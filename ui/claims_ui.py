"""Step 11: weekly claims board, receipt confirm screen, exceptions with draft email, weekly summary.

Only a person moves a claim to approved/paid (the button needs your name). Receipts live in memory for the
session only (the images come from a temp folder that is deleted)."""
import tempfile
from datetime import date
from pathlib import Path

import streamlit as st

from variance import gmail, reimburse as R
from .common import author, usd
from .gmail_ui import get_client

COLUMNS = [("received", "Received"), ("needs_info", "Needs info"), ("ready_to_approve", "Ready to approve"),
           ("approved", "Approved"), ("paid", "Paid")]
IMG = {".png", ".jpg", ".jpeg", ".gif", ".webp"}


def _threshold():
    return float(st.session_state.settings.get("ocr_confidence", 0.8))


def _intake(c):
    """Fetch the chosen reimbursement label: fillable PDFs = claim forms, everything else = receipts."""
    ss = st.session_state
    s = ss.settings
    label = s.get("gmail", {}).get("reimbursement_label")
    if not label:
        st.info("Pick the reimbursement label on the Email screen (Connection tab) first.")
        return
    forms = R.load_form_profiles()
    name = st.selectbox("Claim form layout", ["(guess from the form)"] + list(forms), key="form_prof")
    if st.button("Fetch this week's claims from email", type="primary"):
        notes, n = [], 0
        try:
            with gmail.fetched(c, s, label, exts=(".pdf", ".png", ".jpg", ".jpeg")) as msgs:
                for m in msgs:
                    claim, form_files = None, set()
                    for f in m["files"]:
                        fields = R.read_form_fields(f) if f.suffix.lower() == ".pdf" else {}
                        if fields and claim is None:
                            prof = forms.get(name) or R.guess_form_profile(fields)
                            claim = R.read_claim_form(f, prof, claim_id=m["id"])
                            claim.setdefault("email", m.get("from", ""))
                            R.upsert_claim(s, claim, by="system")
                            form_files.add(f)
                            n += 1
                    for f in m["files"]:
                        if f in form_files:
                            continue
                        try:
                            rec = R.read_receipt(f, claim_id=m["id"] if claim else None)
                        except R.OcrUnavailable as e:
                            st.warning(str(e))
                            rec = {"receipt_id": f.name, "claim_id": m["id"] if claim else None, "amount_cents": None,
                                   "date": None, "vendor": "", "confidence": 0.0, "confirmed": False,
                                   "source": "manual", "sha256": "", "file": f.name}
                        ss.receipts[rec["receipt_id"]] = rec
                        ss.receipt_blobs[rec["receipt_id"]] = f.read_bytes()
        except gmail.NotAllowed as e:
            st.error(str(e))
            return
        st.success(f"{n} claim(s) read. Receipts needing a check are on the Confirm tab.")


def _recs():
    ss = st.session_state
    claims = list(R.load_claims(ss.settings).values())
    return claims, R.reconcile(claims, list(ss.receipts.values()), _threshold())


def _board():
    ss = st.session_state
    s = ss.settings
    claims, rec = _recs()
    if not claims:
        st.info("No claims yet. Fetch them from email on the first tab.")
        return
    by = {r["claim_id"]: r for r in rec["claims"]}
    cols = st.columns(len(COLUMNS))
    for col, (state, title) in zip(cols, COLUMNS):
        col.markdown(f"**{title}**")
        for cl in [x for x in claims if x["state"] == state]:
            r = by[cl["claim_id"]]
            with col.container(border=True):
                st.markdown(f"**{cl['claim_id'][:12]}**  \n{cl.get('claimant') or '(no name)'}  \n"
                            f"{usd(cl.get('amount_cents') or 0)}")
                st.caption(f"Check: {r['status'].replace('_', ' ')}"
                           + (" - receipt needs confirming" if r["needs_confirmation"] else ""))
                if state != "ready_to_approve" and R.suggested_state(r) == "ready_to_approve":
                    st.caption("Looks ready, but only you can approve it.")
                moves = {"received": [("Needs info", "needs_info"), ("Ready", "ready_to_approve")],
                         "needs_info": [("Ready", "ready_to_approve")],
                         "ready_to_approve": [("Needs info", "needs_info"), ("Approve", "approved")],
                         "approved": [("Mark paid", "paid")], "paid": []}[state]
                for label, to in moves:
                    human = to in ("approved", "paid")
                    if st.button(label, key=f"mv_{cl['claim_id']}_{to}", disabled=human and not author(),
                                 help="Needs your name in the sidebar." if human and not author() else
                                 ("This records that YOU approved it." if to == "approved" else None)):
                        try:
                            R.set_state(s, cl["claim_id"], to, author() or "system", date.today())
                        except ValueError as e:
                            st.error(str(e))
                        else:
                            st.session_state.committed = R.committed_by_line(s)
                            st.rerun()
    st.caption(f"Approved but not yet paid (shown as committed in variance reports): "
               f"{usd(sum(R.committed_by_line(s).values()))}")


def _confirm():
    ss = st.session_state
    st.write("A receipt value that was hard to read does not count until you confirm it. "
             "Check the picture, fix the values if needed, then confirm.")
    todo = [r for r in ss.receipts.values() if not R.counts(r, _threshold())]
    if not todo:
        st.success("Nothing to confirm.")
    for r in todo:
        rid = r["receipt_id"]
        with st.container(border=True):
            left, right = st.columns(2)
            blob = ss.receipt_blobs.get(rid)
            if blob and Path(rid).suffix.lower() in IMG:
                left.image(blob, caption=rid)
            elif blob:
                left.download_button("Open receipt file", blob, rid, key=f"dl_{rid}")
            right.caption(f"Reading confidence: {r['confidence']:.0%}. Claim: {r.get('claim_id') or 'none'}")
            amt = right.number_input("Amount ($)", value=None if r["amount_cents"] is None else r["amount_cents"] / 100,
                                     step=0.01, format="%.2f", key=f"amt_{rid}")
            dt = right.text_input("Date (YYYY-MM-DD)", value=r.get("date") or "", key=f"dt_{rid}")
            ven = right.text_input("Vendor", value=r.get("vendor") or "", key=f"ven_{rid}")
            if right.button("Confirm these values", key=f"cf_{rid}", disabled=not author() or amt is None):
                ss.receipts[rid] = R.confirm(r, author(), int(round(amt * 100)), dt or None, ven)
                st.rerun()
    if not author():
        st.warning("Type your name in the sidebar to confirm values.")


def _exceptions(c):
    s = st.session_state.settings
    claims, rec = _recs()
    byc = {x["claim_id"]: x for x in claims}
    bad = [r for r in rec["claims"] if r["status"] != "matched"]
    if not bad and not rec["unclaimed"]:
        st.success("No exceptions.")
    for r in bad:
        mail = R.exception_email(byc[r["claim_id"]], r)
        with st.container(border=True):
            st.markdown(f"**{r['claim_id'][:12]}**: {', '.join(x.replace('_', ' ') for x in r['statuses'])} "
                        f"(claimed {usd(r['claimed_cents'] or 0)}, receipts counted {usd(r['receipts_cents'])})")
            st.write("Draft email (nothing is sent):")
            st.text(f"To: {mail['to']}\nSubject: {mail['subject']}\n\n{mail['body']}")
            if c and st.button("Create Gmail draft", key=f"ex_{r['claim_id']}", disabled=not mail["to"]):
                gmail.make_draft(c, mail["to"], mail["subject"], mail["body"])
                st.success("Draft created in Gmail.")
    for u in rec["unclaimed"]:
        st.warning(f"Receipt {u['receipt_id']} ({usd(u['amount_cents'] or 0)}) has no claim.")


def _weekly():
    ss = st.session_state
    s = ss.settings
    claims, rec = _recs()
    if not claims:
        st.info("No claims yet.")
        return
    week = st.text_input("Week label", value=f"week of {date.today():%Y-%m-%d}")
    summ = R.weekly_summary(s, rec["claims"], week)
    st.text(R.claims_text(summ))
    out = Path(tempfile.mkdtemp()) / "claims.xlsx"
    R.write_claims_excel(claims, rec["claims"], rec["unclaimed"], out)
    st.download_button("Download weekly Excel", out.read_bytes(), "weekly_claims.xlsx",
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


def render():
    ss = st.session_state
    ss.setdefault("receipts", {})
    ss.setdefault("receipt_blobs", {})
    st.title("Reimbursements")
    st.write("Weekly claims from email. The app checks claims against receipts; a person approves.")
    c = get_client()
    t = st.tabs(["Fetch", "Board", "Confirm receipts", "Exceptions", "Weekly summary"])
    with t[0]:
        if c is None:
            st.info("Connect Gmail on the Email screen first.")
        else:
            _intake(c)
    with t[1]:
        _board()
    with t[2]:
        _confirm()
    with t[3]:
        _exceptions(c)
    with t[4]:
        _weekly()
