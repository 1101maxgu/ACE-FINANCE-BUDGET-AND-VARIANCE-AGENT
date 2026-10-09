"""Shared helpers for the screens. No business logic here."""
import io
import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from variance.settings import load_settings  # noqa: E402

PAGES = ["1. Upload", "2. Map", "3. Check", "4. Report", "Settings"]


class Mem(io.BytesIO):
    """An uploaded file kept in memory only. Never written to disk."""

    def __init__(self, name, data):
        super().__init__(data)
        self.name = name


def usd(cents):
    if cents is None:
        return ""
    c = int(cents)
    return f"{'-' if c < 0 else ''}${abs(c) // 100:,}.{abs(c) % 100:02d}"


def init_state():
    ss = st.session_state
    if "settings" not in ss:
        ss.settings = load_settings()
    for k, v in {"files": {}, "cfg": {}, "maps": {}, "profile": None, "budget_df": None, "actuals_df": None,
                 "cat_map": None, "result": None, "explanation": None, "page": PAGES[0]}.items():
        ss.setdefault(k, v)


def goto(page):
    st.session_state.page = page


def next_button(label, page, disabled=False):
    st.button(label, on_click=goto, args=(page,), disabled=disabled, type="primary")


def invalidate(*names):
    """Clear downstream results when an earlier step changes."""
    for n in names:
        st.session_state[n] = None
