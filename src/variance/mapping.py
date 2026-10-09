"""Column guessing, saved mapping profiles (user_data/mappings.yaml), category matching."""
import difflib
import re
from pathlib import Path

import yaml

from .ingest import to_cents
from .settings import ROOT

DEFAULT_PATH = ROOT / "user_data" / "mappings.yaml"

_SYN = {
    "budget": {
        "line_id": ["line id", "id", "code", "line code", "account code", "gl code", "item id"],
        "line_name": ["line name", "line item", "line", "item", "name", "description", "account name", "expense", "budget item"],
        "category": ["category", "budget category", "group", "department", "dept", "section", "event", "account category"],
        "type": ["type", "line type", "kind", "income expense"],
        "budget": ["budget", "budget amount", "approved budget", "annual budget", "total budget", "planned", "plan",
                   "allocated", "allocation", "amount", "total"],
        "owner": ["owner", "manager", "responsible", "lead", "contact", "coordinator", "assigned to"],
    },
    "actuals": {
        "txn_id": ["txn id", "transaction id", "id", "reference", "ref", "ref no", "transaction number"],
        "date": ["date", "transaction date", "posted date", "post date", "posting date", "trans date", "txn date"],
        "amount": ["amount", "transaction amount", "amt", "value"],
        "debit": ["debit", "debits", "withdrawal", "money out", "paid out"],
        "credit": ["credit", "credits", "deposit", "money in", "paid in"],
        "category": ["category", "expense category", "gl category", "budget category", "gl account", "account", "class"],
        "description": ["description", "memo", "details", "narrative", "notes", "note", "transaction description"],
        "vendor": ["vendor", "payee", "merchant", "supplier", "paid to", "name"],
    },
}
_MONTH = re.compile(r"^(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b|^\d{4}-\d{2}(-\d{2})?$", re.I)


def _norm(s):
    return " ".join(re.findall(r"[a-z0-9]+", str(s).lower()))


def _fingerprint(df):
    return sorted({_norm(c) for c in df.columns})


def guess_mapping(df, file_kind) -> dict:
    """Guess a mapping from header names. file_kind: 'budget' | 'actuals'.

    The caller adds 'sheet' / 'header_row' from its pickers before saving.
    """
    heads = {_norm(c): c for c in df.columns}
    used, cols = set(), {}
    syn = _SYN[file_kind]
    for exact in (True, False):  # exact synonym match first, then whole-word contains
        for field, words in syn.items():
            if field in cols:
                continue
            for w in words:
                hit = next((h for h in heads if h not in used and
                            (h == w if exact else len(w) >= 4 and re.search(rf"\b{w}\b", h))), None)
                if hit:
                    cols[field] = heads[hit]
                    used.add(hit)
                    break
    m = {"kind": file_kind, "sheet": None, "header_row": 0,
         "columns": {f: cols.get(f) for f in syn}, "fingerprint": _fingerprint(df)}
    if file_kind == "budget":
        months = [c for c in df.columns if _MONTH.match(str(c).strip())]
        wide = len(months) >= 3 and not cols.get("budget")
        m.update(layout="monthly_wide" if wide else "total", month_columns=months if wide else [],
                 type_default="expense")
    else:
        m["date_order"] = None
        if cols.get("debit") and cols.get("credit") and not cols.get("amount"):
            m["sign"] = "debit_credit"
        else:
            neg = pos = 0
            for v in df[cols["amount"]] if cols.get("amount") else []:
                try:
                    c = to_cents(v)
                except ValueError:
                    continue
                neg += (c or 0) < 0
                pos += (c or 0) > 0
            m["sign"] = "negative_expenses" if neg > pos else "positive_expenses"
    return m


# ---------- profiles ----------

def load_profiles(path=None) -> dict:
    """{profile_name: {'budget': {...}, 'actuals': {...}, 'category_map': {...}}}."""
    p = Path(path) if path else DEFAULT_PATH
    return (yaml.safe_load(p.read_text(encoding="utf-8")) or {}) if p.exists() else {}


def _write(profiles, path):
    p = Path(path) if path else DEFAULT_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump(profiles, sort_keys=False), encoding="utf-8")


def save_profile(name, mapping_dict, path=None):
    """Store a mapping under a profile name. mapping_dict is either one guess_mapping() result
    (has 'kind') or {'budget': ..., 'actuals': ...}. Other parts of the profile are kept."""
    profiles = load_profiles(path)
    prof = profiles.setdefault(name, {})
    if "kind" in mapping_dict:
        prof[mapping_dict["kind"]] = mapping_dict
    else:
        prof.update(mapping_dict)
    _write(profiles, path)


def find_profile_by_fingerprint(df, path=None):
    """Name of a saved profile whose budget/actuals headers match df's headers (>=80% overlap)."""
    fp = set(_fingerprint(df))
    for name, prof in load_profiles(path).items():
        for kind in ("budget", "actuals"):
            saved = set((prof.get(kind) or {}).get("fingerprint") or [])
            if saved and len(fp & saved) / len(fp | saved) >= 0.8:
                return name
    return None


# ---------- category mapping ----------

def exact_targets(budget_df) -> dict:
    """normalized name -> [line_ids]. Names = line_id, line_name, and category when it has one line."""
    t = {}
    for r in budget_df.itertuples():
        for n in (r.line_id, r.line_name):
            t.setdefault(_norm(n), []).append(r.line_id)
    for cat, g in budget_df.groupby("category"):
        if len(g) == 1:
            t.setdefault(_norm(cat), []).append(g.line_id.iloc[0])
    return {k: list(dict.fromkeys(v)) for k, v in t.items()}


def suggest_categories(actuals_df, budget_df, saved) -> list:
    """One row per distinct actual category:
    {actual_category, suggestion (a budget line_id or ''), suggestion_label, status, count, total_cents}.
    status: saved | exact | ambiguous | suggested | unmatched. Unmatched money still shows up in
    reports as an 'unbudgeted' line, never dropped."""
    saved = saved or {}
    targets = exact_targets(budget_df)
    labels = dict(zip(budget_df.line_id, budget_df.line_name))
    out = []
    for cat, g in actuals_df.groupby("category"):
        n = _norm(cat)
        if cat in saved:
            sug, status = saved[cat], "saved"
        elif len(targets.get(n, [])) == 1:
            sug, status = targets[n][0], "exact"
        elif len(targets.get(n, [])) > 1:
            sug, status = targets[n][0], "ambiguous"
        else:
            close = difflib.get_close_matches(n, list(targets), n=1, cutoff=0.6)
            sug, status = (targets[close[0]][0], "suggested") if close else ("", "unmatched")
        out.append({"actual_category": cat, "suggestion": sug, "suggestion_label": labels.get(sug, ""),
                    "status": status, "count": int(len(g)), "total_cents": int(g.amount_cents.sum())})
    return out


def save_category_map(profile_name, category_map, path=None):
    """Save {actual_category: line_id} for a profile ('' = keep as unbudgeted)."""
    profiles = load_profiles(path)
    profiles.setdefault(profile_name, {})["category_map"] = dict(category_map)
    _write(profiles, path)
