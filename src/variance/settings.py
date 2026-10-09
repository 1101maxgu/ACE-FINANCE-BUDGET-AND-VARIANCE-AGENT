"""Settings loader. Secrets never live here (use a local .env)."""
import copy
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PATH = ROOT / "user_data" / "settings.yaml"

_PERIOD = {"label": "", "start": "", "end": ""}
DEFAULTS = {
    "shared_folder": "",
    "reports_dir": "reports",
    "flag_pct": 10.0,
    "flag_min_cents": 15000,
    "early_warning_pct": 80,
    "explain_mode": "paste",
    "redact": False,
    "period": dict(_PERIOD),
    "last_period": dict(_PERIOD),
}


def load_settings(path=None) -> dict:
    """Return settings: defaults overlaid with the YAML file (missing file = defaults)."""
    p = Path(path) if path else DEFAULT_PATH
    out = copy.deepcopy(DEFAULTS)
    if p.exists():
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        for k, v in data.items():
            if isinstance(v, dict) and isinstance(out.get(k), dict):
                out[k].update(v)
            else:
                out[k] = v
    return out


def save_settings(settings: dict, path=None) -> Path:
    """Write settings to YAML (creates the folder). Returns the path."""
    p = Path(path) if path else DEFAULT_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump(settings, sort_keys=False), encoding="utf-8")
    return p
