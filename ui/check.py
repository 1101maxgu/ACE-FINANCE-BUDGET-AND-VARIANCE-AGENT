"""Screen 3: results (tiles, timing, table, chart, drill-down), data quality, explanation."""
from datetime import date

import pandas as pd
import streamlit as st

from variance import drilldown, explain
from variance.settings import save_settings
from .common import get_facts, invalidate, label_of, next_button, recalc, usd
from . import quality_ui

COLORS = {"unfavorable": "#f8d7da", "favorable": "#d4edda", "on_budget": "#e9ecef"}
STATUS_TEXT = {"unfavorable": "Unfavorable", "favorable": "Favorable", "on_budget": "On budget"}
CHIPS = {"ok": ("OK", "#d4edda"), "watch": ("Watch", "#fff3cd"), "over": ("Over", "#f5b7b1")}
MODES = ["Template", "Paste", "API"]
TAG_TEXT = {"one_time_spike": "One-time spike", "recurring": "Recurring", "timing_shift": "Timing shift"}


def _d(s):
    try:
        return date.fromisoformat(str(s))
    except ValueError:
        return None


def _run():
    ss = st.session_state
    s = ss.settings
    st.write("Which period is this report for? It is never guessed from the data.")
    p = s["period"] if (s["period"].get("start") or s["period"].get("end")) else s["last_period"]
    c0, c1, c2, c3 = st.columns([2, 2, 2, 2])
    label = c0.text_input("Period name", value=p.get("label", ""), key="chk_label", help="For example: March 2026.")
    start = c1.date_input("Period start", value=_d(p.get("start")), format="YYYY-MM-DD", key="chk_start")
    end = c2.date_input("Period end", value=_d(p.get("end")), format="YYYY-MM-DD", key="chk_end")
    asof = c3.date_input("Report as of", value=_d(ss.asof) or (min(date.today(), end) if end else date.today()),
                         format="YYYY-MM-DD", key="chk_asof", help="Spending after this date is left out.")
    if not (start and end):
        st.warning("Pick the period start and end to continue.")
        return False
    if start > end:
        st.error("Period start is after period end.")
        return False
    if st.button("Calculate variances", type="primary"):
        per = {"label": label.strip() or f"{start} to {end}", "start": start.isoformat(), "end": end.isoformat()}
        s.update(period=per, last_period=dict(per))
        ss.asof = asof.isoformat()
        err = recalc()
        if err:
            st.error(err)
            return False
        save_settings(s)
        invalidate("explanation")
    return True


def _controls():
    """Step 7: timing and threshold controls."""
    ss = st.session_state
    s = ss.settings
    with st.expander("Timing and thresholds"):
        c = st.columns(4)
        pe = c[0].text_input("% of period elapsed (blank = work it out from the dates)",
                             value=str(s.get("pct_elapsed", "")), help="Type 50 if you are half way through.")
        ew = c[1].number_input("Early warning at % of budget used", 0, 200, int(s.get("early_warning_pct", 80)))
        pct = c[2].number_input("Flag at least this %", 0.0, value=float(s["flag_pct"]), step=1.0,
                                help="A line is flagged when BOTH the % and the dollar limit are passed.")
        dol = c[3].number_input("Flag at least this many $", 0.0, value=s["flag_min_cents"] / 100, step=10.0)
        if st.button("Apply and recalculate"):
            try:
                pe_v = "" if not pe.strip() else float(pe)
            except ValueError:
                st.error("% elapsed must be a number between 0 and 100, or blank.")
                return
            s.update(pct_elapsed=pe_v, early_warning_pct=int(ew), flag_pct=pct, flag_min_cents=int(round(dol * 100)))
            err = recalc()
            if err:
                st.error(err)
            else:
                save_settings(s)
                invalidate("explanation")
                st.rerun()


def _num(col):
    return pd.to_numeric(col, errors="coerce").astype("float64") / 100


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
        "Committed": _num(v.committed_cents), "Actual": v.actual_cents / 100, "Variance": v.variance_cents / 100,
        "Variance %": v.variance_pct, "Status": v.status.map(STATUS_TEXT),
        "Flag": v.flagged.map({True: "FLAG", False: ""}), "Pace": v.chip.map(lambda c: CHIPS.get(c, ("", ""))[0]),
        "Expected to date": _num(v.expected_cents), "Pace variance": _num(v.pace_variance_cents),
        "Projection": _num(v.projection_cents), "Confidence": v.projection_confidence.str.capitalize(),
        "Owner": v.owner}).reset_index(drop=True)
    colors = v.status.map(COLORS).tolist()
    sty = show.style.apply(lambda row: [f"background-color: {colors[row.name]}; color: #222"] * len(row), axis=1)
    sty = sty.map(lambda x: f"background-color: {next((c for n, c in CHIPS.values() if n == x), '#fff')}; "
                            "color: #222; font-weight: bold" if x else "", subset=["Pace"])
    money = {k: "${:,.2f}" for k in ("Budget", "Committed", "Actual", "Variance", "Expected to date",
                                     "Pace variance", "Projection")}
    sty = sty.format({**money, "Variance %": "{:.2f}%"}, na_rep="-")
    st.dataframe(sty, width="stretch", hide_index=True)
    st.markdown(" ".join(f"<span style='background:{COLORS[k]};padding:2px 8px;border-radius:4px;color:#222'>"
                         f"{STATUS_TEXT[k]}</span>" for k in COLORS) + " " +
                " ".join(f"<span style='background:{c};padding:2px 8px;border-radius:4px;color:#222'>Pace: {n}</span>"
                         for n, c in CHIPS.values()) +
                "  Variance = actual minus budget. Revenue under target counts as unfavorable. "
                "'-' = not available (no budget set, or no period dates). Projection confidence is low early "
                "in the period or with few transactions.", unsafe_allow_html=True)


def _drill(r):
    """Step 9: expandable top transactions with tags and source-row trace."""
    fl = r.lines[r.lines.flagged]
    if fl.empty:
        return
    st.subheader("Why is it flagged? Top transactions")
    for ln in fl.itertuples():
        d = drilldown.drill(r, ln.line_id, n=5)
        tags = ", ".join(TAG_TEXT.get(t, t) for t in d["tags"]) or "no pattern detected"
        with st.expander(f"{ln.line_name}: {usd(ln.variance_cents)} ({tags})"):
            if not d["top_transactions"]:
                st.write("No transactions in this period for this line.")
                continue
            st.dataframe(pd.DataFrame([{
                "Source row": t["source_row"], "Txn": t["txn_id"], "Date": t["date"], "Amount": t["amount_cents"] / 100,
                "Vendor": t["vendor"], "Description": t["description"], "Tag": TAG_TEXT.get(t["tag"], t["tag"])}
                for t in d["top_transactions"]]).style.format({"Amount": "${:,.2f}"}),
                width="stretch", hide_index=True)
            st.caption("Source row = the row number in your actuals file.")


def _results(r):
    t = r.totals
    if r.quality and any(f["severity"] == "critical" for f in r.quality):
        st.error("UNRECONCILED: the actuals do not match the total you stated. See the Data quality tab.")
    c = st.columns(5)
    c[0].metric("Expense budget", usd(t["expense_budget_cents"]))
    c[1].metric("Expense actual", usd(t["expense_actual_cents"]))
    c[2].metric("Net variance", usd(t["net_variance_cents"]), help="Positive = better than budget overall.")
    c[3].metric("Flagged lines", t["flagged_count"], help=f"of {t['line_count']} lines")
    c[4].metric("Period elapsed", "n/a" if t.get("pct_elapsed") is None else f"{t['pct_elapsed']:.0f}%")
    if t["excluded_row_count"]:
        st.info(f"{t['excluded_row_count']} transaction(s) ({usd(t['excluded_cents'])}) "
                "are outside the period and left out.")
    if t["unbudgeted_cents"]:
        st.warning(f"{usd(t['unbudgeted_cents'])} was spent in categories with no budget line "
                   "(shown as UNBUDGETED).")
    _controls()
    _table(r)
    g = r.lines.groupby("category", sort=False)[["budget_cents", "actual_cents"]].sum() / 100
    st.subheader("Budget vs actual by category")
    st.bar_chart(g.rename(columns={"budget_cents": "Budget", "actual_cents": "Actual"}))
    _drill(r)


def render_explanation(e):
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
    ss.redact = st.checkbox("Redact descriptions and vendors", value=bool(ss.redact), key="redact_w",
                            help="Leaves transaction descriptions and vendor names out of what is sent.")
    facts = get_facts()
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
    else:
        with st.expander("Exactly what will be sent"):
            st.code(explain.build_prompt(facts), language="markdown", wrap_lines=True)
        if st.button("Ask Claude through the API"):
            try:
                ss.explanation = explain.explain_api(facts, s)
            except explain.NotConfigured as ex:
                st.info(str(ex))
            except explain.ExplainError as ex:
                st.error(str(ex))
    if ss.explanation:
        st.divider()
        render_explanation(ss.explanation)
        next_button("Next: Make reports", "4. Report")


def render():
    ss = st.session_state
    st.title("Check")
    if ss.budget_df is None or ss.actuals_df is None or ss.cat_map is None:
        st.info("Finish the Upload and Map steps first (including Confirm categories).")
        next_button("Go to Map", "2. Map")
        return
    if not _run():
        return
    if ss.result is None:
        st.info("Press Calculate variances to see totals, flagged lines and the chart.")
        return
    t1, t2, t3 = st.tabs(["Results", "Data quality", "Explanation"])
    with t1:
        _results(ss.result)
    with t2:
        quality_ui.render()
    with t3:
        _explain(ss.result)
