"""Step 15: Task Scheduler setup helper and alert history. The app never registers a task itself."""
import re

import streamlit as st
import yaml

from variance import mapping, scheduled
from variance import settings as S


def _jobs_dir():
    return S.ROOT / "user_data" / "jobs"


def _setup():
    ss = st.session_state
    st.write("Run a report automatically each month, with no one at the keyboard. This screen writes a small job "
             "file and shows the one command that schedules it. Nothing is scheduled until you run that command yourself.")
    profiles = list(mapping.load_profiles())
    if not profiles:
        st.info("Save a mapping on the Map screen first. A job uses a saved mapping.")
        return
    p = ss.settings["period"] if ss.settings["period"].get("start") else ss.settings["last_period"]
    c1, c2 = st.columns(2)
    name = c1.text_input("Job name", value=ss.profile or profiles[0], key="job_name")
    prof = c2.selectbox("Saved mapping", profiles, index=profiles.index(ss.profile) if ss.profile in profiles else 0)
    st.caption("The files are read from where they are on this computer each run. They are never changed.")
    bf = st.text_input("Full path of the budget file", key="job_bf")
    af = st.text_input("Full path of the actuals file", key="job_af")
    st.markdown("**Period** (the same dates every run unless you edit the job file)")
    c3, c4, c5 = st.columns(3)
    lab = c3.text_input("Period name", value=p.get("label", ""), key="job_lab")
    ps = c4.text_input("Start (YYYY-MM-DD)", value=p.get("start", ""), key="job_ps")
    pe = c5.text_input("End (YYYY-MM-DD)", value=p.get("end", ""), key="job_pe")
    c6, c7, c8 = st.columns(3)
    backend = c6.selectbox("Explanation", ["template", "api"], help="Paste needs a person, so it is not available here. "
                           "API falls back to template when no key is set.")
    redact = c7.checkbox("Redact descriptions")
    draft = c8.checkbox("Also create a Gmail draft", help="A draft only; you send it.")
    c9, c10 = st.columns(2)
    when = c9.text_input("Time (HH:MM)", value="08:00")
    day = c10.number_input("Day of the month", 1, 28, 1)
    ready = all(x.strip() for x in (name, bf, af, lab, ps, pe))
    job = {"name": name.strip(), "profile": prof, "budget_file": bf.strip(), "actuals_file": af.strip(),
           "period": {"label": lab, "start": ps, "end": pe}, "backend": backend, "redact": redact,
           "email_draft": draft}
    path = _jobs_dir() / (re.sub(r"[^\w.-]+", "_", name.strip()) + ".yaml")
    if st.button("Save job file", disabled=not ready):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(job, sort_keys=False), encoding="utf-8")
        st.success(f"Saved {path}")
    if ready:
        st.write("To schedule it, open a Command Prompt and run this (copy with the icon):")
        st.code(scheduled.schtasks_command(path, name.strip(), when, int(day)), language="batch")
        if st.button("Test run now", help="Runs the job once, right now, exactly as the scheduler would."):
            res = scheduled.run_job(job)
            (st.success if res["ok"] else st.error)("OK" if res["ok"] else "The test run failed.")
            for a in res["alerts"]:
                st.write("- " + a)
            for f in res["files"]:
                st.caption(f"Created {f}")


def _history():
    rows = scheduled.read_alerts()
    if not rows:
        st.info("No automatic runs yet. Alerts from scheduled runs will be listed here.")
    for r in rows:
        (st.success if r["status"] == "OK" else st.error)(f"{r['when']} - {r['job']} - {r['status']}")
        for i in r["items"]:
            st.write("- " + i)


def render():
    st.title("Schedule and alerts")
    t1, t2 = st.tabs(["Set up a monthly run", "Alert history"])
    with t1:
        _setup()
    with t2:
        _history()
