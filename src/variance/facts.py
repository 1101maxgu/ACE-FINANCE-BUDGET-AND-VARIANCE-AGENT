"""facts.json: the only thing the explainer ever sees. Computed numbers only, never raw files."""
import json
import math


def _clean(v):
    if isinstance(v, float) and math.isnan(v):
        return None
    if hasattr(v, "item"):
        v = v.item()
    return v


def build_facts(result, settings, redact=False) -> dict:
    """Period, thresholds, totals, flagged lines (+ top 3 transactions each), quality findings.
    redact=True leaves out transaction descriptions and vendors."""
    L = result.lines
    flagged = L[L.flagged].copy()
    flagged = flagged.reindex(flagged.variance_cents.abs().sort_values(ascending=False, kind="stable").index)
    out = []
    for r in flagged.to_dict("records"):
        item = {k: _clean(r[k]) for k in ("line_id", "category", "line_name", "type", "owner", "budget_cents",
                                          "actual_cents", "variance_cents", "variance_pct", "status", "txn_count")}
        t = result.txns[result.txns.line_id == r["line_id"]]
        t = t.reindex(t.amount_cents.abs().sort_values(ascending=False, kind="stable").index).head(3)
        item["top_transactions"] = [
            {"txn_id": x.txn_id, "date": x.date.strftime("%Y-%m-%d"), "amount_cents": int(x.amount_cents),
             **({} if redact else {"vendor": x.vendor, "description": x.description})}
            for x in t.itertuples()]
        out.append(item)
    period = dict(result.period or {})
    return {
        "period": {k: period.get(k, "") for k in ("label", "start", "end")},
        "as_of_date": result.as_of_date.isoformat(),
        "thresholds": {"flag_pct": settings.get("flag_pct", 10.0),
                       "flag_min_cents": int(settings.get("flag_min_cents", 15000))},
        "totals": result.totals,
        "flagged_lines": out,
        "quality_findings": [],  # filled by data-quality checks (Step 8)
        "redacted": bool(redact),
    }


def facts_to_json(facts) -> str:
    """Pretty JSON, exactly what would be sent to an explainer."""
    return json.dumps(facts, indent=2, ensure_ascii=False, default=_clean)
