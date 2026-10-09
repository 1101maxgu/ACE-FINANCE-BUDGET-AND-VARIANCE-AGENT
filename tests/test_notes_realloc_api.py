"""Steps 4 (API slot), 12 and 13."""
import datetime as dt
import json
from types import SimpleNamespace

import pytest

from test_timing_quality_drill import adf, bdf, line
from variance import explain, facts as F, notes, realloc
from variance.calc import compute

S = {"flag_min_cents": 15000, "flag_pct": 10.0}


def one_line_result():
    b = bdf([("A", "A", "Venue", "expense", 10000)])
    a = adf([("t1", "2026-01-02", 40000, "A", "x"), ("t2", "2026-01-03", 1000, "A", "y")])
    return compute(b, a, {}, {**S, "period": {"label": "Jan", "start": "", "end": ""}}, dt.date(2026, 1, 31))


# ---- Step 12 ----

def test_notes_one_file_per_author_and_filters(tmp_path):
    st = {"shared_folder": str(tmp_path)}
    n1 = notes.add_note(st, "Ann Lee", "P1", "A", "Jan", ["t1"], " Deposit paid early ", date="2026-02-01")
    notes.add_note(st, "Bob", "P1", "B", "Jan", [], "x", date="2026-02-02")
    notes.add_note(st, "Bob", "P2", "A", "Feb", [], "y", date="2026-02-03")
    assert sorted(p.name for p in (tmp_path / "notes").iterdir()) == ["Ann_Lee.json", "Bob.json"]
    assert n1["text"] == "Deposit paid early" and n1["note_id"] == "Ann_Lee-1"
    assert len(notes.load_notes(st)) == 3 and len(notes.load_notes(st, profile="P1")) == 2
    assert [n["author"] for n in notes.load_notes(st, "P1", "Jan")] == ["Ann Lee", "Bob"]
    assert notes.delete_note(st, "Bob", "Bob-1") and len(notes.load_notes(st)) == 2
    with pytest.raises(ValueError):
        notes.add_note(st, "  ", "P1", "A", "Jan", [], "x")


def test_note_goes_into_facts_and_goes_stale_with_new_transactions(tmp_path):
    st = {"shared_folder": str(tmp_path)}
    r = one_line_result()
    note = notes.add_note(st, "Ann", "P", "A", "Jan", ["t1", "t2"], "Deposit paid early", date="2026-02-01")
    facts = F.build_facts(r, S, notes=[note])
    cn = facts["flagged_lines"][0]["coordinator_notes"]
    assert cn == [{"author": "Ann", "date": "2026-02-01", "text": "Deposit paid early", "state": "current"}]
    issue = explain.explain_template(facts)["top_issues"][0]
    assert issue["cause"]["label"] == "answered" and issue["question"] == ""
    # a new transaction arrives on the line -> note is stale -> asked again
    old = notes.add_note(st, "Ann", "P", "A", "Jan", ["t1"], "Deposit", date="2026-02-01")
    facts = F.build_facts(r, S, notes=[old])
    assert facts["flagged_lines"][0]["coordinator_notes"][0]["state"] == "stale"
    issue = explain.explain_template(facts)["top_issues"][0]
    assert issue["cause"]["label"] == "unknown" and "Does it still hold" in issue["question"]
    # a note for another period does not apply
    other = {**note, "period": "Feb"}
    assert F.build_facts(r, S, notes=[other])["flagged_lines"][0]["coordinator_notes"] == []
    assert explain.number_guard(explain.explain_template(facts), facts) == []


# ---- Step 13 ----

def realloc_result():
    b = bdf([("A", "A", "Surplus", "expense", 100000), ("B", "B", "Over1", "expense", 50000),
             ("C", "C", "Over2", "expense", 10000), ("D", "D", "Tiny", "expense", 10000)])
    a = adf([("1", "2026-01-02", 20000, "A", ""), ("2", "2026-01-02", 90000, "B", ""),
             ("3", "2026-01-02", 60000, "C", ""), ("4", "2026-01-02", 9000, "D", "")])
    return compute(b, a, {}, S, dt.date(2026, 1, 31))


def test_reallocation_pairs_largest_first_and_is_advice_only():
    r = realloc_result()
    before = r.lines.copy()
    sug = realloc.suggest(r, S)
    # A has 80000 free, C needs 50000, B needs 40000. D's 1000 free is under the $150 floor.
    assert [(s["from_line_id"], s["to_line_id"], s["amount_cents"]) for s in sug] == [("A", "C", 50000), ("A", "B", 30000)]
    assert all(s["status"] == "for approval" for s in sug) and sug[0]["suggestion_id"] == "A->C"
    assert r.lines.equals(before)                       # nothing applied
    facts = F.build_facts(r, S)
    assert facts["reallocation_candidates"] == sug
    t = explain.explain_template(facts)
    assert "$500.00 from Surplus to Over2" in t["reallocation_suggestions"][0]
    assert explain.number_guard(t, facts) == []


def test_decisions_are_only_recorded(tmp_path):
    st = {"shared_folder": str(tmp_path)}
    sug = realloc.suggest(realloc_result(), S)
    realloc.record_decision(st, "Ann", "A->C", "dismissed", "2026-02-01")
    realloc.record_decision(st, "Bob", "A->B", "snoozed", "2026-02-01", snooze_until="2026-02-10")
    d = realloc.load_decisions(st)
    vis = {s["suggestion_id"]: s["visible"] for s in realloc.with_decisions(sug, d, "2026-02-05")}
    assert vis == {"A->C": False, "A->B": False}
    vis = {s["suggestion_id"]: s["visible"] for s in realloc.with_decisions(sug, d, "2026-02-10")}
    assert vis == {"A->C": False, "A->B": True}
    with pytest.raises(ValueError):
        realloc.record_decision(st, "Ann", "A->C", "applied", "2026-02-01")


# ---- Step 4 API slot ----

def test_api_not_configured_without_key(monkeypatch, tmp_path):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(explain, "ROOT", tmp_path)       # no .env here
    with pytest.raises(explain.NotConfigured):
        explain.explain_api(F.build_facts(one_line_result(), S))


def test_api_with_fake_client_enforces_guard():
    facts = F.build_facts(one_line_result(), S)
    good = json.dumps(explain.explain_template(facts))

    def client(text):
        create = lambda **kw: SimpleNamespace(content=[SimpleNamespace(text=text)])
        return SimpleNamespace(messages=SimpleNamespace(create=create))

    assert explain.explain_api(facts, client=client(good))["status"] == "off_track"
    bad = json.loads(good)
    bad["headline"] = "We overspent by $99,999.00"
    with pytest.raises(explain.ExplainError, match="99,999.00"):
        explain.explain_api(facts, client=client(json.dumps(bad)))
