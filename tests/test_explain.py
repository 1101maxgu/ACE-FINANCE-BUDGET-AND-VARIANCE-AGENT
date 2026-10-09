import datetime as dt
import json

import pytest

from test_calc import AS_OF, SETTINGS, actuals, budget
from variance import explain, facts as F
from variance.calc import compute


@pytest.fixture(scope="module")
def facts():
    r = compute(budget(), actuals().assign(description="secret lunch", vendor="Acme"), {}, SETTINGS, AS_OF)
    return F.build_facts(r, {**SETTINGS, "period": {}}, redact=False)


def test_facts_content(facts):
    assert facts["totals"]["flagged_count"] == 4 and len(facts["flagged_lines"]) == 4
    first = facts["flagged_lines"][0]               # biggest |variance| first: Venue/Tickets 50000 tie -> stable
    assert abs(first["variance_cents"]) == 50000
    food = [x for x in facts["flagged_lines"] if x["line_id"] == "L1"][0]
    assert food["variance_pct"] == 37.5
    assert [t["amount_cents"] for t in food["top_transactions"]] == [70000, 50000, -10000]
    assert food["top_transactions"][0]["description"] == "secret lunch"
    parking = [x for x in facts["flagged_lines"] if x["line_id"] == "UNBUDGETED:Parking"][0]
    assert parking["variance_pct"] is None            # NaN never leaks into JSON
    json.loads(F.facts_to_json(facts))


def test_redaction_hides_descriptions():
    r = compute(budget(), actuals().assign(description="secret lunch", vendor="Acme"), {}, SETTINGS, AS_OF)
    txt = F.facts_to_json(F.build_facts(r, SETTINGS, redact=True))
    assert "secret" not in txt and "Acme" not in txt


def test_template_passes_its_own_guard(facts):
    e = explain.explain_template(facts)
    assert e["status"] == "off_track" and len(e["top_issues"]) == 4
    assert all(i["cause"]["label"] == "unknown" and i["question"] for i in e["top_issues"])
    assert explain.number_guard(e, facts) == []
    assert "$300.00 over budget (37.5%)" in " ".join(i["title"] for i in e["top_issues"])


def test_guard_accepts_formats_and_rejects_invented_numbers(facts):
    ok = "Food was $300.00 over, i.e. $300 or 37.5%. Venue is -$500.00 under. 4 lines flagged. Period 2026-03-31."
    assert explain.number_guard(ok, facts) == []
    bad = explain.number_guard("Food is $301.00 over, up 41% and 23 vendors; budget $1,600.", facts)
    assert set(bad) == {"301.00", "41", "23", "1,600"}


def test_guard_checks_every_string_in_dict(facts):
    d = {"headline": "fine", "top_issues": [{"detail": "spent $999.99"}], "decisions_needed": ["ok"]}
    assert explain.number_guard(d, facts) == ["999.99"]


def test_parse_pasted_reply(facts):
    e = explain.explain_template(facts)
    wrapped = "Sure! Here you go:\n```json\n" + json.dumps(e) + "\n```\nHope that helps."
    d, problems = explain.parse_pasted_reply(wrapped, facts)
    assert problems == [] and d["status"] == "off_track"

    e["headline"] = "We overspent by $12,345.67"
    e["top_issues"][0]["cause"]["label"] = "guess"
    d, problems = explain.parse_pasted_reply(json.dumps(e), facts)
    assert d is not None
    assert any("12,345.67" in p for p in problems) and any("Issue 1" in p for p in problems)

    assert explain.parse_pasted_reply("no json here", facts)[0] is None
    assert explain.parse_pasted_reply('{"headline": "x"}', facts)[0] is None


def test_prompt_contains_rules_and_facts(facts):
    p = explain.build_prompt(facts)
    assert "supported" in p and '"flagged_count": 4' in p


def test_api_slot_not_configured(facts):
    with pytest.raises(explain.NotConfigured, match="ANTHROPIC_API_KEY"):
        explain.explain_api(facts)
