import json

from helpers import btn, make_app


def test_check_timing_quality_drilldown(tmp_path, monkeypatch):
    at = make_app(tmp_path, monkeypatch)
    r = at.session_state.result
    assert r.totals["flagged_count"] >= 1
    assert "chip" in r.lines.columns
    assert any(f["code"] == "possible_duplicate" for f in r.quality)  # shown in the Data quality tab
    # timing controls
    btn(at, "Apply and recalculate").click().run()
    assert not at.exception, at.exception
    # fix actions: stated total (critical -> unreconciled banner) then mark duplicates intentional
    at.number_input(key="fx_total").set_value(1.0)
    btn(at, "Check this total").click().run()
    assert not at.exception, at.exception
    assert at.session_state.stated == 100
    assert any("UNRECONCILED" in e.value for e in at.error)
    at.session_state.stated = None
    at.session_state.page = "3. Check"
    at.run()
    at.checkbox(key="dup_0").set_value(True)
    btn(at, "Mark ticked as intentional").click().run()
    assert at.session_state.dupes
    assert not any(f["code"] == "possible_duplicate" for f in at.session_state.result.quality)
    # map the unmapped category
    at.selectbox(key="fx_tgt").set_value("L001").run()
    btn(at, "Apply mapping").click().run()
    assert not at.exception, at.exception


def test_notes_and_suggestions(tmp_path, monkeypatch):
    at = make_app(tmp_path, monkeypatch, page="Needs your answer")
    assert not at.exception, at.exception
    key = next(t.key for t in at.text_area if t.key.startswith("ans_"))
    at.text_area(key=key).set_value("Booked a bigger hall").run()
    at.button(key="save_" + key[4:]).click().run()
    assert not at.exception, at.exception
    assert list((tmp_path / "user_data" / "notes").glob("*.json"))
    assert any("Booked" in m.value for m in at.markdown)
    # the note reaches the facts
    at.session_state.page = "Suggestions"
    at.run()
    assert not at.exception, at.exception
    dismiss = [b for b in at.button if b.label == "Dismiss"]
    assert dismiss
    if dismiss:
        dismiss[0].click().run()
        assert list((tmp_path / "user_data" / "decisions").glob("*.json"))
        data = json.loads(next((tmp_path / "user_data" / "decisions").glob("*.json")).read_text())
        assert data[0]["decision"] == "dismissed"
