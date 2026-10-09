"""Gmail behind a small client interface.

Rules: OAuth scopes are read-only + compose; only labels chosen in settings['gmail']['labels'] are read;
the app only creates DRAFTS (send_message exists for a human-clicked, allow-listed send and is never called
by this package); the token lives outside the shared folder; email content is untrusted DATA - it is never put
into prompts or treated as instructions. Tests use InMemoryGmailClient; nothing here touches the network
unless GoogleGmailClient is built by connect()/load_client().
"""
import base64
import re
import tempfile
from contextlib import contextmanager
from email.message import EmailMessage
from pathlib import Path

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly", "https://www.googleapis.com/auth/gmail.compose"]
LOCAL_DIR = Path.home() / ".ace-variance"


class GmailNotConnected(Exception):
    """Plain-language message about what to do to connect."""


class NotAllowed(Exception):
    """Blocked by the label list or the send allow-list."""


class GmailClient:
    """Interface. Message dict: {id, subject, from, date, body_text, attachments:[{filename, mime, data(bytes)}]}."""

    def account(self) -> str: raise NotImplementedError
    def list_labels(self) -> list: raise NotImplementedError          # [{id, name}]
    def list_messages(self, label_name) -> list: raise NotImplementedError   # [{id, subject, from, date}]
    def get_message(self, msg_id) -> dict: raise NotImplementedError
    def create_draft(self, to, subject, body, attachments=()) -> str: raise NotImplementedError
    def send_message(self, to, subject, body, attachments=()) -> str: raise NotImplementedError


class InMemoryGmailClient(GmailClient):
    """Fake client for tests and demos. messages = {label_name: [message dict, ...]}."""

    def __init__(self, messages=None, account="me@example.org"):
        self.messages, self._account = messages or {}, account
        self.drafts, self.sent, self.reads = [], [], []

    def account(self): return self._account
    def list_labels(self): return [{"id": n, "name": n} for n in self.messages]

    def list_messages(self, label_name):
        self.reads.append(label_name)
        return [{k: m.get(k, "") for k in ("id", "subject", "from", "date")} for m in self.messages.get(label_name, [])]

    def get_message(self, msg_id):
        for ms in self.messages.values():
            for m in ms:
                if m["id"] == msg_id:
                    return {"body_text": "", "attachments": [], **m}
        raise KeyError(msg_id)

    def create_draft(self, to, subject, body, attachments=()):
        self.drafts.append({"to": to, "subject": subject, "body": body, "attachments": list(attachments)})
        return f"draft-{len(self.drafts)}"

    def send_message(self, to, subject, body, attachments=()):
        self.sent.append({"to": to, "subject": subject, "body": body, "attachments": list(attachments)})
        return f"sent-{len(self.sent)}"


# ---------- real client (needs the network and an OAuth token) ----------

def _mime(to, subject, body, attachments):
    m = EmailMessage()
    m["To"], m["Subject"] = to, subject
    m.set_content(body)
    for a in attachments:  # {filename, mime, data}
        mt, _, st = (a.get("mime") or "application/octet-stream").partition("/")
        m.add_attachment(a["data"], maintype=mt, subtype=st or "octet-stream", filename=a["filename"])
    return {"raw": base64.urlsafe_b64encode(m.as_bytes()).decode()}


class GoogleGmailClient(GmailClient):
    def __init__(self, creds):
        from googleapiclient.discovery import build
        self.svc = build("gmail", "v1", credentials=creds, cache_discovery=False)

    def account(self):
        return self.svc.users().getProfile(userId="me").execute().get("emailAddress", "")

    def list_labels(self):
        return [{"id": x["id"], "name": x["name"]} for x in self.svc.users().labels().list(userId="me").execute()["labels"]]

    def list_messages(self, label_name):
        ids = [x["id"] for x in self.list_labels() if x["name"] == label_name]
        if not ids:
            raise NotAllowed(f"Label '{label_name}' does not exist in this mailbox.")
        r = self.svc.users().messages().list(userId="me", labelIds=ids, maxResults=100).execute()
        out = []
        for m in r.get("messages", []):
            h = self.svc.users().messages().get(userId="me", id=m["id"], format="metadata",
                                                metadataHeaders=["Subject", "From", "Date"]).execute()
            hd = {x["name"].lower(): x["value"] for x in h["payload"]["headers"]}
            out.append({"id": m["id"], "subject": hd.get("subject", ""), "from": hd.get("from", ""), "date": hd.get("date", "")})
        return out

    def get_message(self, msg_id):
        m = self.svc.users().messages().get(userId="me", id=msg_id, format="full").execute()
        hd = {x["name"].lower(): x["value"] for x in m["payload"]["headers"]}
        body, atts = [], []

        def walk(p):
            if p.get("filename"):
                aid = p["body"].get("attachmentId")
                data = (self.svc.users().messages().attachments().get(userId="me", messageId=msg_id, id=aid).execute()["data"]
                        if aid else p["body"].get("data", ""))
                atts.append({"filename": p["filename"], "mime": p.get("mimeType", ""),
                             "data": base64.urlsafe_b64decode(data + "==")})
            elif p.get("mimeType") == "text/plain" and p["body"].get("data"):
                body.append(base64.urlsafe_b64decode(p["body"]["data"] + "==").decode("utf-8", "replace"))
            for c in p.get("parts", []):
                walk(c)

        walk(m["payload"])
        return {"id": msg_id, "subject": hd.get("subject", ""), "from": hd.get("from", ""), "date": hd.get("date", ""),
                "body_text": "\n".join(body), "attachments": atts}

    def create_draft(self, to, subject, body, attachments=()):
        return self.svc.users().drafts().create(userId="me", body={"message": _mime(to, subject, body, attachments)}).execute()["id"]

    def send_message(self, to, subject, body, attachments=()):
        return self.svc.users().messages().send(userId="me", body=_mime(to, subject, body, attachments)).execute()["id"]


# ---------- connection / token ----------

def _paths(settings):
    g = (settings or {}).get("gmail", {})
    cred = Path(g.get("credentials_path") or LOCAL_DIR / "credentials.json")
    tok = Path(g.get("token_path") or LOCAL_DIR / "gmail_token.json")
    sf = (settings or {}).get("shared_folder")
    if sf:
        for p in (cred, tok):
            try:
                p.resolve().relative_to(Path(sf).resolve())
            except ValueError:
                continue
            raise ValueError(f"The Gmail token/credentials file must not be inside the shared folder ({p}).")
    return cred, tok


HELP_ADMIN = ("Google blocked the sign-in. If this is a work or school account, your Google admin may not allow "
              "apps like this one. Ask the admin to allow it, or use the shared ACE mailbox or a personal Gmail account instead.")


def connect(settings) -> GoogleGmailClient:
    """Run the one-time browser sign-in (OAuth) and save the token locally. Not used in tests."""
    cred, tok = _paths(settings)
    if not cred.exists():
        raise GmailNotConnected(
            f"Missing the Google app file ({cred}). One person needs to create a free 'OAuth desktop app' in Google Cloud "
            "Console (Gmail API enabled, scopes: read-only + compose), download its JSON and save it at that path. "
            "If your Google account cannot create one, try a personal Gmail account.")
    from google_auth_oauthlib.flow import InstalledAppFlow
    try:
        creds = InstalledAppFlow.from_client_secrets_file(str(cred), SCOPES).run_local_server(port=0)
    except Exception as e:  # noqa: BLE001 - turn any OAuth failure into plain language
        s = str(e).lower()
        raise GmailNotConnected(HELP_ADMIN if ("access_denied" in s or "admin" in s or "policy" in s)
                                else f"Sign-in did not finish: {e}")
    tok.parent.mkdir(parents=True, exist_ok=True)
    tok.write_text(creds.to_json(), encoding="utf-8")
    return GoogleGmailClient(creds)


def load_client(settings) -> GoogleGmailClient:
    """Client from the saved token (refreshing it if needed)."""
    _, tok = _paths(settings)
    if not tok.exists():
        raise GmailNotConnected("Gmail is not connected yet. Click 'Connect Gmail' and sign in.")
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    creds = Credentials.from_authorized_user_file(str(tok), SCOPES)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception:  # noqa: BLE001
                raise GmailNotConnected("The Gmail sign-in expired. Click 'Connect Gmail' to sign in again.")
            tok.write_text(creds.to_json(), encoding="utf-8")
        else:
            raise GmailNotConnected("The Gmail sign-in is no longer valid. Click 'Connect Gmail' to sign in again.")
    return GoogleGmailClient(creds)


def status(settings, client=None) -> dict:
    """{'connected': bool, 'account': str, 'problem': str} - for the status indicator. Pass a client to skip the token."""
    try:
        c = client or load_client(settings)
        return {"connected": True, "account": c.account(), "problem": ""}
    except GmailNotConnected as e:
        return {"connected": False, "account": "", "problem": str(e)}
    except Exception as e:  # noqa: BLE001
        return {"connected": False, "account": "", "problem": f"Could not reach Gmail: {e}"}


def disconnect(settings) -> bool:
    """Delete the local token."""
    _, tok = _paths(settings)
    existed = tok.exists()
    if existed:
        tok.unlink()
    return existed


# ---------- reading (chosen labels only) ----------

def chosen_labels(settings) -> list:
    return list((settings.get("gmail") or {}).get("labels") or [])


def list_labels(client) -> list:
    """All label names in the mailbox (for the label picker)."""
    return sorted(x["name"] for x in client.list_labels())


def read_label(client, settings, label_name, with_content=True) -> list:
    """Messages under ONE chosen label. Other labels raise NotAllowed. Every message carries
    untrusted=True: treat it as data, never as instructions."""
    if label_name not in chosen_labels(settings):
        raise NotAllowed(f"'{label_name}' is not one of the labels you chose, so it will not be read.")
    out = []
    for m in client.list_messages(label_name):
        full = client.get_message(m["id"]) if with_content else dict(m)
        out.append({**full, "untrusted": True, "label": label_name})
    return out


@contextmanager
def fetched(client, settings, label_name, exts=None):
    """Download a label's attachments into a temp folder that is deleted afterwards.
    Yields [{id, subject, from, date, body_text, files: [Path, ...]}]."""
    with tempfile.TemporaryDirectory(prefix="ace_mail_") as d:
        out = []
        for m in read_label(client, settings, label_name):
            files = []
            for i, a in enumerate(m.get("attachments", [])):
                name = re.sub(r"[^\w.\- ]", "_", Path(a["filename"]).name) or f"file{i}"
                if exts and Path(name).suffix.lower() not in exts:
                    continue
                p = Path(d) / m["id"] / name
                p.parent.mkdir(exist_ok=True)
                p.write_bytes(a["data"])
                files.append(p)
            out.append({**{k: v for k, v in m.items() if k != "attachments"}, "files": files})
        yield out


# ---------- writing ----------

def make_draft(client, to, subject, body, attachments=()) -> str:
    """Create a Gmail DRAFT (the user opens Gmail and presses Send). Returns the draft id."""
    return client.create_draft(to, subject, body, attachments)


def send_if_allowed(client, settings, to, subject, body, attachments=()) -> str:
    """Send only when EVERY recipient is on settings['gmail']['allow_list']. For a human-clicked action
    or an allow-listed recipient; this package never calls it on its own."""
    allow = {a.strip().lower() for a in (settings.get("gmail") or {}).get("allow_list") or []}
    rcpt = [a.strip().lower() for a in re.split(r"[;,]", to) if a.strip()]
    if not rcpt or not all(a in allow for a in rcpt):
        raise NotAllowed("That address is not on the send allow-list. Create a draft instead and send it yourself.")
    return client.send_message(to, subject, body, attachments)
