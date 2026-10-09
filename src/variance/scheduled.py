"""Headless runs for Windows Task Scheduler. This module never registers a task itself.

A job is a small YAML file (or dict):
    name: alice-monthly
    profile: Alice                  # a saved mapping profile
    budget_file: C:\\path\\budget.xlsx
    actuals_file: C:\\path\\actuals.csv
    period: {label: "Oct 2026", start: "2026-10-01", end: "2026-10-31"}   # explicit, never auto-detected
    as_of_date: "2026-10-31"        # optional (default: period end)
    backend: template               # template | api  (paste needs a person)
    redact: false
    email_draft: false              # also create a Gmail DRAFT with the reports attached (never sends)
"""
import argparse
import re
import sys
import traceback
from datetime import datetime
from pathlib import Path

import yaml

from . import emailing, explain, gmail, mapping, notes, pipeline, reimburse, reports
from .settings import ROOT, load_settings

ALERTS_PATH = ROOT / "user_data" / "alerts.md"


def _slug(s):
    return re.sub(r"[^\w.-]+", "_", str(s)).strip("_") or "job"


def run_job(job, settings=None, profiles=None, client=None, now=None, alerts_path=None) -> dict:
    """Run one job headlessly. Never raises: problems become an alert and ok=False.
    Returns {ok, job, files, alerts, backend_used, explanation}. The clock is read here (for the alert
    timestamp) and never inside the calculation."""
    if not isinstance(job, dict):
        job = yaml.safe_load(Path(job).read_text(encoding="utf-8"))
    settings = settings if settings is not None else load_settings()
    name = job.get("name", "job")
    out = {"ok": False, "job": name, "files": [], "alerts": [], "backend_used": "", "explanation": None}
    try:
        profile = (profiles if profiles is not None else mapping.load_profiles()).get(job.get("profile"))
        if profile is None:
            raise ValueError(f"Mapping profile '{job.get('profile')}' was not found. Open the app and save it first.")
        backend = job.get("backend", "template")
        if backend not in ("template", "api"):
            raise ValueError("Unattended runs can only use the 'template' or 'api' explanation backend.")
        st = {**settings, "period": job["period"]}
        label = str(job["period"]["label"])
        run = pipeline.run(job["budget_file"], job["actuals_file"], st, profile, as_of_date=job.get("as_of_date"),
                           redact=bool(job.get("redact")), stated_total_cents=job.get("stated_total_cents"),
                           notes=notes.load_notes(st, job.get("profile"), label),
                           committed=reimburse.committed_by_line(st))
        facts = run["facts"]
        expl, used = None, "template"
        if backend == "api":
            try:
                expl, used = explain.explain_api(facts, st), "api"
            except (explain.NotConfigured, explain.ExplainError) as e:
                out["alerts"].append(f"[info] Claude API not used ({e}); the template explanation was used instead.")
        expl = expl or explain.explain_template(facts)
        folder = Path(settings.get("reports_dir") or "reports")
        if not folder.is_absolute():
            folder = ROOT / folder
        folder.mkdir(parents=True, exist_ok=True)
        stem = f"{_slug(name)}-{_slug(label)}"
        files = [reports.write_excel(run["result"], facts, folder / f"{stem}.xlsx"),
                 reports.write_pdf(expl, facts, folder / f"{stem}.pdf")]
        if facts["unreconciled"]:
            out["alerts"].append("[high] UNRECONCILED: " + "; ".join(
                f["message"] for f in facts["quality_findings"] if f["severity"] == "critical"))
        out["alerts"] += [f"[{'high' if x['status'] == 'unfavorable' else 'info'}] {i['title']}"
                          for x, i in zip(facts["flagged_lines"][:5], expl["top_issues"])]
        out["alerts"] += [f"[watch] {w['line_name']} is at an early-warning level." for w in facts["watch_lines"]
                          if w.get("early_warning")]
        if job.get("email_draft"):
            if client is None:
                out["alerts"].append("[info] No Gmail connection, so no email draft was created.")
            else:
                emailing.draft_report(client, settings, files, f"Variance report: {label}", expl["headline"])
        out.update(ok=True, files=files, backend_used=used, explanation=expl)
    except Exception as e:  # noqa: BLE001 - headless: report, don't crash the scheduler
        out["alerts"].append(f"[error] The scheduled run failed: {e}")
        out["traceback"] = traceback.format_exc()
    _write_alert(alerts_path or ALERTS_PATH, now or datetime.now(), out)
    return out


def _write_alert(path, now, out):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    head = f"## {now:%Y-%m-%d %H:%M} | {out['job']} | {'OK' if out['ok'] else 'FAILED'}\n"
    body = "".join(f"- {a}\n" for a in out["alerts"]) or "- Nothing needs attention.\n"
    with open(path, "a", encoding="utf-8") as f:
        f.write(head + body + "\n")


def read_alerts(path=None) -> list:
    """Alert history, newest first: [{when, job, status, items[]}]."""
    p = Path(path or ALERTS_PATH)
    if not p.exists():
        return []
    out = []
    for block in p.read_text(encoding="utf-8").split("## ")[1:]:
        head, *items = block.strip().splitlines()
        when, job, status = (x.strip() for x in head.split("|"))
        out.append({"when": when, "job": job, "status": status, "items": [i[2:] for i in items if i.startswith("- ")]})
    return out[::-1]


def schtasks_command(job_path, name, when="08:00", day=1, python=None, script=None) -> str:
    """The Task Scheduler command a person can run to schedule a MONTHLY job. NOT executed by this package."""
    py, sc = python or sys.executable, script or ROOT / "run_report.py"
    return (f'schtasks /Create /SC MONTHLY /D {int(day)} /ST {when} /TN "ACE Variance - {name}" '
            f'/TR "\\"{py}\\" \\"{sc}\\" \\"{job_path}\\"" /F')


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Run a Budget & Variance job without the app.")
    ap.add_argument("job", help="path to the job .yaml file")
    args = ap.parse_args(argv)
    res = run_job(args.job)
    print(("OK: " if res["ok"] else "FAILED: ") + "; ".join(res["alerts"] or ["nothing needs attention"]))
    return 0 if res["ok"] else 1
