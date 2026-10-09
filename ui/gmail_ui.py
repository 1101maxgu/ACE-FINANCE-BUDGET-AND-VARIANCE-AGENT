"""Steps 10 and 14: Gmail connect, outbound drafts (explicit send), reply inbox, import from email."""
import streamlit as st

from variance import emailing, gmail
from variance.settings import save_settings
from .common import Mem, author, invalidate, label_of, next_button

HELP = """**If sign-in does not work**
- *"This app is blocked" / "access denied"*: your Google account belongs to a work or school that does not allow
  outside apps. Ask your Google admin to allow it, or use the shared ACE mailbox or a personal Gmail account.
- *"Missing the Google app file"*: one person must create a free "OAuth desktop app" in Google Cloud Console
  (Gmail API on, scopes read-only + compose), download the JSON and save it where the message says.
- *Sign-in expired*: just press Connect Gmail again.
- The sign-in token is stored only on this computer, never in the shared folder."""


def get_client():
    """The Gmail client for this session (a saved token), or None. Tests put a fake one in session state."""
    ss = st.session_state
    if ss.get("gmail_client") is not None:
        return ss.gmail_client
    try:
        ss.gmail_client = gmail.load_client(ss.settings)
    except gmail.GmailNotConnected as e:
        ss.gmail_problem = str(e)
    except Exception as e:  # missing google libraries, network
        ss.gmail_problem = f"Could not reach Gmail: {e}"
    return ss.get("gmail_client")


def _connection(c):
    ss = st.session_state
    s = ss.settings
    g = s.setdefault("gmail", {})
    stt = gmail.status(s, c) if c else {"connected": False, "account": "", "problem": ss.get("gmail_problem", "")}
    if stt["connected"]:
        st.success(f"Connected as {stt['account']}")
    else:
        st.error("Not connected")
        if stt["problem"]:
            st.info(stt["problem"])
    c1, c2 = st.columns(2)
    if c1.button("Connect Gmail", help="Opens a Google sign-in page in your browser."):
        try:
            ss.gmail_client = gmail.connect(s)
            ss.pop("gmail_problem", None)
            st.rerun()
        except (gmail.GmailNotConnected, ValueError) as e:
            st.error(str(e))
    if stt["connected"] and c2.button("Disconnect (delete local sign-in)"):
        gmail.disconnect(s)
        ss.gmail_client = None
        st.rerun()
    with st.expander("Account problems? Read this"):
        st.markdown(HELP)
    if not c:
        return
    st.subheader("Labels the app may read")
    st.caption("Only the labels you tick here are ever read. Everything else in the mailbox is off limits.")
    labels = gmail.list_labels(c)
    chosen = st.multiselect("Allowed labels", labels, default=[x for x in g.get("labels", []) if x in labels])
    roles = {"question_label": "Replies to questions", "export_label": "Budget/actuals exports",
             "reimbursement_label": "Reimbursement claims"}
    cols = st.columns(3)
    picks = {}
    for col, (k, lab) in zip(cols, roles.items()):
        opts = [""] + chosen
        picks[k] = col.selectbox(lab, opts, index=opts.index(g.get(k)) if g.get(k) in opts else 0, key=f"role_{k}")
    allow = st.text_input("Addresses that may be sent to directly (comma separated, optional)",
                          value=", ".join(g.get("allow_list", [])),
                          help="Leave empty: you always send from Gmail yourself.")
    runner = st.text_input("Report runner email (gets questions with no line owner)", value=s.get("runner_email", ""))
    if st.button("Save Gmail settings"):
        g.update(labels=chosen, allow_list=[a.strip() for a in allow.split(",") if a.strip()], **picks)
        s["runner_email"] = runner.strip()
        save_settings(s)
        st.success("Saved.")


def _preview(to, subject, body, atts):
    with st.container(border=True):
        st.markdown(f"**To:** {to or '(nobody yet)'}  \n**Subject:** {subject}  \n**Attachments:** {', '.join(atts) or 'none'}")
        st.text(body)


def _question_body(q):
    return (f"Hi {q['owner']},\n\nA quick question about {q['line_name']} ({q['period']}):\n\n{q['text']}\n\n"
            f"Please just reply to this email and keep the subject line as is.\n\nThanks")


def _drafts(c):
    ss = st.session_state
    s = ss.settings
    st.subheader("Report email")
    files = ss.get("report_files")
    if not files:
        st.info("Make the reports on the Report screen first, then come back to draft the email.")
    else:
        label = label_of(s)
        to = st.text_input("To", value=s.get("runner_email", ""), key="rep_to")
        subject = st.text_input("Subject", value=f"Budget & Variance report: {label}", key="rep_subj")
        body = st.text_area("Message", value=f"Hi,\n\nThe {label} variance report is attached "
                                              "(generated, not audited).\n\nThanks", key="rep_body")
        names = [f.name for f in files.values()]
        st.write("**This is exactly what will be created:**")
        _preview(to, subject, body, names)
        if st.button("Create Gmail draft (you send it from Gmail)", type="primary", disabled=not to.strip()):
            try:
                emailing.draft_report(c, s, list(files.values()), subject, body, to)
                st.success("Draft created in Gmail. Open Gmail to review and press Send.")
            except Exception as e:
                st.error(f"Could not create the draft: {e}")
        allow = {a.lower() for a in s.get("gmail", {}).get("allow_list", [])}
        if allow and to.strip() and all(a.strip().lower() in allow for a in to.split(",")):
            ok = st.checkbox("I have read this email and want to send it now", key="rep_ok")
            if st.button("Send now", disabled=not ok):
                try:
                    gmail.send_if_allowed(c, s, to, subject, body, [
                        {"filename": f.name, "mime": "application/octet-stream", "data": f.read_bytes()}
                        for f in files.values()])
                    st.success("Sent.")
                except gmail.NotAllowed as e:
                    st.error(str(e))
    st.subheader("Questions to owners")
    if ss.result is None or not ss.explanation:
        st.info("Choose an explanation on the Check screen first. Its unknown-cause questions can become emails.")
    elif st.button("Create tracked questions from this explanation", disabled=not author()):
        from .common import get_facts
        made = emailing.create_questions(s, author(), ss.profile or "", get_facts(), ss.explanation)
        st.success(f"{len(made)} new question(s).")
    open_q = emailing.list_questions(s, "open")
    if not open_q:
        st.caption("No open questions waiting for an email draft.")
    for q in open_q:
        _preview(q["to_email"], f"[{q['qid']}] {q['line_name']}: question", _question_body(q), [])
        if not q["to_email"]:
            st.warning("No email address for this owner. Add it under owner_emails in settings, or set the "
                       "report runner email.")
    if open_q and st.button("Create Gmail drafts for these questions", type="primary"):
        try:
            ids = emailing.draft_questions(c, s, open_q)
            st.success(f"{len(ids)} draft(s) created. Open Gmail to send them.")
            st.rerun()
        except Exception as e:
            st.error(f"Could not create drafts: {e}")


def _inbox(c):
    ss = st.session_state
    s = ss.settings
    st.write("Replies are fetched as plain text for you to read. Nothing becomes a note until you save it.")
    if st.button("Check for replies"):
        try:
            new = emailing.collect_replies(c, s)
            st.success(f"{len(new)} new reply(ies).")
        except gmail.NotAllowed as e:
            st.error(str(e))
        except Exception as e:
            st.error(f"Could not read replies: {e}")
    pending = [(q, r) for q in emailing.list_questions(s) for r in q["replies"] if r["state"] == "pending"]
    if not pending:
        st.caption("No replies waiting for review.")
    for q, r in pending:
        with st.container(border=True):
            st.markdown(f"**{q['qid']}** about {q['line_name']} - from {r['from']} ({r['date']})")
            st.caption("Email content is data from outside. Read it before saving.")
            txt = st.text_area("Reply text (you can edit before saving)", value=r["text"], key=f"rt_{r['msg_id']}")
            c1, c2 = st.columns(2)
            ids = list(ss.result.txns[ss.result.txns.line_id == q["line_id"]].txn_id) if ss.result is not None else []
            if c1.button("Save as note", key=f"sv_{r['msg_id']}", disabled=not author()):
                emailing.review_reply(s, q["qid"], r["msg_id"], "save_as_note", author(), ids, edited_text=txt)
                st.rerun()
            if c2.button("Ignore", key=f"ig_{r['msg_id']}"):
                emailing.review_reply(s, q["qid"], r["msg_id"], "ignore", author())
                st.rerun()


def _import(c):
    ss = st.session_state
    s = ss.settings
    st.write("Pull an export that was emailed to the chosen export label straight into the mapping step.")
    label = s.get("gmail", {}).get("export_label")
    if not label:
        st.info("Pick an export label on the Connection tab first.")
        return
    try:
        with emailing.export_intake(c, s) as msgs:
            if not msgs:
                st.caption("No messages under that label.")
            for m in msgs:
                st.markdown(f"**{m['subject']}** from {m['from']} ({m['date']})")
                for f in m["files"]:
                    c1, c2 = st.columns(2)
                    for col, kind in ((c1, "budget"), (c2, "actuals")):
                        if col.button(f"Use {f.name} as {kind}", key=f"imp_{kind}_{m['id']}_{f.name}"):
                            ss.files[kind] = Mem(f.name, f.read_bytes())  # copied into memory; temp folder is deleted
                            ss.cfg.pop(kind, None)
                            ss.maps.pop(kind, None)
                            invalidate("budget_df", "actuals_df", "cat_map", "result", "explanation")
                            st.success(f"{f.name} loaded as the {kind} file.")
                            next_button("Go to Upload", "1. Upload")
    except gmail.NotAllowed as e:
        st.error(str(e))
    except Exception as e:
        st.error(f"Could not read the export label: {e}")


def render():
    st.title("Email")
    st.write("Gmail is optional. The app only reads labels you choose, and it only creates drafts: "
             "you press Send yourself.")
    c = get_client()
    t = st.tabs(["Connection", "Drafts", "Reply inbox", "Import from email"])
    with t[0]:
        _connection(c)
    for tab, fn in zip(t[1:], (_drafts, _inbox, _import)):
        with tab:
            if c is None:
                st.info("Connect Gmail on the first tab to use this.")
            else:
                fn(c)
