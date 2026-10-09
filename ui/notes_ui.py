"""Step 12: 'Needs your answer' inbox, answer box (date + author) and notes manager."""
from datetime import date

import streamlit as st

from variance import notes as N
from .common import author, get_facts, label_of, next_button, recalc, usd


def render():
    ss = st.session_state
    s = ss.settings
    st.title("Needs your answer")
    st.write("Lines flagged by the numbers whose cause is not known yet. Your answer is saved as a note "
             "and used the next time an explanation is written. If new transactions arrive on a line, "
             "its question is asked again.")
    if ss.result is None:
        st.info("Calculate results on the Check screen first.")
        next_button("Go to Check", "3. Check")
        return
    if not author():
        st.warning("Type your name in the sidebar first, so your answers are saved under it.")
    facts = get_facts()
    period = label_of(s)
    todo = [f for f in facts["flagged_lines"]
            if not any(n["state"] == "current" for n in f.get("coordinator_notes", []))]
    if not todo:
        st.success("Nothing needs an answer right now.")
    for f in todo:
        stale = [n for n in f.get("coordinator_notes", []) if n["state"] == "stale"]
        owner = f.get("owner") or "the report runner"
        with st.container(border=True):
            st.markdown(f"**{f['line_name']}**: {usd(f['variance_cents'])} vs budget "
                        f"(budget {usd(f['budget_cents'])}, actual {usd(f['actual_cents'])})")
            st.caption(f"Question goes to: {owner}")
            st.write(f"What explains the difference on {f['line_name']}?")
            if stale:
                st.warning("New transactions arrived since the last answer: " + "; ".join(
                    f"{n['author']} ({n['date']}): {n['text']}" for n in stale))
            c1, c2 = st.columns([4, 1])
            text = c1.text_area("Your answer", key=f"ans_{f['line_id']}", height=80)
            when = c2.date_input("Date", value=date.today(), key=f"ansd_{f['line_id']}", format="YYYY-MM-DD")
            if st.button("Save answer", key=f"save_{f['line_id']}", disabled=not (text.strip() and author())):
                ids = ss.result.txns[ss.result.txns.line_id == f["line_id"]].txn_id
                N.add_note(s, author(), ss.profile or "", f["line_id"], period, list(ids), text, when)
                recalc()
                st.rerun()
    st.subheader("Notes for this period")
    mine = N.load_notes(s, ss.profile or "", period)
    if not mine:
        st.caption("No notes saved yet.")
    names = dict(zip(ss.result.lines.line_id, ss.result.lines.line_name))
    for n in mine:
        c1, c2 = st.columns([6, 1])
        c1.markdown(f"**{names.get(n['line_id'], n['line_id'])}** - {n['author']}, {n['date']}: {n['text']}")
        if n["author"] == author() and c2.button("Delete", key=f"del_{n['note_id']}"):
            N.delete_note(s, author(), n["note_id"])
            recalc()
            st.rerun()
    st.caption(f"Notes are stored one file per person in: {N.data_dir(s) / 'notes'}")
