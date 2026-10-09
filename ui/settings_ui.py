"""Settings screen: period (prefilled from last used), thresholds, folders."""
from datetime import date

import streamlit as st

from variance.settings import save_settings
from .common import invalidate

MODES = ["template", "paste", "api"]


def _d(s):
    try:
        return date.fromisoformat(str(s)) if s else None
    except ValueError:
        return None


def render():
    ss = st.session_state
    s = ss.settings
    st.title("Settings")
    st.write("The period is asked every run and is never guessed from the data. "
             "It starts with what you used last time.")
    p = s["period"] if (s["period"].get("start") or s["period"].get("end")) else s["last_period"]
    with st.form("settings"):
        label = st.text_input("Period name (e.g. March 2026)", value=p.get("label", ""))
        c1, c2 = st.columns(2)
        start = c1.date_input("Period start", value=_d(p.get("start")), format="YYYY-MM-DD")
        end = c2.date_input("Period end", value=_d(p.get("end")), format="YYYY-MM-DD")
        st.subheader("When is a line flagged?")
        c3, c4 = st.columns(2)
        pct = c3.number_input("At least this % off budget", min_value=0.0, value=float(s["flag_pct"]), step=1.0,
                              help="A line is flagged only when BOTH limits are passed (default 10% and $150).")
        dollars = c4.number_input("and at least this many dollars off", min_value=0.0,
                                  value=s["flag_min_cents"] / 100, step=10.0,
                                  help="Small dollar differences are ignored even if the percentage is large.")
        st.subheader("Folders and defaults")
        shared = st.text_input("Shared folder for reports (optional)", value=s.get("shared_folder", ""),
                               help="A synced Drive/OneDrive folder. Leave empty to keep reports on this computer only.")
        mode = st.selectbox("Default explanation mode", MODES,
                            index=MODES.index(s.get("explain_mode", "paste")))
        redact = st.checkbox("Hide transaction descriptions in what is sent for explanation",
                             value=bool(s.get("redact")))
        saved = st.form_submit_button("Save settings", type="primary")
    if saved:
        if start and end and start > end:
            st.error("Period start is after period end.")
            return
        per = {"label": label, "start": start.isoformat() if start else "", "end": end.isoformat() if end else ""}
        s.update(period=per, last_period=dict(per), flag_pct=pct, flag_min_cents=int(round(dollars * 100)),
                 shared_folder=shared.strip(), explain_mode=mode, redact=redact)
        save_settings(s)
        invalidate("result", "explanation")
        st.success("Saved.")
