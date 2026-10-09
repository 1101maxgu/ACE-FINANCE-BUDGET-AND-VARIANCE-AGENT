"""Deterministic variance engine. Pure: no clock, no files. Money in integer cents.

Conventions
- variance_cents = actual - budget, for every line.
- Expense line: over budget (variance > 0) is unfavorable. Revenue line: under target (variance < 0) is unfavorable.
- Expense actual = sum of amount_cents; revenue actual = -sum (actuals: positive = money out, negative = money in).
- variance_pct = variance / |budget| * 100 (2 dp, half-up); NaN when budget is 0.
- flagged = |variance| >= flag_min_cents AND (budget == 0 OR |pct| >= flag_pct). Either direction.
- Actuals whose category maps to no budget line become their own 'UNBUDGETED:<cat>' line (never dropped).
- Actuals dated outside [period start, min(period end, as_of_date)] are excluded and counted in totals.
"""
from decimal import Decimal, ROUND_HALF_UP

import pandas as pd

from .mapping import _norm, exact_targets
from .models import Result

LINE_COLS = ["line_id", "category", "budget_cents", "actual_cents", "variance_cents", "variance_pct",
             "status", "flagged", "line_name", "type", "owner", "budget_source_row", "txn_count"]


def _pct(variance, budget):
    if budget == 0:
        return float("nan")
    return float((Decimal(variance) * 100 / Decimal(abs(budget))).quantize(Decimal("0.01"), ROUND_HALF_UP))


def _day(x):
    return pd.Timestamp(x).normalize() if x not in (None, "") else None


def compute(budget_df, actuals_df, category_map, settings, as_of_date) -> Result:
    """Compare actuals to budget. See module docstring for conventions."""
    category_map = category_map or {}
    min_cents = int(settings.get("flag_min_cents", 15000))
    min_pct = float(settings.get("flag_pct", 10.0))
    period = dict(settings.get("period") or {})
    as_of = _day(as_of_date)
    start, end = _day(period.get("start")), _day(period.get("end"))
    if end is None or as_of < end:
        end = as_of

    a = actuals_df.copy()
    a["date"] = pd.to_datetime(a["date"])
    keep = (a["date"] <= end) & (a["date"] >= start if start is not None else True)
    excluded = a[~keep]
    a = a[keep].copy()

    ids = set(budget_df.line_id)
    targets = exact_targets(budget_df)
    cache = {}

    def assign(cat):
        if cat not in cache:
            if cat in category_map:
                tgt = category_map[cat]
                if tgt and tgt not in ids:
                    raise ValueError(f"Category map sends '{cat}' to unknown budget line '{tgt}'.")
            else:
                t = targets.get(_norm(cat), [])
                tgt = t[0] if len(t) == 1 else ""
            cache[cat] = tgt or f"UNBUDGETED:{cat or '(blank)'}"
        return cache[cat]

    a["line_id"] = [assign(c) for c in a["category"]]
    sums = a.groupby("line_id")["amount_cents"].agg(["sum", "count"])

    rows = []
    for r in budget_df.itertuples():
        rows.append((r.line_id, r.category, r.line_name, r.type, getattr(r, "owner", ""), int(r.budget_cents),
                     getattr(r, "source_row", None)))
    for lid in sorted(set(a.line_id) - ids):
        name = lid.split(":", 1)[1]
        rows.append((lid, name, name, "expense", "", 0, None))

    recs = []
    for lid, cat, name, typ, owner, budget, src in rows:
        s, n = (int(sums.at[lid, "sum"]), int(sums.at[lid, "count"])) if lid in sums.index else (0, 0)
        actual = -s if typ == "revenue" else s
        var = actual - budget
        pct = _pct(var, budget)
        if var == 0:
            status = "on_budget"
        else:
            bad = var < 0 if typ == "revenue" else var > 0
            status = "unfavorable" if bad else "favorable"
        flagged = abs(var) >= min_cents and (budget == 0 or abs(pct) >= min_pct)
        recs.append((lid, cat, budget, actual, var, pct, status, flagged, name, typ, owner, src, n))
    lines = pd.DataFrame(recs, columns=LINE_COLS)

    def tot(typ, col):
        return int(lines.loc[lines.type == typ, col].sum())

    eb, ea, rb, ra = (tot("expense", "budget_cents"), tot("expense", "actual_cents"),
                      tot("revenue", "budget_cents"), tot("revenue", "actual_cents"))
    by_cat = (lines.groupby(["category", "type"], sort=False)[["budget_cents", "actual_cents", "variance_cents"]]
              .sum().reset_index())
    totals = {
        "expense_budget_cents": eb, "expense_actual_cents": ea, "expense_variance_cents": ea - eb,
        "revenue_budget_cents": rb, "revenue_actual_cents": ra, "revenue_variance_cents": ra - rb,
        "net_budget_cents": rb - eb, "net_actual_cents": ra - ea, "net_variance_cents": (ra - ea) - (rb - eb),
        "line_count": int(len(lines)), "flagged_count": int(lines.flagged.sum()),
        "unbudgeted_cents": int(lines.loc[lines.line_id.str.startswith("UNBUDGETED:"), "actual_cents"].sum()),
        "excluded_row_count": int(len(excluded)), "excluded_cents": int(excluded.amount_cents.sum()),
        "by_category": [{k: (int(v) if k.endswith("_cents") else v) for k, v in row.items()}
                        for row in by_cat.to_dict("records")],
    }
    return Result(lines=lines, totals=totals, txns=a, as_of_date=as_of.date(), period=period)
