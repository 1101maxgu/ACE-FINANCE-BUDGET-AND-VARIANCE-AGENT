"""Outbound drafts, the question loop ([ACE-Q-###]) and export intake. Drafts only; a person sends.

Questions: one JSON file per author in <data_dir>/questions/. Status flow:
open -> drafted (email draft created) -> reply_received (reply fetched, NOT yet trusted) -> answered (a person
saved it as a note) | back to drafted when a reply is ignored. Reply text is untrusted data.
"""
import json
import re
from datetime import date as _date
from pathlib import Path

from . import gmail, notes
from .settings import data_dir

_TAG = re.compile(r"\[ACE-Q-(\d{3,})\]")


def _dir(settings):
    d = data_dir(settings) / "questions"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _all(settings):
    d = data_dir(settings) / "questions"
    return [(f, json.loads(f.read_text(encoding="utf-8"))) for f in sorted(d.glob("*.json"))] if d.exists() else []


def list_questions(settings, status=None) -> list:
    """All questions from all authors, oldest first; optionally only one status."""
    out = [q for _, qs in _all(settings) for q in qs]
    out = [q for q in out if status is None or q["status"] == status]
    return sorted(out, key=lambda q: q["qid"])


def _update(settings, qid, **changes) -> dict:
    for f, qs in _all(settings):
        for q in qs:
            if q["qid"] == qid:
                q.update(changes)
                f.write_text(json.dumps(qs, indent=2), encoding="utf-8")
                return q
    raise KeyError(f"No question {qid}")


def create_questions(settings, author, profile, facts, explanation, date=None) -> list:
    """Turn the unknown-cause questions of an explanation into stored questions with ids ACE-Q-###.
    Goes to the line owner, else the report runner. Skips a line that already has an unanswered question
    for the same profile and period."""
    if not author.strip():
        raise ValueError("Please enter your name.")
    existing = list_questions(settings)
    n = max([int(q["qid"].split("-")[-1]) for q in existing] or [0])
    label = facts["period"]["label"]
    owners = {x["line_id"]: x["owner"] for x in facts["flagged_lines"]}
    names = {x["line_id"]: x["line_name"] for x in facts["flagged_lines"]}
    made = []
    for it in explanation.get("top_issues", []):
        if not isinstance(it, dict) or not it.get("question"):
            continue
        lid = it.get("line_id", "")
        if any(q["line_id"] == lid and q["profile"] == profile and q["period"] == label and q["status"] != "answered"
               for q in existing + made):
            continue
        n += 1
        owner = owners.get(lid, "")
        to = (settings.get("owner_emails") or {}).get(owner) if owner else None
        made.append({"qid": f"ACE-Q-{n:03d}", "profile": profile, "period": label, "line_id": lid,
                     "line_name": names.get(lid, lid), "text": it["question"], "owner": owner or "report runner",
                     "to_email": to or settings.get("runner_email", ""), "status": "open", "author": author.strip(),
                     "created": str(date or _date.today().isoformat()), "replies": []})
    if made:
        f = _dir(settings) / (re.sub(r"[^\w.-]", "_", author.strip()) + ".json")
        old = json.loads(f.read_text(encoding="utf-8")) if f.exists() else []
        f.write_text(json.dumps(old + made, indent=2), encoding="utf-8")
    return made


def draft_questions(client, settings, questions=None) -> list:
    """Create one Gmail DRAFT per open question (subject carries the [ACE-Q-###] tag). Returns draft ids."""
    ids = []
    for q in questions if questions is not None else list_questions(settings, "open"):
        body = (f"Hi {q['owner']},\n\nA quick question about {q['line_name']} ({q['period']}):\n\n{q['text']}\n\n"
                f"Please just reply to this email and keep the subject line as is.\n\nThanks")
        ids.append(gmail.make_draft(client, q["to_email"], f"[{q['qid']}] {q['line_name']}: question", body))
        _update(settings, q["qid"], status="drafted")
    return ids


def _clean_reply(text):
    keep = []
    for ln in text.splitlines():
        if re.match(r"^\s*On .+wrote:\s*$", ln) or ln.strip().startswith("-----Original"):
            break
        if not ln.lstrip().startswith(">"):
            keep.append(ln)
    return "\n".join(keep).strip()


def collect_replies(client, settings, label=None) -> list:
    """Fetch replies tagged [ACE-Q-###] from the chosen question label. They wait for review; nothing becomes a
    note automatically. Returns the new replies [{qid, msg_id, from, date, text}]."""
    label = label or (settings.get("gmail") or {}).get("question_label")
    known = {q["qid"]: q for q in list_questions(settings)}
    new = []
    for m in gmail.read_label(client, settings, label):
        t = _TAG.search(m.get("subject", ""))
        qid = f"ACE-Q-{t.group(1)}" if t else None
        if qid not in known or any(r["msg_id"] == m["id"] for r in known[qid]["replies"]):
            continue
        rep = {"qid": qid, "msg_id": m["id"], "from": m.get("from", ""), "date": m.get("date", ""),
               "text": _clean_reply(m.get("body_text", "")), "state": "pending"}
        _update(settings, qid, replies=known[qid]["replies"] + [rep], status="reply_received")
        known[qid]["replies"].append(rep)
        new.append(rep)
    return new


def answer_question(settings, qid, author, text, txn_ids, date=None) -> dict:
    """A person answers (typed, or accepting a reply) -> saved as a coordinator note and the question closes."""
    q = next(x for x in list_questions(settings) if x["qid"] == qid)
    note = notes.add_note(settings, author, q["profile"], q["line_id"], q["period"], txn_ids, text, date=date)
    _update(settings, qid, status="answered")
    return note


def review_reply(settings, qid, msg_id, action, reviewer, txn_ids=(), date=None, edited_text=None):
    """action 'save_as_note' (-> answer_question, returns the note) or 'ignore' (question goes back to 'drafted')."""
    q = next(x for x in list_questions(settings) if x["qid"] == qid)
    rep = next(r for r in q["replies"] if r["msg_id"] == msg_id)
    if action == "save_as_note":
        note = answer_question(settings, qid, reviewer, edited_text or rep["text"], txn_ids, date)
        rep["state"] = "saved"
        _update(settings, qid, replies=q["replies"])
        return note
    if action == "ignore":
        rep["state"] = "ignored"
        _update(settings, qid, replies=q["replies"], status="drafted")
        return None
    raise ValueError("action must be 'save_as_note' or 'ignore'")


def draft_report(client, settings, paths, subject, body, to=None) -> str:
    """Draft an email with report files attached (user sends it). `to` defaults to settings['runner_email']."""
    atts = [{"filename": Path(p).name, "mime": "application/pdf" if str(p).lower().endswith(".pdf")
             else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "data": Path(p).read_bytes()}
            for p in paths]
    return gmail.make_draft(client, to or settings.get("runner_email", ""), subject, body, atts)


def export_intake(client, settings, label=None):
    """Context manager: attachments (.csv/.xlsx) of the chosen export label in a temp folder (deleted on exit).
    Yields [{id, subject, from, date, files:[Path]}]; read them with ingest.preview/load_* inside the block."""
    label = label or (settings.get("gmail") or {}).get("export_label")
    return gmail.fetched(client, settings, label, exts=(".csv", ".xlsx", ".xlsm"))
