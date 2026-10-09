"""Drill-down: top contributors per line with code-assigned tags. The explainer may only cite these tags.

Tags (transaction): one_time_spike = one transaction is >= 50% of the line's actual and its
vendor/description appears once; recurring = same vendor/description 3+ times in the line.
Tag (line): timing_shift = spending is off the expected pace but the line is not materially off its full budget.
"""
import pandas as pd

from .mapping import _norm

TAGS = ("one_time_spike", "recurring", "timing_shift")


def drill(result, line_id, n=5) -> dict:
    """{'line_id', 'tags': [...], 'top_transactions': [{txn_id, date, amount_cents, vendor, description,
    source_row, tag}]} for one line, biggest contributors first (by absolute amount)."""
    L = result.lines.set_index("line_id").loc[line_id]
    sign = -1 if L["type"] == "revenue" else 1
    t = result.txns[result.txns.line_id == line_id].copy()
    t["contrib"] = t.amount_cents * sign
    t["nkey"] = [_norm(v) or _norm(d) for v, d in zip(t.vendor, t.description)]
    counts = t.nkey.value_counts()
    actual = int(L["actual_cents"])

    def tag(r):
        n_same = counts[r.nkey] if r.nkey else 1
        if n_same >= 3:
            return "recurring"
        if actual > 0 and r.contrib * 2 >= actual and n_same == 1:
            return "one_time_spike"
        return ""

    t["tag"] = [tag(r) for r in t.itertuples()]
    t = t.reindex(t.contrib.abs().sort_values(ascending=False, kind="stable").index)
    tags = {x for x in t.tag if x}
    if bool(L["pace_flagged"]) and not bool(L["flagged"]):
        tags.add("timing_shift")
    top = [{"txn_id": r.txn_id, "date": r.date.strftime("%Y-%m-%d"), "amount_cents": int(r.amount_cents),
            "vendor": r.vendor, "description": r.description, "source_row": None if pd.isna(r.source_row) else int(r.source_row), "tag": r.tag}
           for r in t.head(n).itertuples()]
    return {"line_id": line_id, "tags": sorted(tags), "top_transactions": top}

