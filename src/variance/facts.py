"""facts.json: the only thing the explainer ever sees. Computed numbers only, never raw files."""
import json
import math

import pandas as pd

from . import drilldown, notes as notes_mod, quality, realloc

_ITEM = ("line_id", "category", "line_name", "type", "owner", "budget_cents", "actual_cents", "variance_cents",
         "variance_pct", "status", "txn_count", "committed_cents", "expected_cents", "pace_variance_cents",
         "projection_cents", "projection_confidence", "early_warning", "chip")


def _clean(v):
    if v is pd.NA or (isinstance(v, float) and math.isnan(v)):
        return None
    if hasattr(v, "item"):
        v = v.item()
    return v


def build_facts(result, settings, redact=False, notes=None) -> dict:
    """Period, thresholds, totals, flagged lines (top 3 transactions + tags + coordinator notes each),
    watch lines, quality findings, reallocation candidates.

    redact=True leaves out transaction descriptions and vendors.
    notes: list of note dicts (variance.notes.load_notes); matched by line_id + period label.
    """
    L = result.lines
    flagged = L[L.flagged].copy()
    flagged = flagged.reindex(flagged.variance_cents.abs().sort_values(ascending=False, kind="stable").index)
    period = dict(result.period or {})
    label = period.get("label", "")
    out = []
    for r in flagged.to_dict("records"):
        item = {k: _clean(r[k]) for k in _ITEM}
        d = drilldown.drill(result, r["line_id"], n=3)
        item["tags"] = d["tags"]
        item["top_transactions"] = [
            {k: v for k, v in t.items() if not (redact and k in ("vendor", "description"))}
            for t in d["top_transactions"]]
        ids = result.txns[result.txns.line_id == r["line_id"]].txn_id
        item["coordinator_notes"] = [
            {"author": n["author"], "date": n["date"], "text": n["text"], "state": notes_mod.note_state(n, ids)}
            for n in (notes or []) if n["line_id"] == r["line_id"] and n["period"] == label]
        out.append(item)
    watch = L[~L.flagged & (L.early_warning | L.pace_flagged)]
    q = list(result.quality or [])
    return {
        "period": {k: period.get(k, "") for k in ("label", "start", "end")},
        "as_of_date": result.as_of_date.isoformat(),
        "thresholds": {"flag_pct": settings.get("flag_pct", 10.0),
                       "flag_min_cents": int(settings.get("flag_min_cents", 15000)),
                       "early_warning_pct": settings.get("early_warning_pct", 80)},
        "totals": result.totals,
        "flagged_lines": out,
        "watch_lines": [{k: _clean(r[k]) for k in _ITEM} for r in watch.to_dict("records")],
        "quality_findings": q,
        "unreconciled": quality.is_unreconciled(q),
        "reallocation_candidates": realloc.suggest(result, settings),
        "redacted": bool(redact),
    }


def facts_to_json(facts) -> str:
    """Pretty JSON, exactly what would be sent to an explainer."""
    return json.dumps(facts, indent=2, ensure_ascii=False, default=_clean)
