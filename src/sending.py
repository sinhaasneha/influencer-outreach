"""Stage 5: sending layer - dedupe, approval, dry-run/live SMTP, outreach log, manual DM queue."""
import csv
import logging
import os
import re
import smtplib
import sqlite3
import ssl
import time
from datetime import datetime, timezone
from email.message import EmailMessage

log = logging.getLogger(__name__)
EMAIL_OK = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
INVALID_EMAILS = {"", "not found", "not available", "none"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS outreach (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_url TEXT UNIQUE NOT NULL,
    influencer TEXT NOT NULL,
    email TEXT,
    email_key TEXT UNIQUE,            -- lowercase email; UNIQUE => same address can never be contacted twice
    subject TEXT, body TEXT,
    message_generated INTEGER NOT NULL DEFAULT 0,
    approved INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    sent INTEGER NOT NULL DEFAULT 0,
    sent_at TEXT, error TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS dm_queue (
    profile_url TEXT PRIMARY KEY,
    influencer TEXT, instagram TEXT, message TEXT,
    status TEXT NOT NULL DEFAULT 'PENDING_MANUAL'
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class OutreachTracker:
    def __init__(self, path: str = "data/outreach.db"):
        if path != ":memory:":
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    # ---- registration ----------------------------------------------------
    def _insert(self, m: dict, status: str, email, key) -> None:
        self.db.execute(
            "INSERT INTO outreach (profile_url, influencer, email, email_key, subject, body, message_generated,"
            " status, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (m["profile_url"], m["name"], email, key, m.get("email_subject"), m.get("email_body"),
             int(m.get("message_status") == "GENERATED"), status, now_iso()))

    def register(self, m: dict) -> bool:
        """Add a generated message to the log. Idempotent: an influencer is only ever registered once."""
        if self.db.execute("SELECT 1 FROM outreach WHERE profile_url=?", (m["profile_url"],)).fetchone():
            return False
        email = (m.get("email") or "").strip()
        key, status = None, "PENDING"
        if m.get("message_status") != "GENERATED":
            status = "SKIPPED_NO_MESSAGE"
        elif email.lower() in INVALID_EMAILS:
            status, email = "SKIPPED_NO_EMAIL", None
        elif not EMAIL_OK.match(email):
            status = "SKIPPED_INVALID_EMAIL"
        else:
            key = email.lower()
        try:
            self._insert(m, status, email or None, key)
        except sqlite3.IntegrityError:  # another influencer already owns this address (e.g. shared agency inbox)
            self._insert(m, "SKIPPED_DUPLICATE_EMAIL", email, None)
        ig, dm = m.get("instagram"), m.get("instagram_dm")
        if m.get("message_status") == "GENERATED" and dm and ig and ig not in INVALID_EMAILS:
            self.db.execute("INSERT OR IGNORE INTO dm_queue (profile_url, influencer, instagram, message)"
                            " VALUES (?,?,?,?)", (m["profile_url"], m["name"], ig, dm))
        self.db.commit()
        return True

    def register_all(self, messages: list[dict]) -> int:
        return sum(self.register(m) for m in messages)

    # ---- review ------------------------------------------------------------
    def approve(self, name: str | None = None) -> int:
        q = "UPDATE outreach SET approved=1 WHERE status IN ('PENDING','SIMULATED','FAILED')"
        cur = self.db.execute(q + (" AND influencer=?" if name else ""), (name,) if name else ())
        self.db.commit()
        return cur.rowcount

    # ---- sending -----------------------------------------------------------
    def sendable(self, live: bool, require_approval: bool) -> list[sqlite3.Row]:
        statuses = "('PENDING','FAILED','SIMULATED')" if live else "('PENDING')"
        extra = " AND approved=1" if (live and require_approval) else ""
        return self.db.execute(f"SELECT * FROM outreach WHERE status IN {statuses}{extra} ORDER BY id").fetchall()

    def mark(self, row_id: int, status: str, sent: bool = False, error: str | None = None) -> None:
        self.db.execute("UPDATE outreach SET status=?, sent=?, sent_at=?, error=? WHERE id=?",
                        (status, int(sent), now_iso() if sent or status == "SIMULATED" else None, error, row_id))
        self.db.commit()

    # ---- exports -----------------------------------------------------------
    def export_tracker(self, path: str) -> int:
        rows = self.db.execute("SELECT influencer, email, message_generated, sent, sent_at, status, error"
                               " FROM outreach ORDER BY id").fetchall()
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["Influencer", "Email", "Message Generated", "Sent", "Date", "Status", "Error"])
            for r in rows:
                w.writerow([r["influencer"], r["email"] or "Not Found", "Yes" if r["message_generated"] else "No",
                            "Yes" if r["sent"] else "No", r["sent_at"] or "", r["status"], r["error"] or ""])
        return len(rows)

    def export_dm_queue(self, path: str) -> int:
        rows = self.db.execute("SELECT influencer, instagram, message, status FROM dm_queue").fetchall()
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["Influencer", "Instagram", "DM (copy-paste)", "Status"])
            for r in rows:
                w.writerow([r["influencer"], r["instagram"], r["message"], r["status"]])
        return len(rows)

    def summary(self) -> dict:
        return {r["status"]: r["n"] for r in
                self.db.execute("SELECT status, COUNT(*) n FROM outreach GROUP BY status")}


class SMTPSender:
    def __init__(self, host, port, user, password, from_addr):
        self.host, self.port, self.user, self.password, self.from_addr = host, int(port), user, password, from_addr

    @classmethod
    def from_env(cls):
        missing = [k for k in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD") if not os.getenv(k)]
        if missing:
            raise RuntimeError(f"Live sending needs {', '.join(missing)} in .env")
        return cls(os.environ["SMTP_HOST"], os.getenv("SMTP_PORT", "587"), os.environ["SMTP_USER"],
                   os.environ["SMTP_PASSWORD"], os.getenv("SMTP_FROM", os.environ["SMTP_USER"]))

    def send(self, to: str, subject: str, body: str) -> None:
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = self.from_addr, to, subject
        msg.set_content(body)
        ctx = ssl.create_default_context()
        if self.port == 465:
            with smtplib.SMTP_SSL(self.host, self.port, context=ctx, timeout=20) as s:
                s.login(self.user, self.password)
                s.send_message(msg)
        else:
            with smtplib.SMTP(self.host, self.port, timeout=20) as s:
                s.starttls(context=ctx)
                s.login(self.user, self.password)
                s.send_message(msg)


def load_suppression(path: str) -> set:
    try:
        with open(path, encoding="utf-8") as f:
            return {ln.strip().lower() for ln in f if ln.strip() and not ln.startswith("#")}
    except FileNotFoundError:
        return set()


def run_send(tracker: OutreachTracker, sender, cfg: dict, live: bool, limit: int | None = None) -> dict:
    sc = cfg["sending"]
    suppressed = load_suppression(sc["suppression_file"])
    cap = min(limit or sc["max_per_run"], sc["max_per_run"])
    stats = {"sent": 0, "simulated": 0, "failed": 0, "suppressed": 0}
    for row in tracker.sendable(live, sc["require_approval_live"])[:cap]:
        if (row["email_key"] or "") in suppressed:
            tracker.mark(row["id"], "SKIPPED_SUPPRESSED")
            stats["suppressed"] += 1
            continue
        body = row["body"] + sc["footer"]
        if not live:
            log.info("[DRY RUN] would send to %s: %s", row["email"], row["subject"])
            tracker.mark(row["id"], "SIMULATED")
            stats["simulated"] += 1
            continue
        try:
            sender.send(row["email"], row["subject"], body)
            tracker.mark(row["id"], "SENT", sent=True)
            stats["sent"] += 1
        except Exception as e:  # keep going; failed rows are retried on the next live run
            log.error("Send to %s failed: %s", row["email"], e)
            tracker.mark(row["id"], "FAILED", error=str(e)[:200])
            stats["failed"] += 1
        time.sleep(sc["delay_seconds"])
    return stats
