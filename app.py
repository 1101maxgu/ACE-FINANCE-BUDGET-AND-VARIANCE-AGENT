"""Budget & Variance Agent - Streamlit shell. Logic lives in src/variance; screens in ui/."""
import streamlit as st

from ui.common import PAGES, init_state

st.set_page_config(page_title="Budget & Variance", layout="wide")
init_state()

from ui import check, mapping_ui, report, settings_ui, upload  # noqa: E402

SCREENS = dict(zip(PAGES, [upload.render, mapping_ui.render, check.render, report.render, settings_ui.render]))

st.sidebar.title("Budget & Variance")
st.sidebar.radio("Steps", PAGES, key="page")
st.sidebar.caption("Code does the math. Claude explains. You approve everything.")
SCREENS[st.session_state.page]()
