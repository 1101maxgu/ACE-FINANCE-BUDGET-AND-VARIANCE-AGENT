"""Explanation backends (template, paste handoff, API slot) and the number guard."""
import json
import os
import re
from decimal import Decimal

from .facts import facts_to_json
from .settings import ROOT

PROMPT_PATH = ROOT / "prompts" / "explain_system.md"
STATUSES = ("on_track", "watch", "off_track")
CAUSE_LABELS = ("supported", "unknown", "answered")
_KEYS = ("headline", "status", "top_issues", "decisions_needed", "reallocation_suggestions")


class NotConfigured(Exception):
    """The Anthropic API backend has no key yet."""


def build_prompt(facts) -> str:
    """Exactly what gets pasted into Claude: system rules + facts.json."""
    return f"{PROMPT_PATH.read_text(encoding='utf-8')}\n\nFACTS:\n```json\n{facts_to_json(facts)}\n```\n"


class ExplainError(Exception):
    """The API reply could not be used (unreadable, or numbers not in the facts)."""


def explain_api(facts, settings=None, client=None) -> dict:
    """Ask Claude via the API. Raises NotConfigured when there is no ANTHROPIC_API_KEY (read from the
    environment or a local .env); raises ExplainError if the reply fails parsing or the number guard.
    `client` is for tests (any object with .messages.create)."""
    if client is None:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
        key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        if not key:
            raise NotConfigured("The Claude API is not set up yet. Add ANTHROPIC_API_KEY to the local .env file "
                                "(it is never stored in the shared folder), or use Template or Paste mode.")
        import anthropic
        client = anthropic.Anthropic(api_key=key)
    model = (settings or {}).get("api_model", "claude-sonnet-5-5")
    msg = client.messages.create(model=model, max_tokens=2000,
                                 messages=[{"role": "user", "content": build_prompt(facts)}])
    d, problems = parse_pasted_reply("".join(b.text for b in msg.content if getattr(b, "text", None)), facts)
    if d is None or problems:
        raise ExplainError("Claude's reply could not be used: " + " ".join(problems))
    return d


# ---------- template backend ----------

def _usd(cents):
    c = abs(int(cents))
    return f"${c // 100:,}.{c % 100:02d}"


def _issue(ln):
    over = ln["variance_cents"] > 0
    if ln["type"] == "revenue":
        how = "above target" if over else "below target"
    else:
        how = "over budget" if over else "under budget"
    pct = f" ({abs(ln['variance_pct'])}%)" if ln["variance_pct"] is not None else " (no budget was set)"
    who = ln["owner"] or "the report runner"
    detail = f"Budget {_usd(ln['budget_cents'])}, actual {_usd(ln['actual_cents'])}."
    if ln.get("projection_cents") is not None:
        detail += (f" At the current pace the line would end at {_usd(ln['projection_cents'])} "
                   f"({ln['projection_confidence']} confidence).")
    tags = ln.get("tags") or []
    notes = ln.get("coordinator_notes") or []
    cur = [n for n in notes if n["state"] == "current"]
    if cur:
        cause, q = {"label": "answered", "text": f"{cur[-1]['author']} ({cur[-1]['date']}): {cur[-1]['text']}"}, ""
    elif notes:
        cause = {"label": "unknown", "text": "There are new transactions since the last note."}
        q = f"{who}: new transactions arrived on {ln['line_name']} since {notes[-1]['author']}'s note. Does it still hold?"
    elif "one_time_spike" in tags:
        cause = {"label": "supported", "text": "One large one-time transaction accounts for most of the difference (tag one_time_spike)."}
        q = ""
    elif "recurring" in tags:
        cause = {"label": "supported", "text": "The same vendor charges repeatedly on this line (tag recurring)."}
        q = ""
    else:
        cause = {"label": "unknown", "text": "The cause is not known from the data."}
        q = f"{who}: what drove the difference on {ln['line_name']}?"
    return {
        "line_id": ln["line_id"],
        "title": f"{ln['line_name']} is {_usd(ln['variance_cents'])} {how}{pct}",
        "detail": detail, "cause": cause, "question": q,
    }


def explain_template(facts) -> dict:
    """Rule-based explanation in the PRD schema. Every cause is 'unknown' with a question."""
    t, fl = facts["totals"], facts["flagged_lines"]
    bad = [x for x in fl if x["status"] == "unfavorable"]
    status = "off_track" if bad else ("watch" if fl else "on_track")
    net = t["net_variance_cents"]
    head = {"on_track": "On track", "watch": "Watch", "off_track": "Off track"}[status]
    label = facts["period"].get("label")
    headline = (f"{'UNRECONCILED. ' if facts.get('unreconciled') else ''}"
                f"{head}{' for ' + label if label else ''}: {t['flagged_count']} of {t['line_count']} lines flagged; "
                f"net result is {_usd(net)} {'better' if net >= 0 else 'worse'} than budget.")
    issues = [_issue(x) for x in fl[:5]]
    realloc = [f"Move {_usd(r['amount_cents'])} from {r['from_name']} to {r['to_name']} (for approval; advice only)."
               for r in facts.get("reallocation_candidates", [])]
    return {"headline": headline, "status": status, "top_issues": issues,
            "decisions_needed": [i["question"] for i in issues if i["question"]],
            "reallocation_suggestions": realloc}


# ---------- number guard ----------

_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _numbers(text):
    out = []
    for m in _NUM.finditer(text):
        s = m.group().rstrip(",").replace(",", "")
        out.append((m.group(), Decimal(s)))
    return out


def _leaves(x, key=""):
    if isinstance(x, dict):
        for k, v in x.items():
            yield from _leaves(v, k)
    elif isinstance(x, list):
        yield len(x), "__len__"
        for v in x:
            yield from _leaves(v, key)
    else:
        yield x, key


def _strings(x):
    if isinstance(x, dict):
        for v in x.values():
            yield from _strings(v)
    elif isinstance(x, list):
        for v in x:
            yield from _strings(v)
    elif isinstance(x, str):
        yield x


def _allowed(facts):
    ok = set()
    for v, key in _leaves(facts):
        if isinstance(v, bool) or v is None:
            continue
        if isinstance(v, str):
            ok.update(d for _, d in _numbers(v))
        elif isinstance(v, (int, float)):
            d = abs(Decimal(str(v)))
            if key.endswith("_cents"):
                d = d / 100
                ok.add(d.quantize(Decimal(1)))  # whole-dollar rounding
            elif isinstance(v, float):
                ok.add(d.quantize(Decimal("0.1")))
                ok.add(d.quantize(Decimal(1)))
            ok.add(abs(d))
    return ok


def number_guard(text_or_dict, facts) -> list:
    """Numbers in the text (or any string inside the dict) that are not in facts. Empty list = OK.
    Allowed: any number in facts (cents shown as dollars, whole-dollar rounding, percentages),
    numbers inside fact strings (dates, ids, names), and list lengths."""
    ok = _allowed(facts)
    texts = [text_or_dict] if isinstance(text_or_dict, str) else list(_strings(text_or_dict))
    bad = []
    for t in texts:
        for raw, d in _numbers(t):
            if d not in ok and raw not in bad:
                bad.append(raw)
    return bad


# ---------- paste handoff ----------

def parse_pasted_reply(text, facts):
    """Parse Claude's pasted reply. Returns (dict or None, problems).
    None only when no usable JSON in the schema was found; otherwise the dict is returned together
    with any problems (bad cause labels, numbers not in facts) so the UI can highlight them."""
    s = text.strip()
    s = re.sub(r"^```(?:json)?\s*|\s*```$", "", s)
    try:
        d = json.loads(s)
    except ValueError:
        a, b = s.find("{"), s.rfind("}")
        try:
            d = json.loads(s[a:b + 1]) if a >= 0 and b > a else None
        except ValueError:
            d = None
    if not isinstance(d, dict):
        return None, ["I couldn't find a JSON reply in what was pasted. Paste Claude's whole answer."]
    missing = [k for k in _KEYS if k not in d]
    if missing:
        return None, [f"The reply is missing: {', '.join(missing)}."]
    problems = []
    if d["status"] not in STATUSES:
        problems.append(f"Status must be one of: {', '.join(STATUSES)}.")
    for i, it in enumerate(d["top_issues"], 1):
        label = (it.get("cause") or {}).get("label") if isinstance(it, dict) else None
        if label not in CAUSE_LABELS:
            problems.append(f"Issue {i} has no valid cause label (supported / unknown / answered).")
    problems += [f"Number not in the computed facts: {n}" for n in number_guard(d, facts)]
    return d, problems
