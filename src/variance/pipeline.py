"""Single entry point: files + settings + profile -> result and facts. Never reads the clock."""
from . import facts as F
from .calc import compute
from .ingest import load_actuals, load_budget
from .settings import save_settings


def run(budget_file, actuals_file, settings, profile, as_of_date=None, redact=False, stated_total_cents=None,
        notes=None, committed=None, intentional_dupes=(), settings_path=None, remember=False) -> dict:
    """Run a full comparison. Returns {'result', 'facts', 'budget', 'actuals'}.

    settings['period'] = {label, start, end} is REQUIRED (never auto-detected) -> ValueError if blank.
    as_of_date defaults to the period end (explicit input, not the clock).
    profile: a saved profile {budget, actuals, category_map} (see mapping.load_profiles()).
    remember=True saves the period as settings['last_period'] (to settings_path or the default file).
    """
    from . import quality  # local import: quality needs calc results
    period = {k: str((settings.get("period") or {}).get(k) or "") for k in ("label", "start", "end")}
    missing = [k for k in period if not period[k]]
    if missing:
        raise ValueError("Please enter the report period (" + ", ".join(missing) + " is missing).")
    settings = {**settings, "period": period}
    b = load_budget(budget_file, profile)
    a = load_actuals(actuals_file, profile)
    r = compute(b, a, profile.get("category_map") or {}, settings, as_of_date or period["end"], committed=committed)
    r.quality = quality.run_checks(b, a, r, settings, stated_total_cents, intentional_dupes)
    if remember:
        save_settings({**settings, "last_period": dict(period)}, settings_path)
    return {"result": r, "facts": F.build_facts(r, settings, redact, notes=notes), "budget": b, "actuals": a}
