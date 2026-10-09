"""Deterministic variance engine. Pure: no clock, no files. Money in integer cents.

Conventions
- variance_cents = actual - budget, for every line.
- Expense line: over budget (variance > 0) is unfavorable. Revenue line: under target (variance < 0) is unfavorable.
- Expense actual = sum of amount_cents; revenue actual = -sum (actuals: positive = money out, negative = money in).
- variance_pct = variance / |budget| * 100 (2 dp, half-up); NaN when budget is 0.
- flagged = |variance| >= flag_min_cents AND (budget == 0 OR |pct| >= flag_pct). Either direction (materiality).
- Actuals whose category maps to no budget line become their own 'UNBUDGETED:<cat>' line (never dropped).
- Actuals dated outside [period start, min(period end, as_of_date)] are excluded and counted in totals.

Timing (needs period start+end, or settings['pct_elapsed'] 0-100 override)
- pct_elapsed: share of the period elapsed at as_of_date (0..1).
- expected_cents: budget * pct_elapsed, or the phased budget (monthly_wide months, current month prorated by day).
- pace_variance_cents = actual - expected. pace_flagged: adverse pace variance that is material (same limits).
- projection_cents = actual / pct_elapsed (run-rate); projection_confidence low|medium|high.
- early_warning: expense line that used >= early_warning_pct of its budget and is not over it yet.
- chip: 'over' (unfavorable and flagged) | 'watch' (early warning or adverse pace) | 'ok'.
"""
import calendar
import re
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

import pandas as pd

from .mapping import _norm, exact_targets
from .models import Result

LINE_COLS = ["line_id", "category", "budget_cents", "actual_cents", "variance_cents", "variance_pct",
             "status", "flagged", "line_name", "type", "owner", "budget_source_row", "txn_count",
             "committed_cents", "expected_cents", "pace_variance_cents", "pace_flagged", "projection_cents",
             "projection_variance_cents", "projection_confidence", "early_warning", "chip", "pct_elapsed"]
_INT_COLS = ["expected_cents", "pace_variance_cents", "projection_cents", "projection_variance_cents"]
_MON = {m: i for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split(), 1)}


def _pct(variance, budget):
    if budget == 0:
        return float("nan")
    return float((Decimal(variance) * 100 / Decimal(abs(budget))).quantize(Decimal("0.01"), ROUND_HALF_UP))


def _day(x):
    return pd.Timestamp(x).normalize() if x not in (None, "") else None


def _round(x):
    return int(Decimal(x).quantize(Decimal(1), ROUND_HALF_UP))


def _month_of(header):
    h = str(header).strip().lower()
    m = re.match(r"(\d{4})-(\d{2})", h)
    if m:
        return int(m.group(1)), int(m.group(2))
    y = re.search(r"\d{4}", h)
    return (int(y.group()) if y else None), _MON.get(h[:3])


def _phased_expected(phasing, start, as_of):
    """Sum of phased months up to as_of; the current month is prorated by day."""
    total = Decimal(0)
    for head, cents in phasing:
        y, m = _month_of(head)
        if m is None:
            return None
        y = y or start.year + (1 if m < start.month else 0)
        first, days = date(y, m, 1), calendar.monthrange(y, m)[1]
        done = (as_of.date() - first).days + 1
        total += Decimal(cents) * Decimal(min(max(done, 0), days)) / days
    return _round(total)


def compute(budget_df, actuals_df, category_map, settings, as_of_date, committed=None) -> Result:
    """Compare actuals to budget. See module docstring for conventions.
    committed: optional {line_id: cents} of approved-but-unpaid claims, shown as committed_cents (not in actual)."""
    category_map, committed = category_map or {}, committed or {}
    min_cents = int(settings.get("flag_min_cents", 15000))
    min_pct = float(settings.get("flag_pct", 10.0))
    early = float(settings.get("early_warning_pct", 80))
    period = dict(settings.get("period") or {})
    as_of = _day(as_of_date)
    start, p_end = _day(period.get("start")), _day(period.get("end"))
    end = as_of if p_end is None or as_of < p_end else p_end

    a = actuals_df.copy()
    a["date"] = pd.to_datetime(a["date"])
    keep = (a["date"] <= end) & (a["date"] >= start if start is not None else True)
    if "source_row" not in a:
        a["source_row"] = pd.Series([pd.NA] * len(a), index=a.index, dtype="Int64")
    excluded = a[~keep]
    a = a[keep].copy()

    pct_el = None
    if settings.get("pct_elapsed") not in (None, ""):
        pct_el = min(max(float(settings["pct_elapsed"]) / 100, 0.0), 1.0)
    elif start is not None and p_end is not None:
        total_days = (p_end - start).days + 1
        pct_el = min(max(((end - start).days + 1) / total_days, 0.0), 1.0)

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
    has_phasing = "phasing" in budget_df.columns
    for r in budget_df.itertuples():
        ph = r.phasing if has_phasing and isinstance(r.phasing, list) else None
        rows.append((r.line_id, r.category, r.line_name, r.type, getattr(r, "owner", ""), int(r.budget_cents),
                     getattr(r, "source_row", None), ph))
    for lid in sorted(set(a.line_id) - ids):
        name = lid.split(":", 1)[1]
        rows.append((lid, name, name, "expense", "", 0, None, None))

    recs = []
    for lid, cat, name, typ, owner, budget, src, ph in rows:
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
        exp = pv = proj = pvar = None
        conf, pace_flag = "", False
        if pct_el is not None:
            exp = _phased_expected(ph, start, end) if ph and start is not None else None
            exp = _round(Decimal(budget) * Decimal(str(pct_el))) if exp is None else exp
            pv = actual - exp
            adverse = pv < 0 if typ == "revenue" else pv > 0
            pace_flag = bool(adverse and abs(pv) >= min_cents and (exp == 0 or abs(pv) * 100 >= min_pct * abs(exp)))
            if pct_el > 0:
                proj = actual if pct_el >= 1 else _round(Decimal(actual) / Decimal(str(pct_el)))
                pvar = proj - budget
                conf = "high" if pct_el >= 1 or (pct_el >= 0.5 and n >= 3) else (
                    "low" if pct_el < 0.25 or n < 3 else "medium")
        warn = bool(typ == "expense" and budget > 0 and (pct_el is None or pct_el < 1)
                    and actual * 100 >= early * budget and actual <= budget)
        chip = "over" if status == "unfavorable" and flagged else ("watch" if warn or pace_flag else "ok")
        recs.append([lid, cat, budget, actual, var, pct, status, flagged, name, typ, owner, src, n,
                     int(committed.get(lid, 0)), exp, pv, pace_flag, proj, pvar, conf, warn, chip,
                     float("nan") if pct_el is None else pct_el])
    lines = pd.DataFrame(recs, columns=LINE_COLS)
    for c in _INT_COLS:
        lines[c] = pd.array(lines[c].tolist(), dtype="Int64")

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
        "committed_cents": int(lines.committed_cents.sum()),
        "excluded_row_count": int(len(excluded)), "excluded_cents": int(excluded.amount_cents.sum()),
        "pct_elapsed": None if pct_el is None else round(pct_el * 100, 1),
        "by_category": [{k: (int(v) if k.endswith("_cents") else v) for k, v in row.items()}
                        for row in by_cat.to_dict("records")],
    }
    return Result(lines=lines, totals=totals, txns=a, as_of_date=as_of.date(), period=period)
