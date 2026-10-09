"""Screen 3: results (tiles, table, chart) and explanation (template / paste / API)."""
from datetime import date

import pandas as pd
import streamlit as st

from variance import calc, explain, facts as F
from variance.settings import save_settings
from .common import invalidate, next_button, usd

COLORS = {"unfavorable": "#f8d7da", "favorable": "#d4edda", "on_budget": "#e9ecef"}
STATUS_TEXT = {"unfavorable": "Unfavorable", "favorable": "Favorable", "on_budget": "On budget"}
MODES = ["Template", "Paste", "API"]


def _d(s):
    try:
        return date.fromisoformat(str(s))
    except ValueError:
        return None


def _run():
    ss = st.session_state
    s = ss.settings
    per = s["period"]
    if not (_d(per.get("start")) and _d(per.get("end"))):
        st.warning("Set the period start and end first.")
        next_button("Go to Settings", "Settings")
        return False
    st.write(f"Period: **{per.get('label') or ''}** {per['start']} to {per['end']}")
    asof = st.date_input("Report as of", value=min(date.today(), _d(per["end"])), format="YYYY-MM-DD",
                         help="Spending after this date is left out.")
    if st.button("Calculate variances", type="primary"):
        try:
            ss.result = calc.compute(ss.budget_df, ss.actuals_df, ss.cat_map, s, asof)
        except ValueError as e:
            st.error(str(e))
            return False
        s["last_period"] = dict(per)
        save_settings(s)
        invalidate("explanation")
    return True


def _table(r):
    L = r.lines
    c1, c2, c3 = st.columns([2, 2, 3])
    sel = c1.multiselect("Status", list(STATUS_TEXT), default=list(STATUS_TEXT), format_func=STATUS_TEXT.get)
    only = c2.checkbox("Flagged only")
    q = c3.text_input("Search line or category")
    v = L[L.status.isin(sel)]
    if only:
        v = v[v.flagged]
    if q:
        v = v[(v.line_name + " " + v.category).str.contains(q, case=False, regex=False)]
    show = pd.DataFrame({
        "Line": v.line_name, "Category": v.category, "Type": v.type, "Budget": v.budget_cents / 100,
        "Actual": v.actual_cents / 100, "Variance": v.variance_cents / 100, "Variance %": v.variance_pct,
        "Status": v.status.map(STATUS_TEXT), "Flagged": v.flagged.map({True: "FLAG", False: ""}),
        "Owner": v.owner}).reset_index(drop=True)
    colors = v.status.map(COLORS).tolist()
    sty = show.style.apply(lambda row: [f"background-color: {colors[row.name]}; color: #222"] * len(row), axis=1)
    sty = sty.format({"Budget": "${:,.2f}", "Actual": "${:,.2f}", "Variance": "${:,.2f}", "Variance %": "{:.2f}%"},
                     na_rep="n/a")
    st.dataframe(sty, width="stretch", hide_index=True)
    st.markdown(" ".join(f"<span style='background:{COLORS[k]};padding:2px 8px;border-radius:4px;color:#222'>"
                         f"{STATUS_TEXT[k]}</span>" for k in COLORS) +
                "  Variance = actual minus budget. Revenue under target counts as unfavorable. "
                "n/a % = no budget was set.", unsafe_allow_html=True)


def _results(r):
    t = r.totals
    c = st.columns(4)
    c[0].metric("Expense budget", usd(t["expense_budget_cents"]))
    c[1].metric("Expense actual", usd(t["expense_actual_cents"]))
    c[2].metric("Net variance", usd(t["net_variance_cents"]), help="Positive = better than budget overall.")
    c[3].metric("Flagged lines", t["flagged_count"], help=f"of {t['line_count']} lines")
    if t["excluded_row_count"]:
        st.info(f"{t['excluded_row_count']} transaction(s) ({usd(t['excluded_cents'])}) "
                "are outside the period and left out.")
    if t["unbudgeted_cents"]:
        st.warning(f"{usd(t['unbudgeted_cents'])} was spent in categories with no budget line "
                   "(shown as UNBUDGETED).")
    _table(r)
    g = r.lines.groupby("category", sort=False)[["budget_cents", "actual_cents"]].sum() / 100
    st.subheader("Budget vs actual by category")
    st.bar_chart(g.rename(columns={"budget_cents": "Budget", "actual_cents": "Actual"}))


def _render_explanation(e):
    color = {"on_track": "green", "watch": "orange", "off_track": "red"}.get(e.get("status"), "gray")
    st.subheader(e.get("headline", ""))
    st.markdown(f":{color}[**{str(e.get('status', '')).replace('_', ' ').upper()}**]")
    for it in e.get("top_issues", []):
        cause = it.get("cause") or {}
        with st.container(border=True):
            st.markdown(f"**{it.get('title', '')}**")
            st.write(it.get("detail", ""))
            lab = cause.get("label", "unknown")
            st.markdown(f":{'orange' if lab == 'unknown' else 'blue'}[{lab.upper()}] {cause.get('text', '')}")
            if it.get("question"):
                st.markdown(f"Question: *{it['question']}*")
    if e.get("decisions_needed"):
        st.markdown("**Decisions needed**")
        for d in e["decisions_needed"]:
            st.markdown(f"- {d}")
    if e.get("reallocation_suggestions"):
        st.markdown("**Reallocation suggestions (for approval, nothing is applied)**")
        for x in e["reallocation_suggestions"]:
            st.markdown(f"- {x}")


def _explain(r):
    ss = st.session_state
    s = ss.settings
    mode = st.radio("How should the explanation be written?", MODES, horizontal=True,
                    index=[m.lower() for m in MODES].index(s.get("explain_mode", "paste")),
                    help="Template: simple built-in wording. Paste: you copy the text into Claude and paste "
                         "the reply back. API: automatic, needs a key.")
    redact = st.checkbox("Redact descriptions and vendors", value=bool(s.get("redact")),
                         help="Leaves transaction descriptions and vendor names out of what is sent.")
    ss.redact = redact
    facts = F.build_facts(r, s, redact)
    if mode == "Template":
        ss.explanation = explain.explain_template(facts)
    elif mode == "Paste":
        with st.expander("Exactly what will be sent (copy it with the icon at the top right)", expanded=True):
            st.code(explain.build_prompt(facts), language="markdown", wrap_lines=True)
        st.caption("Paste this into Claude, then paste Claude's whole answer below.")
        reply = st.text_area("Claude's reply", height=200, key="reply")
        if st.button("Check and use this reply", disabled=not reply.strip()):
            d, problems = explain.parse_pasted_reply(reply, facts)
            for p in problems:
                st.error(p)
            if d is None or problems:
                if d is not None:
                    st.warning("Reply not used. Ask Claude to fix the items above, or use Template mode.")
                ss.explanation = None
            else:
                ss.explanation = d
                st.success("Reply accepted. Every number matches the computed facts.")
    elif st.button("Ask Claude through the API"):
        try:
            d = explain.explain_api(facts)
            bad = explain.number_guard(d, facts)
            if bad:
                st.error("Numbers not in the computed facts: " + ", ".join(bad))
            else:
                ss.explanation = d
        except explain.NotConfigured as ex:
            st.info(str(ex))
    if ss.explanation:
        st.divider()
        _render_explanation(ss.explanation)
        next_button("Next: Make reports", "4. Report")


def render():
    ss = st.session_state
    st.title("Check")
    if ss.budget_df is None or ss.actuals_df is None or ss.cat_map is None:
        st.info("Finish the Upload and Map steps first (including Confirm categories).")
        next_button("Go to Map", "2. Map")
        return
    if not _run() or ss.result is None:
        return
    t1, t2 = st.tabs(["Results", "Explanation"])
    with t1:
        _results(ss.result)
    with t2:
        _explain(ss.result)
