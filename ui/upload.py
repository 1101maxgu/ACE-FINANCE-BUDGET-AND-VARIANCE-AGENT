"""Screen 1: two drop zones with sheet and header-row pickers."""
import streamlit as st

from variance import ingest
from .common import Mem, invalidate, next_button

KINDS = {"budget": "Budget file", "actuals": "Actuals export"}


def _zone(kind, label):
    ss = st.session_state
    st.subheader(label)
    up = st.file_uploader(f"Drop the {label.lower()} here (CSV or Excel)", type=["csv", "txt", "xlsx", "xlsm"],
                          key=f"up_{kind}")
    if up is not None and (kind not in ss.files or ss.files[kind].name != up.name
                           or ss.files[kind].getvalue() != up.getvalue()):
        ss.files[kind] = Mem(up.name, up.getvalue())
        ss.cfg.pop(kind, None)
        invalidate("budget_df", "actuals_df", "cat_map", "result", "explanation")
        ss.maps.pop(kind, None)
    f = ss.files.get(kind)
    if f is None:
        st.info("No file yet. Drag one in, or click Browse.")
        return False
    try:
        sheets = ingest.list_sheets(f)
        cfg = ss.cfg.setdefault(kind, {})
        c1, c2 = st.columns(2)
        sheet = c1.selectbox("Sheet", sheets, index=min(sheets.index(cfg["sheet"]) if cfg.get("sheet") in sheets else 0,
                                                       len(sheets) - 1), key=f"sheet_{kind}_{f.name}",
                             help="Which tab holds the data. CSV files have only one.")
        guess = ingest.guess_header_row(f, sheet)
        hdr = c2.number_input("Header row (row number holding the column titles)", min_value=1, step=1,
                              value=cfg.get("header_row", guess) + 1 if cfg.get("sheet") == sheet else guess + 1,
                              key=f"hdr_{kind}_{f.name}_{sheet}",
                              help="Notes above the table? Set this to the row with the column titles.") - 1
        cfg.update(sheet=sheet, header_row=int(hdr))
        st.caption(f"Loaded **{f.name}**. First rows as the app sees them:")
        st.dataframe(ingest.preview(f, sheet, hdr, 8), width="stretch")
        return True
    except ingest.IngestError as e:
        st.error(str(e))
    except Exception as e:  # unreadable/corrupt file
        st.error(f"I couldn't open this file ({e}). Check it is a CSV or .xlsx and not password protected.")
    return False


def render():
    st.title("Upload")
    st.write("Add your budget and your actuals export. Files are read in memory only and never changed.")
    ok = [_zone(k, v) for k, v in KINDS.items()]
    next_button("Next: Map columns", "2. Map", disabled=not all(ok))
