"""Shared setup for the AppTest smoke tests. In-memory data only."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from streamlit.testing.v1 import AppTest  # noqa: E402

from ui.common import Mem  # noqa: E402

BUDGET = b"Line,Category,Budget,Owner\nVenue,Venue,1000.00,Sam\nFood,Food,500.00,\nSpeakers,Speakers,0,\n"
ACTUALS = (b"Date,Amount,Category,Description\n2026-03-02,1400.00,Venue,Hall\n2026-03-05,200.00,Food,Pizza\n"
           b"2026-03-09,300.00,Speakers,Fee\n2026-03-09,300.00,Speakers,Fee\n2026-03-10,50.00,Mystery,Misc\n")


def btn(at, label):
    return next(b for b in at.button if b.label == label)


def make_app(tmp_path, monkeypatch, page="3. Check", calculate=True):
    """App with files loaded, mapped, categories confirmed, and (optionally) results calculated."""
    monkeypatch.setattr("variance.mapping.DEFAULT_PATH", tmp_path / "mappings.yaml")
    monkeypatch.setattr("variance.settings.DEFAULT_PATH", tmp_path / "settings.yaml")
    monkeypatch.setattr("variance.settings.ROOT", tmp_path)  # user_data (notes, decisions) -> temp
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60)
    at.run()
    ss = at.session_state
    ss.files = {"budget": Mem("b.csv", BUDGET), "actuals": Mem("a.csv", ACTUALS)}
    ss.cfg = {"budget": {"sheet": "(csv)", "header_row": 0}, "actuals": {"sheet": "(csv)", "header_row": 0}}
    ss.page = "2. Map"
    at.run()
    btn(at, "Save mapping and read the files").click().run()
    btn(at, "Confirm categories").click().run()
    ss.settings["period"] = {"label": "March", "start": "2026-03-01", "end": "2026-03-31"}
    ss.settings["reports_dir"] = str(tmp_path / "reports")
    ss.author = "Pat"
    ss.page = "3. Check"
    at.run()
    if calculate:
        btn(at, "Calculate variances").click().run()
        assert not at.exception, at.exception
    ss.page = page
    at.run()
    return at
