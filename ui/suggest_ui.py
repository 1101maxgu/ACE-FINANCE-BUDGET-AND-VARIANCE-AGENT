"""Step 13: reallocation cards. Approve / dismiss / snooze records the decision only."""
from datetime import date, timedelta

import streamlit as st

from variance import realloc
from .common import author, next_button, usd


def render():
    ss = st.session_state
    s = ss.settings
    st.title("Suggestions")
    st.write("Ideas for moving unused budget to lines that are over. This is advice only: nothing here "
             "changes your budget file. Your choice is just recorded so the suggestion stops reappearing.")
    if ss.result is None:
        st.info("Calculate results on the Check screen first.")
        next_button("Go to Check", "3. Check")
        return
    if not author():
        st.warning("Type your name in the sidebar to record decisions.")
    sug = realloc.with_decisions(realloc.suggest(ss.result, s), realloc.load_decisions(s), date.today())
    L = ss.result.lines.set_index("line_id")
    shown = [x for x in sug if x["visible"]]
    if not sug:
        st.success("No reallocation ideas: no unused budget lines pair with over-budget lines.")
    elif not shown:
        st.info("All suggestions have been decided or snoozed.")
    for x in shown:
        a, b = L.loc[x["from_line_id"]], L.loc[x["to_line_id"]]
        with st.container(border=True):
            st.markdown(f"**Move {usd(x['amount_cents'])} from {x['from_name']} to {x['to_name']}**  "
                        f"`{x['status'].upper()}`")
            st.write(f"{x['from_name']}: budget {usd(a.budget_cents)}, actual {usd(a.actual_cents)}.  \n"
                     f"{x['to_name']}: budget {usd(b.budget_cents)}, actual {usd(b.actual_cents)}, "
                     f"over by {usd(b.variance_cents)}.")
            st.caption(x["note"])
            c = st.columns([1, 1, 1, 2])
            until = c[3].date_input("Snooze until", value=date.today() + timedelta(days=7),
                                    key=f"sn_{x['suggestion_id']}", format="YYYY-MM-DD")
            for col, (label, dec) in zip(c, [("Approve", "approved"), ("Dismiss", "dismissed"), ("Snooze", "snoozed")]):
                if col.button(label, key=f"{dec}_{x['suggestion_id']}", disabled=not author()):
                    realloc.record_decision(s, author(), x["suggestion_id"], dec, date.today(),
                                            until if dec == "snoozed" else None)
                    st.rerun()
    done = [x for x in sug if not x["visible"]]
    if done:
        with st.expander(f"Decided or snoozed ({len(done)})"):
            for x in done:
                st.write(f"{x['from_name']} -> {x['to_name']} {usd(x['amount_cents'])}: {x['decision']}")
