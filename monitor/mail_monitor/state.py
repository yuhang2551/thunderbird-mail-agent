"""状态：SQLite 里记三张表——处理过的邮件、见过的发件人、每次运行。

这是 Agent 的记忆。去重靠 messages 表；"这是谁"靠 senders 表（第二天接 LLM 推断身份）。
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from email.utils import parseaddr
from pathlib import Path
from typing import Any, Iterable

from .models import Decision, MessageHeader

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
  id TEXT PRIMARY KEY,
  account TEXT,
  folder_path TEXT,
  thread_id TEXT,
  sender_email TEXT,
  sender_name TEXT,
  subject TEXT,
  received_at TEXT,
  first_seen_at TEXT NOT NULL,
  category TEXT,
  needs_action TEXT,
  urgency TEXT,
  deadline TEXT,
  who TEXT,
  what TEXT,
  suggested_action TEXT,
  decided_by TEXT,
  rule_name TEXT,
  notify_mode TEXT,
  pushed_at TEXT,
  digest_pending INTEGER NOT NULL DEFAULT 0,
  digested_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_messages_digest ON messages(digest_pending);
CREATE INDEX IF NOT EXISTS idx_messages_sender ON messages(sender_email);

CREATE TABLE IF NOT EXISTS senders (
  email TEXT PRIMARY KEY,
  name TEXT,
  domain TEXT,
  relation TEXT,
  notes TEXT,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  message_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  fetched INTEGER DEFAULT 0,
  new INTEGER DEFAULT 0,
  pushed INTEGER DEFAULT 0,
  errors TEXT
);
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class State:
    def __init__(self, path: Path | str):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).expanduser().parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    # ---- 邮件 ----

    def seen(self, ids: Iterable[str]) -> set[str]:
        ids = list(ids)
        found: set[str] = set()
        for start in range(0, len(ids), 500):
            chunk = ids[start : start + 500]
            marks = ",".join("?" * len(chunk))
            rows = self.conn.execute(f"SELECT id FROM messages WHERE id IN ({marks})", chunk).fetchall()
            found.update(row["id"] for row in rows)
        return found

    def mark_seen(self, headers: Iterable[MessageHeader]) -> int:
        """只登记、不判断、不推送（首次运行用）。"""
        now = utcnow()
        count = 0
        for header in headers:
            cur = self.conn.execute(
                """INSERT OR IGNORE INTO messages
                   (id, account, folder_path, thread_id, sender_email, sender_name, subject, received_at,
                    first_seen_at, decided_by, notify_mode, digest_pending)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'init', 'never', 0)""",
                (
                    header.id, header.account_name, header.folder_path, header.thread_id,
                    header.sender_email, header.sender_name, header.subject,
                    header.date.isoformat() if header.date else None, now,
                ),
            )
            count += cur.rowcount
        self.conn.commit()
        return count

    def record(self, header: MessageHeader, decision: Decision, *, notify_mode: str, pushed: bool) -> None:
        now = utcnow()
        self.conn.execute(
            """INSERT OR REPLACE INTO messages
               (id, account, folder_path, thread_id, sender_email, sender_name, subject, received_at, first_seen_at,
                category, needs_action, urgency, deadline, who, what, suggested_action, decided_by, rule_name,
                notify_mode, pushed_at, digest_pending, digested_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)""",
            (
                header.id, header.account_name, header.folder_path, header.thread_id,
                header.sender_email, header.sender_name, header.subject,
                header.date.isoformat() if header.date else None, now,
                decision.category, decision.needs_action, decision.urgency, decision.deadline,
                decision.who, decision.what, decision.suggested_action, decision.decided_by, decision.rule_name,
                notify_mode, now if pushed else None, 1 if notify_mode == "digest" else 0,
            ),
        )
        self.conn.commit()

    def pending_digest(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM messages WHERE digest_pending = 1 ORDER BY received_at ASC"
        ).fetchall()

    def mark_digested(self, ids: Iterable[str]) -> None:
        now = utcnow()
        self.conn.executemany(
            "UPDATE messages SET digest_pending = 0, digested_at = ? WHERE id = ?", [(now, mid) for mid in ids]
        )
        self.conn.commit()

    # ---- 发件人 ----

    def touch_sender(self, header: MessageHeader) -> None:
        email = header.sender_email
        if not email:
            return
        now = utcnow()
        # 只存 From 里真正的名字；裸地址不覆盖之前记住的名字
        display_name = parseaddr(header.author)[0]
        self.conn.execute(
            """INSERT INTO senders (email, name, domain, first_seen_at, last_seen_at, message_count)
               VALUES (?, ?, ?, ?, ?, 1)
               ON CONFLICT(email) DO UPDATE SET
                 name = COALESCE(NULLIF(excluded.name, ''), senders.name),
                 last_seen_at = excluded.last_seen_at,
                 message_count = senders.message_count + 1""",
            (email, display_name, header.sender_domain, now, now),
        )
        self.conn.commit()

    def sender(self, email: str) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM senders WHERE email = ?", (email.lower(),)).fetchone()

    def set_sender_relation(self, email: str, relation: str, notes: str | None = None) -> None:
        self.conn.execute(
            "UPDATE senders SET relation = ?, notes = COALESCE(?, notes) WHERE email = ?",
            (relation, notes, email.lower()),
        )
        self.conn.commit()

    # ---- 运行记录 ----

    def start_run(self) -> int:
        cur = self.conn.execute("INSERT INTO runs (started_at) VALUES (?)", (utcnow(),))
        self.conn.commit()
        return int(cur.lastrowid)

    def finish_run(self, run_id: int, *, fetched: int, new: int, pushed: int, errors: list[str]) -> None:
        self.conn.execute(
            "UPDATE runs SET finished_at = ?, fetched = ?, new = ?, pushed = ?, errors = ? WHERE id = ?",
            (utcnow(), fetched, new, pushed, json.dumps(errors, ensure_ascii=False) if errors else None, run_id),
        )
        self.conn.commit()

    def stats(self) -> dict[str, Any]:
        row = self.conn.execute(
            """SELECT COUNT(*) AS total,
                      SUM(CASE WHEN needs_action = 'yes' THEN 1 ELSE 0 END) AS needs_action,
                      SUM(CASE WHEN needs_action = 'unsure' THEN 1 ELSE 0 END) AS unsure,
                      SUM(CASE WHEN pushed_at IS NOT NULL THEN 1 ELSE 0 END) AS pushed,
                      SUM(CASE WHEN digest_pending = 1 THEN 1 ELSE 0 END) AS digest_pending,
                      SUM(CASE WHEN decided_by = 'rule' THEN 1 ELSE 0 END) AS by_rule,
                      SUM(CASE WHEN decided_by = 'llm' THEN 1 ELSE 0 END) AS by_llm,
                      SUM(CASE WHEN decided_by = 'fallback' THEN 1 ELSE 0 END) AS by_fallback
               FROM messages"""
        ).fetchone()
        senders = self.conn.execute("SELECT COUNT(*) AS n FROM senders").fetchone()["n"]
        runs = self.conn.execute("SELECT COUNT(*) AS n FROM runs").fetchone()["n"]
        return {**{k: (row[k] or 0) for k in row.keys()}, "senders": senders, "runs": runs}
