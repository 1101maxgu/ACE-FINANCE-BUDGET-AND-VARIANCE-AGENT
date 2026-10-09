"""Budget & Variance Agent - Streamlit shell. Logic lives in src/variance; screens in ui/."""
import streamlit as st

from ui.common import PAGES, init_state

st.set_page_config(page_title="Budget & Variance", layout="wide")
init_state()

from ui import (check, claims_ui, gmail_ui, mapping_ui, notes_ui, report, schedule_ui,  # noqa: E402
                settings_ui, suggest_ui, upload)

SCREENS = {"1. Upload": upload.render, "2. Map": mapping_ui.render, "3. Check": check.render,
           "4. Report": report.render, "Needs your answer": notes_ui.render, "Suggestions": suggest_ui.render,
           "Email": gmail_ui.render, "Reimbursements": claims_ui.render, "Schedule": schedule_ui.render,
           "Settings": settings_ui.render}

st.sidebar.title("Budget & Variance")
st.sidebar.text_input("Your name", key="author", help="Saved with your notes and decisions.")
st.sidebar.radio("Steps", PAGES, key="page")
st.sidebar.caption("Code does the math. Claude explains. You approve everything.")
SCREENS[st.session_state.page]()
