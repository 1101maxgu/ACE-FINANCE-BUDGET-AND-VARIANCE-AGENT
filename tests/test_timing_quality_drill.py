"""Steps 6-9. Hand-computed inline fixtures."""
import datetime as dt

import pandas as pd
import pytest

from variance import facts as F, explain, pipeline, quality, settings as S
from variance.calc import compute
from variance.drilldown import drill


def bdf(rows, phasing=None):
    df = pd.DataFrame(rows, columns=["line_id", "category", "line_name", "type", "budget_cents"]).assign(owner="")
    if phasing:
        df["phasing"] = [phasing.get(i) for i in df.line_id]
    return df


def adf(rows):
    df = pd.DataFrame(rows, columns=["txn_id", "date", "amount_cents", "category", "vendor"])
    df["date"] = pd.to_datetime(df["date"])
    return df.assign(description="", source_row=range(2, len(df) + 2))


def line(res, lid):
    return res.lines.set_index("line_id").loc[lid]


# ---- Step 6 ----

def test_run_requires_period_and_remembers_it(tmp_path):
    b, a = tmp_path / "b.csv", tmp_path / "a.csv"
    b.write_text("Line,Amount\nFood,1000\n")
    a.write_text("Date,Cat,Amt\n2026-01-05,Food,400\n2026-01-06,Food,100\n")
    prof = {"budget": {"columns": {"line_name": "Line", "budget": "Amount"}},
            "actuals": {"sign": "positive_expenses", "columns": {"date": "Date", "category": "Cat", "amount": "Amt"}},
            "category_map": {}}
    with pytest.raises(ValueError, match="period"):
        pipeline.run(b, a, S.load_settings(tmp_path / "none.yaml"), prof)
    st = S.load_settings(tmp_path / "none.yaml")
    st["period"] = {"label": "Jan", "start": "2026-01-01", "end": "2026-01-31"}
    out = pipeline.run(b, a, st, prof, settings_path=tmp_path / "s.yaml", remember=True)
    assert out["result"].as_of_date == dt.date(2026, 1, 31)           # defaults to period end, not the clock
    assert out["result"].lines.set_index("line_id").loc["L001", "actual_cents"] == 50000
    assert out["facts"]["period"]["label"] == "Jan"
    assert S.load_settings(tmp_path / "s.yaml")["last_period"]["label"] == "Jan"


# ---- Step 7 ----

P = {"period": {"label": "P", "start": "2026-01-01", "end": "2026-01-10"}, "flag_min_cents": 15000, "flag_pct": 10.0}


def test_pace_and_projection():
    b = bdf([("A", "A", "A", "expense", 200000), ("B", "B", "B", "expense", 100000)])
    a = adf([("1", "2026-01-02", 50000, "A", ""), ("2", "2026-01-03", 50000, "A", ""), ("3", "2026-01-04", 30000, "A", ""),
             ("4", "2026-01-04", 85000, "B", "")])
    r = compute(b, a, {}, P, dt.date(2026, 1, 5))        # 5 of 10 days = 50%
    A = line(r, "A")                                      # actual 130000, expected 100000
    assert (A.pct_elapsed, A.expected_cents, A.pace_variance_cents) == (0.5, 100000, 30000)
    assert A.pace_flagged and A.projection_cents == 260000 and A.projection_variance_cents == 60000
    assert A.projection_confidence == "high" and A.chip == "watch" and not A.early_warning
    B = line(r, "B")                                      # 85000 of 100000 = 85% >= 80%, not over
    assert B.early_warning and B.projection_confidence == "low"   # one transaction only
    assert r.totals["pct_elapsed"] == 50.0


def test_pct_elapsed_override_and_no_period():
    b = bdf([("A", "A", "A", "expense", 200000)])
    a = adf([("1", "2026-01-02", 10000, "A", "")])
    r = compute(b, a, {}, {"pct_elapsed": 25}, dt.date(2026, 1, 5))
    assert line(r, "A").expected_cents == 50000 and line(r, "A").projection_cents == 40000
    r = compute(b, a, {}, {}, dt.date(2026, 1, 5))
    assert pd.isna(line(r, "A").expected_cents) and pd.isna(line(r, "A").projection_cents)


def test_phased_budget_expected():
    ph = {"A": [("Jan", 10000), ("Feb", 20000), ("Mar", 30000)]}
    b = bdf([("A", "A", "A", "expense", 60000)], ph)
    s = {"period": {"label": "Q1", "start": "2026-01-01", "end": "2026-03-31"}}
    r = compute(b, adf([("1", "2026-01-05", 100, "A", "")]), {}, s, dt.date(2026, 2, 14))
    assert line(r, "A").expected_cents == 20000      # all of Jan + 14/28 of Feb (linear would say 30000)


def test_revenue_pace_is_adverse_when_behind():
    b = bdf([("R", "R", "R", "revenue", 200000)])
    r = compute(b, adf([("1", "2026-01-02", -40000, "R", "")]), {}, P, dt.date(2026, 1, 5))
    R = line(r, "R")                                      # earned 40000, expected 100000 -> behind
    assert R.pace_variance_cents == -60000 and R.pace_flagged


def test_committed_is_shown_not_added_to_actual():
    b = bdf([("A", "A", "A", "expense", 100000)])
    r = compute(b, adf([("1", "2026-01-02", 1000, "A", "")]), {}, P, dt.date(2026, 1, 5), committed={"A": 7000})
    assert line(r, "A").committed_cents == 7000 and line(r, "A").actual_cents == 1000
    assert r.totals["committed_cents"] == 7000


# ---- Step 8 ----

def quality_result():
    b = bdf([("F", "Food", "Food", "expense", 10000)])
    a = adf([("A1", "2026-01-05", 1000, "Food", "Acme Co"), ("A2", "2026-01-05", 1000, "Food", "ACME co."),
             ("A3", "2026-03-01", 500, "", "x"), ("A4", "2026-03-02", 700, "Gym", "y")])
    s = {"period": {"label": "Q1", "start": "2026-01-01", "end": "2026-03-31"}}
    return b, a, s, compute(b, a, {}, s, dt.date(2026, 3, 31))


def codes(findings):
    return {f["code"]: f for f in findings}


def test_quality_checks():
    b, a, s, r = quality_result()
    f = codes(quality.run_checks(b, a, r, s))
    assert f["possible_duplicate"]["txn_ids"] == ["A1", "A2"] and f["possible_duplicate"]["rows"] == [2, 3]
    assert f["uncategorized"]["txn_ids"] == ["A3"]
    assert f["unmapped_category"]["txn_ids"] == ["A4"]
    assert f["missing_period"]["message"] == "No transactions at all in 2026-02."
    assert "unreconciled" not in f                       # nothing stated -> nothing to reconcile
    assert not quality.is_unreconciled(list(f.values()))


def test_intentional_duplicate_and_reconciliation():
    b, a, s, r = quality_result()
    f = codes(quality.run_checks(b, a, r, s, stated_total_cents=3200, intentional_dupes=["A1"]))
    assert "possible_duplicate" not in f and "unreconciled" not in f      # 1000+1000+500+700 = 3200
    f = quality.run_checks(b, a, r, s, stated_total_cents=3000)
    u = codes(f)["unreconciled"]
    assert u["severity"] == "critical" and "difference $2.00" in u["message"]
    assert quality.is_unreconciled(f)
    r.quality = f
    facts = F.build_facts(r, s)
    assert facts["unreconciled"] is True
    assert explain.explain_template(facts)["headline"].startswith("UNRECONCILED.")
    assert explain.number_guard(explain.explain_template(facts), facts) == []


# ---- Step 9 ----

def test_drill_tags_and_order():
    b = bdf([("A", "A", "A", "expense", 60000)])
    a = adf([("G", "2026-01-02", 80000, "A", "Gala"), ("R1", "2026-01-03", 5000, "A", "Rent"),
             ("R2", "2026-01-04", 5000, "A", "rent"), ("R3", "2026-01-05", 5000, "A", "Rent")])
    d = drill(compute(b, a, {}, P, dt.date(2026, 1, 10)), "A")
    assert [t["txn_id"] for t in d["top_transactions"]] == ["G", "R1", "R2", "R3"]
    assert [t["tag"] for t in d["top_transactions"]] == ["one_time_spike", "recurring", "recurring", "recurring"]
    assert d["tags"] == ["one_time_spike", "recurring"]


def test_timing_shift_tag_when_pace_off_but_budget_fine():
    b = bdf([("A", "A", "A", "expense", 60000)])
    a = adf([("1", "2026-01-02", 25000, "A", "x"), ("2", "2026-01-03", 25000, "A", "y")])
    r = compute(b, a, {}, P, dt.date(2026, 1, 5))        # expected 30000, actual 50000: pace +20000, budget -10000
    assert line(r, "A").pace_flagged and not line(r, "A").flagged
    assert "timing_shift" in drill(r, "A")["tags"]
