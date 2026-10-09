"""Screen 2: mapping wizard, saved-profile banner, category mapping."""
import copy
from pathlib import Path

import streamlit as st

from variance import ingest, mapping
from .common import invalidate, next_button, usd

NONE = "(none)"
NEW = "(new mapping)"
BUDGET_FIELDS = {"line_id": "Line ID (optional)", "line_name": "Line name", "category": "Category",
                 "type": "Type: expense/revenue (optional)", "budget": "Budget amount", "owner": "Owner (optional)"}
ACTUAL_FIELDS = {"txn_id": "Transaction ID (optional)", "date": "Date", "amount": "Amount", "debit": "Debit",
                 "credit": "Credit", "category": "Category", "description": "Description (optional)",
                 "vendor": "Vendor (optional)"}
SIGNS = {
    "positive_expenses": "Spending shows as positive numbers (refunds negative)",
    "negative_expenses": "Spending shows as negative numbers (refunds positive)",
    "debit_credit": "There are separate Debit and Credit columns",
}
LAYOUTS = {"total": "One total per line", "monthly_wide": "One column per month",
           "sections": "Sections (headings with lines under them)"}
DATE_ORDERS = {None: "Not sure - ask me only if dates are ambiguous", "dmy": "Day first (31/12/2026)",
               "mdy": "Month first (12/31/2026)"}


def _frame(kind):
    ss = st.session_state
    c = ss.cfg[kind]
    return ingest.preview(ss.files[kind], c["sheet"], c["header_row"], 1000)


def _pick_profile(budget_cols_df):
    """Banner + picker. Returns (profile_name or None, saved profile dict)."""
    ss = st.session_state
    profiles = mapping.load_profiles()
    if ss.profile not in profiles:
        ss.profile = mapping.find_profile_by_fingerprint(budget_cols_df)
    if ss.profile and not ss.get("change_profile"):
        c1, c2 = st.columns([5, 1])
        c1.success(f"Using saved mapping **{ss.profile}**")
        if c2.button("Change"):
            ss.change_profile = True
            st.rerun()
    else:
        opts = [NEW] + list(profiles)
        choice = st.selectbox("Saved mapping (one per coordinator budget)", opts,
                              index=opts.index(ss.profile) if ss.profile in profiles else 0)
        new = None if choice == NEW else choice
        if new != ss.profile:
            ss.profile = new
            ss.maps = {}
            invalidate("budget_df", "actuals_df", "cat_map", "result", "explanation")
        if ss.get("change_profile") and st.button("Done"):
            ss.change_profile = False
            st.rerun()
    return ss.profile, profiles.get(ss.profile) or {}


def _editor(kind, df, saved):
    ss = st.session_state
    c = ss.cfg[kind]
    guessed = mapping.guess_mapping(df, kind)
    if kind not in ss.maps:
        m = copy.deepcopy(saved.get(kind)) if saved.get(kind) else guessed
        if any(v and v not in df.columns for v in (m.get("columns") or {}).values()):
            m = guessed  # saved mapping does not fit this file
        ss.maps[kind] = m
    m = ss.maps[kind]
    m.update(sheet=c["sheet"], header_row=c["header_row"], fingerprint=guessed["fingerprint"])
    cols = [NONE] + list(df.columns)
    key = f"{kind}_{ss.profile}_{ss.files[kind].name}"
    if kind == "actuals":
        m["sign"] = st.radio("How does your actuals file show spending?", list(SIGNS), format_func=SIGNS.get,
                             index=list(SIGNS).index(m.get("sign", "positive_expenses")), key=f"sign_{key}")
        drop = ("amount",) if m["sign"] == "debit_credit" else ("debit", "credit")
        fields = {k: v for k, v in ACTUAL_FIELDS.items() if k not in drop}
    else:
        m["layout"] = st.radio("How is the budget laid out?", list(LAYOUTS), format_func=LAYOUTS.get,
                               index=list(LAYOUTS).index(m.get("layout", "total")), key=f"layout_{key}",
                               horizontal=True)
        fields = dict(BUDGET_FIELDS)
        if m["layout"] == "monthly_wide":
            fields.pop("budget")
            m["month_columns"] = st.multiselect(
                "Month columns (they are added up)", list(df.columns), key=f"months_{key}",
                default=[x for x in m.get("month_columns", []) if x in df.columns])
    cc = st.columns(2)
    for i, (f, label) in enumerate(fields.items()):
        cur = m["columns"].get(f)
        pick = cc[i % 2].selectbox(label, cols, index=cols.index(cur) if cur in cols else 0, key=f"col_{f}_{key}")
        m["columns"][f] = None if pick == NONE else pick
    if kind == "actuals":
        m["date_order"] = st.selectbox("Date order in this file", list(DATE_ORDERS), format_func=DATE_ORDERS.get,
                                       index=list(DATE_ORDERS).index(m.get("date_order")), key=f"order_{key}")
    st.caption("Preview of your data:")
    st.dataframe(df.head(6), width="stretch")
    return m


def _category_section():
    ss = st.session_state
    st.subheader("Match categories")
    st.write("Each category in your actuals needs a budget line. Suggestions are preselected. "
             "Anything left as unbudgeted still shows in the report; nothing is dropped.")
    b, a = ss.budget_df, ss.actuals_df
    saved = (mapping.load_profiles().get(ss.profile) or {}).get("category_map") if ss.profile else None
    ids = [""] + list(b.line_id)
    names = dict(zip(b.line_id, b.category + " / " + b.line_name))
    names[""] = "(leave as unbudgeted)"
    status = {"saved": "saved", "exact": "exact match", "ambiguous": "several matches - check",
              "suggested": "suggestion - check", "unmatched": "no match"}
    out = {}
    for r in mapping.suggest_categories(a, b, saved):
        c1, c2, c3 = st.columns([3, 4, 2])
        c1.write(f"**{r['actual_category'] or '(blank)'}**  \n{r['count']} rows, {usd(r['total_cents'])}")
        sug = r["suggestion"] if r["suggestion"] in ids else ""
        out[r["actual_category"]] = c2.selectbox(
            "Budget line", ids, index=ids.index(sug), format_func=names.get, label_visibility="collapsed",
            key=f"cat_{ss.profile}_{r['actual_category']}")
        c3.caption(status[r["status"]])
    return out


def render():
    ss = st.session_state
    st.title("Map columns")
    if not all(k in ss.files and k in ss.cfg for k in ("budget", "actuals")):
        st.info("Upload both files first.")
        next_button("Go to Upload", "1. Upload")
        return
    try:
        bdf, adf = _frame("budget"), _frame("actuals")
    except ingest.IngestError as e:
        st.error(str(e))
        return
    name, saved = _pick_profile(bdf)
    t1, t2 = st.tabs(["Budget columns", "Actuals columns"])
    with t1:
        bm = _editor("budget", bdf, saved)
    with t2:
        am = _editor("actuals", adf, saved)
    pname = st.text_input("Name for this mapping (e.g. the coordinator or budget name)",
                          value=name or Path(ss.files["budget"].name).stem,
                          help="Saved so next time this is automatic.")
    if st.button("Save mapping and read the files", type="primary"):
        try:
            ss.budget_df = ingest.load_budget(ss.files["budget"], bm)
            ss.actuals_df = ingest.load_actuals(ss.files["actuals"], am)
        except ingest.IngestError as e:
            ss.budget_df = ss.actuals_df = None
            st.error(f"**Problem reading your file:** {e}")
        else:
            mapping.save_profile(pname, {"budget": bm, "actuals": am})
            ss.profile = pname
            invalidate("cat_map", "result", "explanation")
            st.rerun()
    if ss.budget_df is None:
        return
    st.success(f"Read {len(ss.budget_df)} budget lines and {len(ss.actuals_df)} transactions.")
    for k, df in (("Budget", ss.budget_df), ("Actuals", ss.actuals_df)):
        sk = df.attrs.get("skipped_rows") or []
        if sk:
            with st.expander(f"{k}: {len(sk)} row(s) skipped (totals or blank)"):
                st.write([f"row {r}: {t}" for r, t in sk])
    cm = _category_section()
    if st.button("Confirm categories", type="primary"):
        mapping.save_category_map(ss.profile, cm)
        ss.cat_map = cm
        invalidate("result", "explanation")
        st.success("Categories saved.")
    next_button("Next: Check results", "3. Check", disabled=ss.cat_map is None)
