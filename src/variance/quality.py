"""Data-quality checks (pure). A 'critical' finding marks the report unreconciled."""
import pandas as pd

from .mapping import _norm


def _usd(c):
    c = int(c)
    return f"{'-' if c < 0 else ''}${abs(c) // 100:,}.{abs(c) % 100:02d}"


def _f(code, severity, message, rows=(), txn_ids=()):
    return {"code": code, "severity": severity, "message": message, "count": len(rows) or len(txn_ids),
            "rows": [int(r) for r in rows if pd.notna(r)], "txn_ids": list(txn_ids)}


def run_checks(budget_df, actuals_df, result, settings, stated_total_cents=None, intentional_dupes=()) -> list:
    """Findings: [{code, severity 'critical'|'warning', message, count, rows (source rows), txn_ids}].

    Codes: uncategorized, unmapped_category, possible_duplicate, missing_period, unreconciled.
    stated_total_cents: the total the user says the actuals file should add up to (net, positive = spend).
    intentional_dupes: txn_ids the user marked 'duplicate is intentional'.
    """
    t = result.txns
    out = []
    blank = t[t.category.astype(str).str.strip() == ""]
    if len(blank):
        out.append(_f("uncategorized", "warning",
                      f"{len(blank)} transaction(s) have no category.", blank.source_row, blank.txn_id))
    unm = t[t.line_id.str.startswith("UNBUDGETED:") & (t.category.astype(str).str.strip() != "")]
    if len(unm):
        out.append(_f("unmapped_category", "warning",
                      f"{len(unm)} transaction(s) ({_usd(unm.amount_cents.sum())}) are in categories with no budget line.",
                      unm.source_row, unm.txn_id))
    key = t.assign(_k=[(d, a, _norm(v) or _norm(x)) for d, a, v, x in
                       zip(t.date, t.amount_cents, t.vendor, t.description)])
    for _, g in key.groupby("_k"):
        g = g[~g.txn_id.isin(set(intentional_dupes))]
        if len(g) > 1:
            out.append(_f("possible_duplicate", "warning",
                          f"Possible duplicate: {len(g)} transactions on {g.date.iloc[0]:%Y-%m-%d} for "
                          f"{_usd(g.amount_cents.iloc[0])}.", g.source_row, g.txn_id))
    p = result.period or {}
    if p.get("start"):
        end = min(pd.Timestamp(p.get("end") or result.as_of_date), pd.Timestamp(result.as_of_date))
        have = set(t.date.dt.to_period("M"))
        for m in pd.period_range(pd.Timestamp(p["start"]), end, freq="M"):
            if m not in have:
                out.append(_f("missing_period", "warning", f"No transactions at all in {m}."))
    if stated_total_cents is not None:
        got = int(t.amount_cents.sum())
        if got != int(stated_total_cents):
            out.append(_f("unreconciled", "critical",
                          f"Actuals add up to {_usd(got)} but you stated {_usd(stated_total_cents)} "
                          f"(difference {_usd(got - int(stated_total_cents))})."))
    return out


def is_unreconciled(findings) -> bool:
    return any(f["severity"] == "critical" for f in findings)
