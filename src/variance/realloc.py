"""Reallocation suggestions. ADVICE ONLY: nothing here changes a budget; decisions are just recorded."""
import json
import re

import pandas as pd

from .settings import data_dir

DECISIONS = ("approved", "dismissed", "snoozed")


def suggest(result, settings) -> list:
    """Pair surplus expense lines with over-budget expense lines (largest first, greedy).

    surplus = budget - max(actual, projection) when positive and >= flag_min_cents (favorable lines only)
    need    = actual - budget for flagged unfavorable expense lines
    Returns [{suggestion_id, from_line_id, from_name, to_line_id, to_name, amount_cents, status:'for approval', note}].
    """
    floor = int(settings.get("flag_min_cents", 15000))
    L = result.lines
    exp = L[L.type == "expense"]
    surplus, need = {}, {}
    for r in exp.itertuples():
        proj = 0 if pd.isna(r.projection_cents) else int(r.projection_cents)
        free = r.budget_cents - max(r.actual_cents, proj)
        if r.status == "favorable" and free >= floor:
            surplus[r.line_id] = free
        elif r.status == "unfavorable" and r.flagged:
            need[r.line_id] = r.actual_cents - r.budget_cents
    names = dict(zip(L.line_id, L.line_name))
    out = []
    for to in sorted(need, key=lambda k: -need[k]):
        for frm in sorted(surplus, key=lambda k: -surplus[k]):
            amt = min(need[to], surplus[frm])
            if amt <= 0:
                continue
            out.append({"suggestion_id": f"{frm}->{to}", "from_line_id": frm, "from_name": names[frm],
                        "to_line_id": to, "to_name": names[to], "amount_cents": int(amt),
                        "status": "for approval", "note": "Advice only. No budget has been changed."})
            need[to] -= amt
            surplus[frm] -= amt
    return out


def _file(settings, author):
    safe = re.sub(r"[^\w.-]", "_", author.strip())
    if not safe:
        raise ValueError("Please enter your name.")
    d = data_dir(settings) / "decisions"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{safe}.json"


def record_decision(settings, author, suggestion_id, decision, date, snooze_until=None) -> dict:
    """Record approve / dismiss / snooze. Only records; never applies anything."""
    if decision not in DECISIONS:
        raise ValueError(f"decision must be one of {DECISIONS}")
    p = _file(settings, author)
    rows = json.loads(p.read_text(encoding="utf-8")) if p.exists() else []
    rec = {"suggestion_id": suggestion_id, "decision": decision, "author": author.strip(),
           "date": str(date), "snooze_until": str(snooze_until) if snooze_until else None}
    p.write_text(json.dumps(rows + [rec], indent=2), encoding="utf-8")
    return rec


def load_decisions(settings) -> list:
    d = data_dir(settings) / "decisions"
    out = [r for f in sorted(d.glob("*.json")) for r in json.loads(f.read_text(encoding="utf-8"))] if d.exists() else []
    return sorted(out, key=lambda r: r["date"])


def with_decisions(suggestions, decisions, on_date) -> list:
    """Attach each suggestion's latest decision and a 'visible' flag (dismissed, approved, or snoozed-until-later
    suggestions are not visible)."""
    latest = {r["suggestion_id"]: r for r in decisions}
    out = []
    for s in suggestions:
        d = latest.get(s["suggestion_id"])
        hidden = bool(d) and (d["decision"] in ("approved", "dismissed") or
                              (d["decision"] == "snoozed" and str(on_date) < (d["snooze_until"] or "")))
        out.append({**s, "decision": d["decision"] if d else None, "visible": not hidden})
    return out
