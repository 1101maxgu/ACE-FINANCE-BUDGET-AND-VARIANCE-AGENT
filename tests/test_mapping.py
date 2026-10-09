import pandas as pd

from variance import mapping, settings


def df(*cols, rows=()):
    return pd.DataFrame(list(rows), columns=list(cols), dtype=object)


def test_guess_budget_total_layout():
    m = mapping.guess_mapping(df("Line Item", "Department", "Approved Budget", "Owner"), "budget")
    assert m["layout"] == "total" and m["kind"] == "budget"
    assert m["columns"] == {"line_id": None, "line_name": "Line Item", "category": "Department",
                            "type": None, "budget": "Approved Budget", "owner": "Owner"}


def test_guess_budget_monthly_wide():
    m = mapping.guess_mapping(df("Item", "Jan", "Feb 2026", "March", "Notes"), "budget")
    assert m["layout"] == "monthly_wide" and m["month_columns"] == ["Jan", "Feb 2026", "March"]


def test_guess_actuals_sign_from_data():
    neg = df("Date", "Category", "Amount", rows=[("2026-01-01", "x", "-5.00"), ("2026-01-02", "x", "-7"), ("2026-01-03", "x", "2")])
    assert mapping.guess_mapping(neg, "actuals")["sign"] == "negative_expenses"
    pos = df("Date", "Category", "Amount", rows=[("2026-01-01", "x", "5.00")])
    assert mapping.guess_mapping(pos, "actuals")["sign"] == "positive_expenses"
    dc = mapping.guess_mapping(df("Transaction Date", "Category", "Debit", "Credit", "Payee"), "actuals")
    assert dc["sign"] == "debit_credit" and dc["columns"]["vendor"] == "Payee"


def test_profiles_roundtrip_and_fingerprint(tmp_path):
    path = tmp_path / "mappings.yaml"
    assert mapping.load_profiles(path) == {}
    b = df("Line Item", "Department", "Approved Budget")
    mapping.save_profile("Alice", mapping.guess_mapping(b, "budget"), path)
    mapping.save_profile("Alice", mapping.guess_mapping(df("Date", "Category", "Amount"), "actuals"), path)
    mapping.save_profile("Bob", mapping.guess_mapping(df("Name", "Total"), "budget"), path)
    prof = mapping.load_profiles(path)
    assert set(prof["Alice"]) == {"budget", "actuals"}
    assert mapping.find_profile_by_fingerprint(b, path) == "Alice"
    assert mapping.find_profile_by_fingerprint(df("name", " TOTAL "), path) == "Bob"
    assert mapping.find_profile_by_fingerprint(df("Zed", "Qux"), path) is None


def test_category_suggestions_and_saved_map(tmp_path):
    budget = pd.DataFrame({"line_id": ["L1", "L2", "L3"], "category": ["Food", "Venue", "Venue"],
                           "line_name": ["Catering", "Hall", "Hall"]})
    acts = pd.DataFrame({"category": ["catering", "Catring", "Hall", "Zebra", "Old"], "amount_cents": [100, 200, 300, 400, 500]})
    rows = {r["actual_category"]: r for r in mapping.suggest_categories(acts, budget, {"Old": "L1"})}
    assert (rows["catering"]["status"], rows["catering"]["suggestion"]) == ("exact", "L1")
    assert (rows["Catring"]["status"], rows["Catring"]["suggestion"]) == ("suggested", "L1")
    assert rows["Hall"]["status"] == "ambiguous"
    assert (rows["Zebra"]["status"], rows["Zebra"]["suggestion"]) == ("unmatched", "")
    assert rows["Old"]["status"] == "saved" and rows["Old"]["total_cents"] == 500
    path = tmp_path / "m.yaml"
    mapping.save_category_map("Alice", {"Zebra": "L2"}, path)
    assert mapping.load_profiles(path)["Alice"]["category_map"] == {"Zebra": "L2"}


def test_settings_roundtrip(tmp_path):
    p = tmp_path / "s.yaml"
    s = settings.load_settings(p)
    assert s["flag_min_cents"] == 15000 and s["flag_pct"] == 10.0
    s["flag_pct"] = 5
    s["period"]["label"] = "Q1"
    settings.save_settings(s, p)
    s2 = settings.load_settings(p)
    assert s2["flag_pct"] == 5 and s2["period"] == {"label": "Q1", "start": "", "end": ""}
