import datetime as dt

import pytest

from variance import explain, scheduled as S
from variance.gmail import InMemoryGmailClient
from variance.settings import load_settings

PROFILE = {"budget": {"columns": {"line_name": "Line", "budget": "Amount"}},
           "actuals": {"sign": "positive_expenses", "columns": {"date": "Date", "category": "Cat", "amount": "Amt"}}}
NOW = dt.datetime(2026, 2, 1, 8, 0)


@pytest.fixture
def env(tmp_path):
    (tmp_path / "b.csv").write_text("Line,Amount\nFood,1000\nVenue,500\n")
    (tmp_path / "a.csv").write_text("Date,Cat,Amt\n2026-01-05,Food,1500\n2026-01-06,Venue,100\n")
    st = {**load_settings(tmp_path / "none.yaml"), "shared_folder": str(tmp_path), "reports_dir": str(tmp_path / "out")}
    job = {"name": "Alice monthly", "profile": "Alice", "budget_file": str(tmp_path / "b.csv"),
           "actuals_file": str(tmp_path / "a.csv"), "period": {"label": "Jan 2026", "start": "2026-01-01", "end": "2026-01-31"}}
    return tmp_path, st, job


def test_headless_run_writes_reports_and_alerts(env):
    tmp, st, job = env
    alerts = tmp / "alerts.md"
    res = S.run_job(job, st, {"Alice": PROFILE}, now=NOW, alerts_path=alerts)
    assert res["ok"] and res["backend_used"] == "template"
    assert [f.split("\\")[-1].split("/")[-1] for f in res["files"]] == ["Alice_monthly-Jan_2026.xlsx", "Alice_monthly-Jan_2026.pdf"]
    assert all((tmp / "out" / n).exists() for n in ("Alice_monthly-Jan_2026.xlsx", "Alice_monthly-Jan_2026.pdf"))
    assert res["alerts"][0] == "[high] Food is $500.00 over budget (50.0%)"      # 1500 vs 1000 dollars
    hist = S.read_alerts(alerts)
    assert hist[0] == {"when": "2026-02-01 08:00", "job": "Alice monthly", "status": "OK", "items": res["alerts"]}


def test_failures_become_alerts_not_crashes(env):
    tmp, st, job = env
    res = S.run_job({**job, "profile": "Nobody"}, st, {"Alice": PROFILE}, now=NOW, alerts_path=tmp / "al.md")
    assert not res["ok"] and "was not found" in res["alerts"][0]
    res = S.run_job({**job, "backend": "paste"}, st, {"Alice": PROFILE}, now=NOW, alerts_path=tmp / "al.md")
    assert not res["ok"] and "template' or 'api" in res["alerts"][0]
    res = S.run_job({**job, "period": {"label": "", "start": "", "end": ""}}, st, {"Alice": PROFILE}, now=NOW, alerts_path=tmp / "al.md")
    assert not res["ok"] and "period" in res["alerts"][0]
    assert [a["status"] for a in S.read_alerts(tmp / "al.md")] == ["FAILED"] * 3


def test_api_backend_falls_back_to_template_without_key(env, monkeypatch):
    tmp, st, job = env
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(explain, "ROOT", tmp)
    res = S.run_job({**job, "backend": "api"}, st, {"Alice": PROFILE}, now=NOW, alerts_path=tmp / "al.md")
    assert res["ok"] and res["backend_used"] == "template" and res["alerts"][0].startswith("[info] Claude API not used")


def test_email_draft_is_a_draft_only(env):
    tmp, st, job = env
    c = InMemoryGmailClient()
    res = S.run_job({**job, "email_draft": True}, {**st, "runner_email": "run@x.org"}, {"Alice": PROFILE}, client=c,
                    now=NOW, alerts_path=tmp / "al.md")
    assert res["ok"] and len(c.drafts) == 1 and c.sent == []
    assert [a["filename"] for a in c.drafts[0]["attachments"]] == ["Alice_monthly-Jan_2026.xlsx", "Alice_monthly-Jan_2026.pdf"]
    res = S.run_job({**job, "email_draft": True}, st, {"Alice": PROFILE}, now=NOW, alerts_path=tmp / "al.md")
    assert "No Gmail connection" in " ".join(res["alerts"])


def test_schtasks_command_is_text_only():
    cmd = S.schtasks_command(r"C:\jobs\a.yaml", "Alice", when="07:30", day=2, python="py.exe", script="run_report.py")
    assert cmd.startswith("schtasks /Create /SC MONTHLY /D 2 /ST 07:30") and 'a.yaml' in cmd and '"ACE Variance - Alice"' in cmd
