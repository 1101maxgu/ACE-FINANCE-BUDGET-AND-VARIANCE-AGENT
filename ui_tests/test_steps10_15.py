import pytest

from helpers import btn, make_app
from variance import emailing, gmail, reimburse as R, scheduled
from variance.gmail import InMemoryGmailClient


def _fake(**kw):
    return InMemoryGmailClient(messages={"ACE-Q": [], "Exports": [], "Claims": [], **kw}, account="ace@example.org")


def test_email_screen_connect_labels_drafts(tmp_path, monkeypatch):
    at = make_app(tmp_path, monkeypatch, page="Email")
    assert not at.exception, at.exception          # not connected: help is shown, no crash
    assert any("Not connected" in e.value for e in at.error)
    client = _fake()
    at.session_state.gmail_client = client
    at.run()
    assert not at.exception, at.exception
    assert any("Connected as ace@example.org" in s.value for s in at.success)
    # choose labels + roles, save
    at.multiselect[0].set_value(["ACE-Q", "Exports"]).run()
    btn(at, "Save Gmail settings").click().run()
    assert at.session_state.settings["gmail"]["labels"] == ["ACE-Q", "Exports"]
    # tracked questions from a template explanation -> preview -> draft (never sent)
    from variance import explain, facts as F
    ss = at.session_state
    ss.explanation = explain.explain_template(F.build_facts(ss.result, ss.settings))
    at.session_state.settings["runner_email"] = "boss@example.org"
    at.run()
    btn(at, "Create tracked questions from this explanation").click().run()
    assert emailing.list_questions(at.session_state.settings, "open")
    btn(at, "Create Gmail drafts for these questions").click().run()
    assert not at.exception, at.exception
    assert client.drafts and client.drafts[0]["subject"].startswith("[ACE-Q-") and not client.sent
    # reply inbox: reply is fetched, then saved as a note only on a click
    q = emailing.list_questions(at.session_state.settings)[0]
    client.messages["ACE-Q"].append({"id": "m1", "subject": f"Re: [{q['qid']}] x", "from": "sam@example.org",
                                     "date": "2026-03-20", "body_text": "Hall upgrade."})
    at.session_state.settings["gmail"]["question_label"] = "ACE-Q"
    at.run()
    btn(at, "Check for replies").click().run()
    assert not at.exception, at.exception
    assert not [n for n in __import__("variance.notes", fromlist=["x"]).load_notes(at.session_state.settings)]
    btn(at, "Save as note").click().run()
    assert emailing.list_questions(at.session_state.settings)[0]["status"] == "answered"


def test_import_from_email(tmp_path, monkeypatch):
    at = make_app(tmp_path, monkeypatch, page="Email")
    client = _fake(Exports=[{"id": "e1", "subject": "March export", "from": "a@b.c", "date": "d", "body_text": "",
                             "attachments": [{"filename": "x.csv", "mime": "text/csv", "data": b"a,b\n1,2\n"}]}])
    at.session_state.gmail_client = client
    at.session_state.settings["gmail"]["labels"] = ["Exports"]
    at.session_state.settings["gmail"]["export_label"] = "Exports"
    at.run()
    assert not at.exception, at.exception
    btn(at, "Use x.csv as actuals").click().run()
    assert at.session_state.files["actuals"].name == "x.csv"


def test_reimbursements_board_requires_a_person(tmp_path, monkeypatch):
    at = make_app(tmp_path, monkeypatch, page="Reimbursements")
    assert not at.exception, at.exception
    s = at.session_state.settings
    R.upsert_claim(s, {"claim_id": "c1", "claimant": "Kim", "email": "kim@example.org", "amount_cents": 4000,
                       "date": "2026-03-04", "description": "", "line_id": "L001", "confidence": 1.0,
                       "confirmed": False, "source": "form"})
    at.session_state.receipts = {"r1": {"receipt_id": "r1", "claim_id": "c1", "amount_cents": 4000, "date": "2026-03-04",
                                        "vendor": "Shop", "confidence": 0.4, "confirmed": False, "source": "ocr",
                                        "sha256": "x", "file": "r1.png"}}
    at.session_state.receipt_blobs = {}
    at.run()
    assert not at.exception, at.exception
    # low-confidence receipt: not counted until confirmed
    claims = list(R.load_claims(s).values())
    assert R.reconcile(claims, list(at.session_state.receipts.values()))["claims"][0]["needs_confirmation"] == ["r1"]
    at.number_input(key="amt_r1").set_value(40.0).run()
    btn(at, "Confirm these values").click().run()
    assert at.session_state.receipts["r1"]["confirmed"] is True
    # move to ready, then approval is a person's click (needs the name from the sidebar)
    btn(at, "Ready").click().run()
    assert R.load_claims(s)["c1"]["state"] == "ready_to_approve"
    at.session_state.author = ""
    at.run()
    assert at.button(key="mv_c1_approved").disabled
    at.session_state.author = "Pat"
    at.run()
    at.button(key="mv_c1_approved").click().run()
    assert R.load_claims(s)["c1"]["state"] == "approved"
    assert R.load_claims(s)["c1"]["history"][-1]["by"] == "Pat"
    assert R.committed_by_line(s) == {"L001": 4000}


def test_schedule_screen_and_alerts(tmp_path, monkeypatch):
    monkeypatch.setattr(scheduled, "ALERTS_PATH", tmp_path / "alerts.md")
    at = make_app(tmp_path, monkeypatch, page="Schedule")
    assert not at.exception, at.exception
    scheduled._write_alert(tmp_path / "alerts.md", __import__("datetime").datetime(2026, 3, 31, 8, 0),
                           {"job": "j1", "ok": False, "alerts": ["[error] boom"]})
    at.run()
    assert not at.exception, at.exception
    assert any("j1" in e.value for e in at.error)
    for k, v in {"job_bf": "C:/x/b.csv", "job_af": "C:/x/a.csv"}.items():
        at.text_input(key=k).set_value(v)
    at.run()
    btn(at, "Save job file").click().run()
    assert list((tmp_path / "user_data" / "jobs").glob("*.yaml"))
    assert any("schtasks" in c.value for c in at.code)
