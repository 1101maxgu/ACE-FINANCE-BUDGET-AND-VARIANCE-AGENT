"""Hand-calculated fixtures. Amounts in cents; actuals: positive = money out, negative = money in."""
import datetime as dt
import math

import pandas as pd
import pytest

from variance.calc import compute

SETTINGS = {"flag_pct": 10.0, "flag_min_cents": 15000}
AS_OF = dt.date(2026, 3, 31)


def budget():
    rows = [  # id, category, name, type, cents
        ("L1", "Food", "Food", "expense", 80000),
        ("L2", "Venue", "Venue", "expense", 50000),
        ("L3", "Tickets", "Tickets", "revenue", 200000),
        ("L4", "Misc", "Misc", "expense", 0),
        ("L5", "Rounding", "Rounding", "expense", 30000),
        ("L6", "Even", "Even", "expense", 1000),
    ]
    return pd.DataFrame(rows, columns=["line_id", "category", "line_name", "type", "budget_cents"]).assign(owner="")


def actuals():
    rows = [
        ("T1", "2026-01-10", 70000, "Food"), ("T2", "2026-02-10", 50000, "Food"),
        ("T8", "2026-02-11", -10000, "Food"),           # refund -> Food actual 110000
        ("T3", "2026-03-01", -150000, "Tickets"),       # money in
        ("T4", "2026-03-02", 5000, "Misc"),
        ("T5", "2026-03-03", 31000, "Rounding"),
        ("T6", "2026-03-04", 1000, "Even"),
        ("T7", "2026-03-05", 20000, "Parking"),         # no budget line
        ("T9", "2026-04-01", 999, "Food"),              # after as_of -> excluded
    ]
    df = pd.DataFrame(rows, columns=["txn_id", "date", "amount_cents", "category"])
    df["date"] = pd.to_datetime(df["date"])
    return df.assign(description="", vendor="")


@pytest.fixture(scope="module")
def res():
    return compute(budget(), actuals(), {}, SETTINGS, AS_OF)


def line(res, lid):
    return res.lines.set_index("line_id").loc[lid]


def test_expense_over_budget_flagged(res):
    r = line(res, "L1")  # 110000 - 80000 = 30000 -> 37.5%
    assert (r.actual_cents, r.variance_cents, r.variance_pct) == (110000, 30000, 37.5)
    assert r.status == "unfavorable" and r.flagged


def test_zero_actuals_is_favorable_and_minus_100_pct(res):
    r = line(res, "L2")
    assert (r.actual_cents, r.variance_cents, r.variance_pct, r.status) == (0, -50000, -100.0, "favorable")
    assert r.flagged


def test_revenue_flip(res):
    r = line(res, "L3")  # revenue 150000 vs 200000: under target is BAD
    assert (r.actual_cents, r.variance_cents, r.variance_pct) == (150000, -50000, -25.0)
    assert r.status == "unfavorable" and r.flagged


def test_zero_budget_guarded(res):
    r = line(res, "L4")
    assert r.variance_cents == 5000 and math.isnan(r.variance_pct)
    assert r.status == "unfavorable" and not r.flagged   # 5000 < 15000 minimum


def test_rounding_half_up(res):
    r = line(res, "L5")  # 1000/30000 = 3.333...
    assert r.variance_pct == 3.33 and not r.flagged


def test_on_budget(res):
    assert line(res, "L6").status == "on_budget"


def test_unbudgeted_category_is_kept_and_flagged(res):
    r = line(res, "UNBUDGETED:Parking")
    assert (r.budget_cents, r.actual_cents, r.status) == (0, 20000, "unfavorable")
    assert math.isnan(r.variance_pct) and r.flagged       # zero budget: dollar rule alone


def test_totals(res):
    t = res.totals
    # expense budget 80000+50000+0+30000+1000; actual 110000+0+5000+31000+1000+20000
    assert (t["expense_budget_cents"], t["expense_actual_cents"]) == (161000, 167000)
    assert (t["revenue_budget_cents"], t["revenue_actual_cents"]) == (200000, 150000)
    assert (t["net_budget_cents"], t["net_actual_cents"], t["net_variance_cents"]) == (39000, -17000, -56000)
    assert t["flagged_count"] == 4 and t["line_count"] == 7 and t["unbudgeted_cents"] == 20000
    assert (t["excluded_row_count"], t["excluded_cents"]) == (1, 999)
    food = [c for c in t["by_category"] if c["category"] == "Food"][0]
    assert (food["budget_cents"], food["actual_cents"], food["variance_cents"]) == (80000, 110000, 30000)


def test_category_map_overrides_and_empty_means_unbudgeted():
    r = compute(budget(), actuals(), {"Parking": "L6", "Food": ""}, SETTINGS, AS_OF)
    assert line(r, "L6").actual_cents == 21000
    assert line(r, "UNBUDGETED:Food").actual_cents == 110000 and line(r, "L1").actual_cents == 0


def test_bad_map_target_raises():
    with pytest.raises(ValueError):
        compute(budget(), actuals(), {"Parking": "NOPE"}, SETTINGS, AS_OF)


def test_period_start_and_end_limit_rows():
    s = {**SETTINGS, "period": {"label": "Feb", "start": "2026-02-01", "end": "2026-02-28"}}
    r = compute(budget(), actuals(), {}, s, AS_OF)
    assert line(r, "L1").actual_cents == 40000      # T2 50000 + T8 -10000
    assert r.totals["excluded_row_count"] == 7      # 9 rows, 2 in Feb


def test_as_of_date_is_the_cutoff_not_the_clock():
    r = compute(budget(), actuals(), {}, SETTINGS, dt.date(2026, 1, 31))
    assert line(r, "L1").actual_cents == 70000 and r.as_of_date == dt.date(2026, 1, 31)


def test_no_actuals_at_all():
    r = compute(budget(), actuals().iloc[0:0], {}, SETTINGS, AS_OF)
    assert r.totals["expense_actual_cents"] == 0 and r.totals["flagged_count"] == 4  # L1, L2, L3, L5 are 100% under; L6 is under $150
