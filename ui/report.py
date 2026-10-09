"""Screen 4: generate and download the PDF one-pager and Excel detail."""
import os
import re
import shutil
from datetime import datetime
from pathlib import Path

import streamlit as st

from variance import explain, reports
from variance.settings import ROOT
from .common import get_facts, next_button


def _name(r):
    base = r.period.get("label") or f"{r.period.get('start', '')}_{r.period.get('end', '')}"
    return re.sub(r"[^A-Za-z0-9_-]+", "_", base).strip("_") or "report"


def render():
    ss = st.session_state
    s = ss.settings
    st.title("Report")
    if ss.result is None:
        st.info("Calculate results on the Check screen first.")
        next_button("Go to Check", "3. Check")
        return
    r = ss.result
    facts = get_facts()
    if facts.get("unreconciled"):
        st.error("UNRECONCILED: reports will carry an unreconciled banner until the stated total matches.")
    expl = ss.explanation
    if not expl:
        expl = explain.explain_template(facts)
        st.info("No explanation chosen yet, so the built-in Template wording will be used.")
    st.write("**Preview**")
    st.markdown(f"> {expl.get('headline', '')}")
    st.caption(f"{len(expl.get('top_issues', []))} issue(s), {len(expl.get('decisions_needed', []))} decision(s) "
               "needed. Reports are marked generated, not audited.")
    if st.button("Generate PDF and Excel", type="primary"):
        out = ROOT / s.get("reports_dir", "reports")
        out.mkdir(parents=True, exist_ok=True)
        stem = f"{_name(r)}_{datetime.now():%Y%m%d_%H%M%S}"
        xl, pdf = out / f"{stem}.xlsx", out / f"{stem}.pdf"
        try:
            reports.write_excel(r, facts, xl)
            reports.write_pdf(expl, facts, pdf)
        except Exception as e:
            st.error(f"Could not create the reports: {e}")
            return
        ss.report_files = {"xlsx": xl, "pdf": pdf}
    files = ss.get("report_files")
    if not files:
        return
    c1, c2 = st.columns(2)
    c1.download_button("Download PDF one-pager", Path(files["pdf"]).read_bytes(), files["pdf"].name,
                       "application/pdf")
    c2.download_button("Download Excel detail", Path(files["xlsx"]).read_bytes(), files["xlsx"].name,
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    st.caption(f"Copies kept in: {files['pdf'].parent}")
    shared = s.get("shared_folder", "")
    if st.button("Save to shared folder", disabled=not shared,
                 help=shared or "Set the shared folder on the Settings screen."):
        try:
            os.makedirs(shared, exist_ok=True)
            for f in files.values():
                shutil.copy2(f, shared)
            st.success(f"Saved to {shared}")
        except OSError as e:
            st.error(f"Could not save to the shared folder: {e}")
