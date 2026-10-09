"""Coordinator notes: one JSON file per author in <data_dir>/notes/ (no sync conflicts)."""
import json
import re
from datetime import date as _date

from .settings import data_dir


def _author_file(settings, author):
    safe = re.sub(r"[^\w.-]", "_", author.strip())
    if not safe:
        raise ValueError("Please enter your name before saving a note.")
    d = data_dir(settings) / "notes"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{safe}.json"


def _read(p):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []


def add_note(settings, author, profile, line_id, period, txn_ids, text, date=None) -> dict:
    """Save a note answering 'why' for a line. period = period label. txn_ids = the line's
    transaction ids at the time of writing (used to detect new activity). Returns the note."""
    p = _author_file(settings, author)
    notes = _read(p)
    note = {"note_id": f"{p.stem}-{len(notes) + 1}", "author": author.strip(), "profile": profile,
            "line_id": line_id, "period": period, "txn_ids": sorted(map(str, txn_ids)), "text": text.strip(),
            "date": str(date or _date.today().isoformat())}
    p.write_text(json.dumps(notes + [note], indent=2), encoding="utf-8")
    return note


def load_notes(settings, profile=None, period=None) -> list:
    """All authors' notes, optionally filtered by profile name and period label."""
    d = data_dir(settings) / "notes"
    out = [n for f in sorted(d.glob("*.json")) for n in _read(f)] if d.exists() else []
    return [n for n in out if (profile is None or n["profile"] == profile) and (period is None or n["period"] == period)]


def delete_note(settings, author, note_id) -> bool:
    """Remove one of your own notes."""
    p = _author_file(settings, author)
    notes = _read(p)
    keep = [n for n in notes if n["note_id"] != note_id]
    p.write_text(json.dumps(keep, indent=2), encoding="utf-8")
    return len(keep) != len(notes)


def note_state(note, current_txn_ids) -> str:
    """'current' if the line has no transactions the note didn't know about, else 'stale' (re-ask)."""
    return "current" if set(map(str, current_txn_ids)) <= set(note["txn_ids"]) else "stale"
