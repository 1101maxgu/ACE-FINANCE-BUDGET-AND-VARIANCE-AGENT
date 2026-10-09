"""Data-quality tab: issue list with counts and affected rows, plus fix actions (Step 8)."""
import streamlit as st

from variance import mapping
from .common import invalidate, recalc, usd


def _apply(msg):
    err = recalc()
    invalidate("explanation")
    if err:
        st.error(err)
    else:
        st.success(msg)
        st.rerun()


def render():
    ss = st.session_state
    r = ss.result
    q = r.quality or []
    st.write("These checks run before any report. Nothing here changes your files.")
    if not q:
        st.success("No data-quality problems found.")
    for f in q:
        box = st.error if f["severity"] == "critical" else st.warning
        box(f"**{f['code'].replace('_', ' ').title()}**: {f['message']}"
            + (f"  \nAffected rows in your file: {', '.join(map(str, f['rows'][:30]))}"
               + (" ..." if len(f["rows"]) > 30 else "") if f["rows"] else ""))
    st.subheader("Fix actions")
    # map a category
    unm = sorted({c for c in r.txns[r.txns.line_id.str.startswith("UNBUDGETED:")].category if str(c).strip()})
    if unm:
        with st.container(border=True):
            st.markdown("**Map a category to a budget line**")
            b = ss.budget_df
            ids = [""] + list(b.line_id)
            names = dict(zip(b.line_id, b.category + " / " + b.line_name))
            names[""] = "(leave as unbudgeted)"
            c1, c2 = st.columns(2)
            cat = c1.selectbox("Category from your actuals", unm, key="fx_cat")
            tgt = c2.selectbox("Budget line", ids, format_func=names.get, key="fx_tgt")
            if st.button("Apply mapping", disabled=not tgt):
                ss.cat_map = {**(ss.cat_map or {}), cat: tgt}
                if ss.profile:
                    mapping.save_category_map(ss.profile, ss.cat_map)
                _apply(f"'{cat}' now maps to {names[tgt]}.")
    # duplicates
    dup = [f for f in q if f["code"] == "possible_duplicate"]
    if dup:
        with st.container(border=True):
            st.markdown("**Possible duplicates**: tick the ones that are real, separate payments.")
            keep = set(ss.dupes)
            picks = []
            for i, f in enumerate(dup):
                if st.checkbox(f["message"] + f" (rows {', '.join(map(str, f['rows']))})", key=f"dup_{i}",
                               value=all(t in keep for t in f["txn_ids"])):
                    picks += f["txn_ids"]
            if st.button("Mark ticked as intentional"):
                ss.dupes = sorted(set(ss.dupes) | set(picks))
                _apply("Marked as intentional.")
    elif ss.dupes:
        st.caption(f"{len(ss.dupes)} transaction(s) marked as intentional duplicates.")
    # stated total
    with st.container(border=True):
        st.markdown("**Reconcile to a total you know**")
        cur = None if ss.stated is None else ss.stated / 100
        v = st.number_input("The actuals should add up to ($, net spend)", value=cur, step=100.0, format="%.2f",
                            key="fx_total", help="For example the total on your bank or ledger statement. "
                                                 "Leave empty to skip the check.")
        c1, c2 = st.columns(2)
        if c1.button("Check this total"):
            ss.stated = None if v is None else int(round(v * 100))
            _apply("Total entered.")
        if ss.stated is not None and c2.button("Clear stated total"):
            ss.stated = None
            _apply("Cleared.")
        st.caption(f"Current actuals total in the period: {usd(int(r.txns.amount_cents.sum()))}")
