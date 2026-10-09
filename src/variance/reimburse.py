"""Reimbursement pipeline: read forms/receipts, reconcile (pure code), claim states, weekly summary.

Amounts are integer cents. A receipt/form value counts toward a claim only if its confidence is at or above the
threshold OR a person has confirmed it (item['confirmed'] = True). Only a person marks a claim approved.
"""
import hashlib
import json
import re
from pathlib import Path

import yaml

from .ingest import IngestError, _parse_dates, to_cents
from .mapping import _norm
from .settings import ROOT, data_dir

FORM_PROFILES = ROOT / "user_data" / "form_profiles.yaml"
STATES = ("received", "needs_info", "ready_to_approve", "approved", "paid")
PRIORITY = ("missing_receipt", "duplicate_receipt", "total_mismatch", "amount_mismatch", "matched")


class OcrUnavailable(Exception):
    """Plain-language message: Tesseract is not installed / not found."""


# ---------- fillable PDF forms ----------

def _txt(v):
    if isinstance(v, bytes):
        return v.decode("utf-16", "replace") if v[:2] in (b"\xfe\xff", b"\xff\xfe") else v.decode("latin-1")
    return "" if v is None else str(v)


def read_form_fields(pdf_path) -> dict:
    """{field name: value} of a fillable PDF form (empty dict if the PDF has no form fields)."""
    import pdfplumber
    out = {}
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            for a in page.annots:
                d = a.get("data") or {}
                if d.get("T") is not None:
                    out[_txt(d["T"])] = _txt(d.get("V"))
    return out


_FORM_SYN = {
    "claimant": ["claimant", "name", "employee", "payee", "submitted by", "full name"],
    "amount": ["amount", "total", "total amount", "amount requested", "reimbursement amount"],
    "date": ["date", "expense date", "date of expense"],
    "description": ["description", "purpose", "reason", "business purpose"],
    "email": ["email", "e mail", "email address"],
    "line_id": ["budget line", "line id", "account", "category"],
}


def guess_form_profile(fields) -> dict:
    """{claim field: pdf field name or None} guessed from PDF field names."""
    norm = {_norm(f): f for f in fields}
    out = {}
    for k, words in _FORM_SYN.items():
        out[k] = next((norm[w] for w in words if w in norm), None)
    return out


def load_form_profiles(path=None) -> dict:
    p = Path(path) if path else FORM_PROFILES
    return (yaml.safe_load(p.read_text(encoding="utf-8")) or {}) if p.exists() else {}


def save_form_profile(name, mapping, path=None):
    p = Path(path) if path else FORM_PROFILES
    p.parent.mkdir(parents=True, exist_ok=True)
    profiles = load_form_profiles(p)
    profiles[name] = dict(mapping)
    p.write_text(yaml.safe_dump(profiles, sort_keys=False), encoding="utf-8")


def read_claim_form(pdf_path, form_profile, claim_id=None) -> dict:
    """Claim dict from a fillable PDF using a form profile. Form values are typed text, so confidence is 1.0."""
    f = read_form_fields(pdf_path)
    g = lambda k: f.get(form_profile.get(k) or "", "").strip()
    try:
        cents = to_cents(g("amount"))
    except ValueError:
        cents = None
    return {"claim_id": claim_id or Path(pdf_path).stem, "claimant": g("claimant"), "email": g("email"),
            "amount_cents": cents, "date": g("date"), "description": g("description"), "line_id": g("line_id"),
            "confidence": 1.0 if cents is not None else 0.0, "confirmed": False, "source": "form"}


# ---------- receipts: text, OCR ----------

def _tesseract(cmd=None):
    import pytesseract
    if cmd:
        pytesseract.pytesseract.tesseract_cmd = cmd
    try:
        pytesseract.get_tesseract_version()
    except pytesseract.TesseractNotFoundError:
        raise OcrUnavailable(
            "Reading scanned receipts needs the free 'Tesseract OCR' program, which is not installed on this computer. "
            "Install it (https://github.com/UB-Mannheim/tesseract/wiki), then restart the app. Until then, "
            "type the receipt amounts in by hand on the confirm screen.")
    return pytesseract


def _ocr_image(img, cmd=None):
    t = _tesseract(cmd)
    d = t.image_to_data(img, output_type=t.Output.DICT)
    lines = {}
    for i, w in enumerate(d["text"]):
        if w.strip() and float(d["conf"][i]) >= 0:
            lines.setdefault((d["block_num"][i], d["par_num"][i], d["line_num"][i]), []).append((w, float(d["conf"][i])))
    return [(" ".join(w for w, _ in ws), sum(c for _, c in ws) / len(ws) / 100) for ws in lines.values()]


def receipt_lines(path, tesseract_cmd=None) -> tuple:
    """(lines, source): lines = [(text, confidence 0..1)]. PDFs with real text are read directly (source 'text',
    confidence 1.0); scans and images use OCR (source 'ocr'; raises OcrUnavailable if Tesseract is missing)."""
    p = Path(path)
    if p.suffix.lower() == ".pdf":
        import pdfplumber
        with pdfplumber.open(p) as pdf:
            text = "\n".join((pg.extract_text() or "") for pg in pdf.pages)
            if text.strip():
                return [(ln, 1.0) for ln in text.splitlines() if ln.strip()], "text"
            lines = []
            for pg in pdf.pages:
                lines += _ocr_image(pg.to_image(resolution=200).original, tesseract_cmd)
            return lines, "ocr"
    from PIL import Image
    with Image.open(p) as im:
        return _ocr_image(im, tesseract_cmd), "ocr"


_MONEY = re.compile(r"(?<![\d.])\$?\s*(\d{1,3}(?:,\d{3})+|\d+)\.(\d{2})\b")
_DATE = re.compile(r"\b(\d{4}-\d{2}-\d{2}|\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}|[A-Z][a-z]{2,8}\.? \d{1,2},? \d{4})\b")


def parse_receipt(lines) -> dict:
    """Pull amount, date, vendor from [(text, confidence)] lines. The amount comes from a 'total' line when there
    is one (else the largest amount). Dates that could be day-first or month-first are left blank."""
    best, best_key = None, None
    for text, conf in lines:
        for m in _MONEY.finditer(text):
            cents = int(m.group(1).replace(",", "")) * 100 + int(m.group(2))
            low = text.lower()
            key = (2 if "total" in low and "subtotal" not in low and "sub total" not in low else 1, cents)
            if best_key is None or key > best_key:
                best, best_key = (cents, conf), key
    date = None
    for text, _ in lines:
        m = _DATE.search(text)
        if m:
            try:
                date = _parse_dates([m.group(1)], None, "Receipt")[0].isoformat()
            except IngestError:
                date = None
            break
    vendor = next((t.strip() for t, _ in lines if t.strip()), "")
    return {"amount_cents": best[0] if best else None, "confidence": round(best[1], 3) if best else 0.0,
            "date": date, "vendor": vendor}


def read_receipt(path, claim_id=None, tesseract_cmd=None) -> dict:
    """Receipt dict from a file: {receipt_id, claim_id, amount_cents, date, vendor, confidence, confirmed, source, sha256, file}."""
    p = Path(path)
    lines, source = receipt_lines(p, tesseract_cmd)
    return {"receipt_id": p.name, "claim_id": claim_id, **parse_receipt(lines), "confirmed": False, "source": source,
            "sha256": hashlib.sha256(p.read_bytes()).hexdigest(), "file": p.name}


def confirm(item, by, amount_cents=None, date=None, vendor=None) -> dict:
    """A person confirms (and may correct) a receipt/claim value. Returns an updated copy."""
    if not by or not by.strip():
        raise ValueError("Please enter your name to confirm a value.")
    out = dict(item, confirmed=True, confirmed_by=by.strip())
    for k, v in (("amount_cents", amount_cents), ("date", date), ("vendor", vendor)):
        if v is not None:
            out[k] = v
    return out


def counts(item, threshold) -> bool:
    """True if the item's amount may be used: present and (confirmed or confidence >= threshold)."""
    return item.get("amount_cents") is not None and (bool(item.get("confirmed")) or item.get("confidence", 0) >= threshold)


# ---------- reconcile (pure) ----------

def reconcile(claims, receipts, threshold=0.8) -> dict:
    """Match receipts to claims by claim_id.

    Returns {'claims': [{claim_id, status, statuses[], claimed_cents, receipts_cents, receipt_ids[],
    needs_confirmation[], duplicate_ids[]}], 'unclaimed': [{receipt_id, status:'unclaimed_receipt', amount_cents}]}.
    Statuses: matched, amount_mismatch, missing_receipt, duplicate_receipt, total_mismatch (items don't add up
    to the stated total), unclaimed_receipt. Unconfirmed low-confidence receipts do NOT count toward receipts_cents.
    """
    seen, dup = {}, {}
    for r in receipts:  # first receipt wins; later identical ones are duplicates
        keys = [("sha", r["sha256"])] if r.get("sha256") else []
        if r.get("amount_cents") is not None and r.get("date"):
            keys.append(("v", r["amount_cents"], r["date"], _norm(r.get("vendor", ""))))
        first = next((seen[k] for k in keys if k in seen), None)
        if first:
            dup[r["receipt_id"]] = first
        for k in keys:
            seen.setdefault(k, r["receipt_id"])
    ids = {c["claim_id"] for c in claims}
    out = []
    for c in claims:
        mine = [r for r in receipts if r.get("claim_id") == c["claim_id"]]
        good = [r for r in mine if r["receipt_id"] not in dup]
        usable = [r for r in good if counts(r, threshold)]
        total = sum(r["amount_cents"] for r in usable)
        st = []
        if not good:
            st.append("missing_receipt")
        if any(r["receipt_id"] in dup for r in mine):
            st.append("duplicate_receipt")
        if c.get("items") and sum(c["items"]) != c.get("amount_cents"):
            st.append("total_mismatch")
        if good and total != c.get("amount_cents"):
            st.append("amount_mismatch")
        st = st or ["matched"]
        out.append({"claim_id": c["claim_id"], "status": min(st, key=PRIORITY.index), "statuses": st,
                    "claimed_cents": c.get("amount_cents"), "receipts_cents": total,
                    "receipt_ids": [r["receipt_id"] for r in good],
                    "needs_confirmation": [r["receipt_id"] for r in good if not counts(r, threshold)],
                    "duplicate_ids": [r["receipt_id"] for r in mine if r["receipt_id"] in dup]})
    unclaimed = [{"receipt_id": r["receipt_id"], "status": "unclaimed_receipt", "amount_cents": r.get("amount_cents")}
                 for r in receipts if r.get("claim_id") not in ids and r["receipt_id"] not in dup]
    return {"claims": out, "unclaimed": unclaimed}


# ---------- claim store, states ----------

def _store(settings):
    # ponytail: one shared file; per-author files if two people save at once and Drive makes conflict copies
    return data_dir(settings) / "claims.json"


def load_claims(settings) -> dict:
    """{claim_id: {claim..., state, history[]}}."""
    p = _store(settings)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def _save(settings, claims):
    p = _store(settings)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(claims, indent=2), encoding="utf-8")


def upsert_claim(settings, claim, by="system") -> dict:
    """Add/refresh a claim; new claims start as 'received'. Never changes the state of an existing claim."""
    claims = load_claims(settings)
    cur = claims.get(claim["claim_id"], {"state": "received", "history": [{"state": "received", "by": by}]})
    claims[claim["claim_id"]] = {**cur, **{k: v for k, v in claim.items() if k not in ("state", "history")}}
    _save(settings, claims)
    return claims[claim["claim_id"]]


def set_state(settings, claim_id, state, by, date=None) -> dict:
    """Move a claim along the board. 'approved' and 'paid' require a named person (`by`)."""
    if state not in STATES:
        raise ValueError(f"state must be one of {STATES}")
    if state in ("approved", "paid") and not (by and by.strip() and by != "system"):
        raise ValueError("Only a person can mark a claim approved or paid: please enter your name.")
    claims = load_claims(settings)
    c = claims[claim_id]
    c["state"] = state
    c["history"].append({"state": state, "by": by, "date": str(date) if date else None})
    _save(settings, claims)
    return c


def suggested_state(rec) -> str:
    """Board column implied by reconcile status. NEVER 'approved': that is a human click."""
    return "ready_to_approve" if rec["status"] == "matched" and not rec["needs_confirmation"] else "needs_info"


def committed_by_line(settings) -> dict:
    """{line_id: cents} of approved-but-unpaid claims (pass to pipeline.run(committed=...)). Claims without a
    line are under ''."""
    out = {}
    for c in load_claims(settings).values():
        if c["state"] == "approved" and c.get("amount_cents"):
            out[c.get("line_id") or ""] = out.get(c.get("line_id") or "", 0) + c["amount_cents"]
    return out


# ---------- weekly status, exceptions ----------

def weekly_summary(settings, recs, week_label="") -> dict:
    """Numbers for the weekly status (feed to claims_text / the number guard). recs = reconcile(...)['claims']."""
    claims = load_claims(settings)
    by_state = {s: 0 for s in STATES}
    for c in claims.values():
        by_state[c["state"]] += 1
    st = {}
    for r in recs:
        st[r["status"]] = st.get(r["status"], 0) + 1
    return {"week": week_label, "claims_count": len(recs), "by_state": by_state, "by_status": st,
            "claimed_cents": sum(r["claimed_cents"] or 0 for r in recs),
            "ready_cents": sum(r["claimed_cents"] or 0 for r in recs if suggested_state(r) == "ready_to_approve"),
            "committed_cents": sum(committed_by_line(settings).values()),
            "exceptions": [{"claim_id": r["claim_id"], "status": r["status"],
                            "claimed_cents": r["claimed_cents"], "receipts_cents": r["receipts_cents"]}
                           for r in recs if r["status"] != "matched"]}


def _usd(c):
    return f"${abs(c) // 100:,}.{abs(c) % 100:02d}"


def claims_text(summary) -> str:
    """Plain-language weekly status from the summary (template; Claude may rephrase it but must pass
    explain.number_guard(text, summary))."""
    s = summary
    lines = [f"{s['claims_count']} claims this week{' (' + s['week'] + ')' if s['week'] else ''}, "
             f"{_usd(s['claimed_cents'])} claimed; {_usd(s['ready_cents'])} are ready for approval.",
             f"{_usd(s['committed_cents'])} is approved but not yet paid."]
    lines += [f"Needs attention: {e['claim_id']} is {e['status'].replace('_', ' ')} "
              f"(claimed {_usd(e['claimed_cents'] or 0)}, receipts {_usd(e['receipts_cents'])})." for e in s["exceptions"]]
    return "\n".join(lines)


def exception_email(claim, rec) -> dict:
    """Draft (subject, body, to) asking the claimant to fix an exception. A person sends it."""
    ask = {"missing_receipt": "attach the receipt", "duplicate_receipt": "check the duplicated receipt",
           "amount_mismatch": "check the amount, which does not match the receipts",
           "total_mismatch": "check the line items, which do not add up to the total"}.get(rec["status"], "check the claim")
    return {"to": claim.get("email", ""), "subject": f"Reimbursement claim {claim['claim_id']}: please {ask}",
            "body": f"Hi {claim.get('claimant', '')},\n\nWe could not approve claim {claim['claim_id']} yet. "
                    f"Could you please {ask}?\n\nThanks"}


def write_claims_excel(claims, recs, unclaimed, out_path) -> str:
    """Weekly Excel: Claims sheet (status, state) and Exceptions."""
    from openpyxl import Workbook
    from openpyxl.styles import Font
    wb = Workbook()
    ws = wb.active
    ws.title = "Claims"
    ws.append(["Claim", "Claimant", "Claimed", "Receipts counted", "Status", "Needs confirmation", "Budget line"])
    byid = {c["claim_id"]: c for c in claims}
    for r in recs:
        c = byid.get(r["claim_id"], {})
        ws.append([r["claim_id"], c.get("claimant", ""), (r["claimed_cents"] or 0) / 100, r["receipts_cents"] / 100,
                   r["status"], ", ".join(r["needs_confirmation"]), c.get("line_id", "")])
    for c in ws[1]:
        c.font = Font(bold=True)
    ws.freeze_panes = "A2"
    ws2 = wb.create_sheet("Exceptions")
    ws2.append(["Item", "Status", "Detail"])
    for r in recs:
        if r["status"] != "matched":
            ws2.append([r["claim_id"], r["status"], ", ".join(r["statuses"])])
    for u in unclaimed:
        ws2.append([u["receipt_id"], u["status"], "" if u["amount_cents"] is None else u["amount_cents"] / 100])
    ws2.freeze_panes = "A2"
    wb.save(out_path)
    return str(out_path)
