"""Shared helpers for the screens. No business logic here."""
import io
import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from variance.settings import load_settings  # noqa: E402

PAGES = ["1. Upload", "2. Map", "3. Check", "4. Report", "Needs your answer", "Suggestions", "Email",
         "Reimbursements", "Schedule", "Settings"]


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
                 "cat_map": None, "result": None, "explanation": None, "page": PAGES[0],
                 "committed": {}, "dupes": [], "stated": None, "asof": None}.items():
        ss.setdefault(k, v)
    ss.setdefault("redact", bool(ss.settings.get("redact")))
    ss.setdefault("author", ss.settings.get("author", ""))


def author():
    return (st.session_state.get("author") or "").strip()


def label_of(settings):
    p = settings["period"]
    return p.get("label") or f"{p.get('start')} to {p.get('end')}"


def recalc():
    """Run the single backend entry point with everything the user has chosen. Returns an error text or None."""
    from variance import notes as N, pipeline, reimburse
    ss = st.session_state
    s = ss.settings
    profile = {"budget": ss.maps["budget"], "actuals": ss.maps["actuals"], "category_map": ss.cat_map or {}}
    try:
        out = pipeline.run(ss.files["budget"], ss.files["actuals"], s, profile, ss.asof, bool(ss.redact),
                           stated_total_cents=ss.stated, committed=reimburse.committed_by_line(s) or None,
                           intentional_dupes=ss.dupes, notes=N.load_notes(s, ss.profile, label_of(s)))
    except Exception as e:  # IngestError / ValueError: show plainly
        return str(e)
    ss.result = out["result"]
    return None


def get_facts():
    """Facts for the current result, with the latest notes and the redaction choice."""
    from variance import facts as F, notes as N
    ss = st.session_state
    s = ss.settings
    return F.build_facts(ss.result, s, bool(ss.redact), notes=N.load_notes(s, ss.profile, label_of(s)))


def goto(page):
    st.session_state.page = page


def next_button(label, page, disabled=False):
    st.button(label, on_click=goto, args=(page,), disabled=disabled, type="primary")


def invalidate(*names):
    """Clear downstream results when an earlier step changes."""
    for n in names:
        st.session_state[n] = None
