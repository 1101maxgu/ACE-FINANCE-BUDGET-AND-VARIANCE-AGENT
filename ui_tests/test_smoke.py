"""Headless smoke test of the Streamlit app (no browser). Run: python -m pytest ui_tests"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from streamlit.testing.v1 import AppTest  # noqa: E402

from ui.common import Mem  # noqa: E402

BUDGET = b"Line,Category,Budget\nVenue,Venue,1000.00\nFood,Food,500.00\nSpeakers,Speakers,0\n"
ACTUALS = (b"Date,Amount,Category,Description\n2026-03-02,1400.00,Venue,Hall\n2026-03-05,200.00,Food,Pizza\n"
           b"2026-03-09,300.00,Speakers,Fee\n2026-03-10,50.00,Mystery,Misc\n")


def _btn(at, label):
    return next(b for b in at.button if b.label == label)


def test_all_screens_and_pipeline(tmp_path, monkeypatch):
    monkeypatch.setattr("variance.mapping.DEFAULT_PATH", tmp_path / "mappings.yaml")
    monkeypatch.setattr("variance.settings.DEFAULT_PATH", tmp_path / "settings.yaml")
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60)
    at.run()
    assert not at.exception
    # empty states of every screen
    for page in ["1. Upload", "2. Map", "3. Check", "4. Report", "Settings"]:
        at.session_state.page = page
        at.run()
        assert not at.exception, (page, at.exception)

    # preload files (the uploader widget cannot be driven headlessly)
    at.session_state.files = {"budget": Mem("b.csv", BUDGET), "actuals": Mem("a.csv", ACTUALS)}
    at.session_state.cfg = {"budget": {"sheet": "(csv)", "header_row": 0},
                            "actuals": {"sheet": "(csv)", "header_row": 0}}
    at.session_state.profile = None
    at.session_state.page = "2. Map"
    at.run()
    assert not at.exception, at.exception
    _btn(at, "Save mapping and read the files").click().run()
    assert not at.exception, at.exception
    assert at.session_state.budget_df is not None, [e.value for e in at.error]
    _btn(at, "Confirm categories").click().run()
    assert at.session_state.cat_map is not None

    at.session_state.settings["period"] = {"label": "March", "start": "2026-03-01", "end": "2026-03-31"}
    at.session_state.settings["reports_dir"] = str(tmp_path / "reports")
    at.session_state.page = "3. Check"
    at.run()
    _btn(at, "Calculate variances").click().run()
    assert not at.exception, at.exception
    assert at.session_state.result is not None
    assert at.session_state.result.totals["flagged_count"] >= 1

    at.session_state.page = "4. Report"
    at.run()
    assert not at.exception, at.exception

    # explanation: paste mode shows the prompt; a template-shaped reply passes the number guard
    from variance import explain, facts as F
    facts = F.build_facts(at.session_state.result, at.session_state.settings, False)
    import json
    at.session_state.reply = json.dumps(explain.explain_template(facts))
    at.session_state.page = "3. Check"
    at.run()
    _btn(at, "Check and use this reply").click().run()
    assert not at.exception, at.exception
    assert at.session_state.explanation, [e.value for e in at.error]
    bad = dict(explain.explain_template(facts), headline="We overspent by $99,999.99")
    at.session_state.reply = json.dumps(bad)
    _btn(at, "Check and use this reply").click().run()
    assert at.session_state.explanation is None and at.error

    at.session_state.page = "4. Report"
    at.run()
    _btn(at, "Generate PDF and Excel").click().run()
    assert not at.exception and not at.error, [e.value for e in at.error]
    assert {p.suffix for p in (tmp_path / "reports").iterdir()} == {".pdf", ".xlsx"}
