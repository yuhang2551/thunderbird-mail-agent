"""状态：SQLite 里记三张表——处理过的邮件、见过的发件人、每次运行；另有一张 meta 表记零碎的状态（比如上次发的是几点那次汇总）。

这是 Agent 的记忆。去重靠 messages 表；"这是谁"靠 senders 表（规则、模型、你自己都能写，优先级 你 > 规则 > 模型）；
"同一话题之前说了什么"靠 messages 表按 (folder_path, thread_id) 或归一化主题查。memory.py 负责把这些整理成给模型看的文字。
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from email.utils import parseaddr
from pathlib import Path
from typing import Any, Iterable

from .models import Decision, MessageHeader, normalize_subject

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
  id TEXT PRIMARY KEY,
  account TEXT,
  folder_path TEXT,
  thread_id TEXT,
  sender_email TEXT,
  sender_name TEXT,
  subject TEXT,
  subject_key TEXT,
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
  digested_at TEXT,
  label TEXT,
  labeled_at TEXT
);

CREATE TABLE IF NOT EXISTS senders (
  email TEXT PRIMARY KEY,
  name TEXT,
  domain TEXT,
  relation TEXT,
  relation_source TEXT,
  relation_updated_at TEXT,
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

CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT
);
"""

# 旧版本数据库缺的列：打开时补上，数据不丢
MIGRATIONS: dict[str, dict[str, str]] = {
    "messages": {"subject_key": "TEXT", "label": "TEXT", "labeled_at": "TEXT"},
    "senders": {"relation_source": "TEXT", "relation_updated_at": "TEXT"},
}

INDEXES = """
CREATE INDEX IF NOT EXISTS idx_messages_digest ON messages(digest_pending);
CREATE INDEX IF NOT EXISTS idx_messages_sender ON messages(sender_email);
CREATE INDEX IF NOT EXISTS idx_messages_thread ON messages(folder_path, thread_id);
CREATE INDEX IF NOT EXISTS idx_messages_subject ON messages(account, subject_key);
"""

# 发件人身份的来源优先级：你手动设的 > 规则写的 > 模型猜的。低优先级不能覆盖高优先级。
RELATION_RANK = {"llm": 1, "rule": 2, "user": 3}


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class State:
    def __init__(self, path: Path | str):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).expanduser().parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.create_function("normalize_subject", 1, normalize_subject)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)
        self._migrate()
        self.conn.executescript(INDEXES)

    def _migrate(self) -> None:
        for table, columns in MIGRATIONS.items():
            existing = {row["name"] for row in self.conn.execute(f"PRAGMA table_info({table})")}
            for column, kind in columns.items():
                if column not in existing:
                    self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")
        self.conn.execute("UPDATE messages SET subject_key = normalize_subject(subject) WHERE subject_key IS NULL")
        self.conn.commit()

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
        """只登记、不判断、不推送（首次运行用）。发件人也顺手记下来，以后好数"之前来过几封"。"""
        now = utcnow()
        count = 0
        for header in headers:
            cur = self.conn.execute(
                """INSERT OR IGNORE INTO messages
                   (id, account, folder_path, thread_id, sender_email, sender_name, subject, subject_key, received_at,
                    first_seen_at, decided_by, notify_mode, digest_pending)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'init', 'never', 0)""",
                (
                    header.id, header.account_name, header.folder_path, header.thread_id,
                    header.sender_email, header.sender_name, header.subject, header.subject_key,
                    header.date.isoformat() if header.date else None, now,
                ),
            )
            if cur.rowcount:
                count += 1
                self.touch_sender(header, commit=False)
        self.conn.commit()
        return count

    def record(
        self, header: MessageHeader, decision: Decision, *, notify_mode: str, pushed: bool, to_digest: bool | None = None
    ) -> None:
        """notify_mode 是判断出的推送方式；to_digest 是这封要不要等汇总，不写就看 notify_mode 是不是 digest
        （本该即时推送、赶上免打扰或推送失败的，notify_mode 还是 instant，to_digest=True）。"""
        now = utcnow()
        if to_digest is None:
            to_digest = notify_mode == "digest"
        self.conn.execute(
            """INSERT OR REPLACE INTO messages
               (id, account, folder_path, thread_id, sender_email, sender_name, subject, subject_key, received_at, first_seen_at,
                category, needs_action, urgency, deadline, who, what, suggested_action, decided_by, rule_name,
                notify_mode, pushed_at, digest_pending, digested_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)""",
            (
                header.id, header.account_name, header.folder_path, header.thread_id,
                header.sender_email, header.sender_name, header.subject, header.subject_key,
                header.date.isoformat() if header.date else None, now,
                decision.category, decision.needs_action, decision.urgency, decision.deadline,
                decision.who, decision.what, decision.suggested_action, decision.decided_by, decision.rule_name,
                notify_mode, now if pushed else None, 1 if to_digest else 0,
            ),
        )
        self.conn.commit()

    def pending_digest(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM messages WHERE digest_pending = 1 ORDER BY received_at ASC"
        ).fetchall()

    def get_meta(self, key: str) -> str | None:
        row = self.conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def set_meta(self, key: str, value: str) -> None:
        self.conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value))
        self.conn.commit()

    def mark_digested(self, ids: Iterable[str]) -> None:
        now = utcnow()
        self.conn.executemany(
            "UPDATE messages SET digest_pending = 0, digested_at = ? WHERE id = ?", [(now, mid) for mid in ids]
        )
        self.conn.commit()

    # ---- 评测：你标的答案 ----

    def recent_decisions(self, *, limit: int = 20, unlabeled_only: bool = True) -> list[sqlite3.Row]:
        """最近判断过的邮件（不含首次登记的），新的在前。"""
        where = "decided_by != 'init'" + (" AND label IS NULL" if unlabeled_only else "")
        return self.conn.execute(
            f"SELECT * FROM messages WHERE {where} ORDER BY received_at DESC LIMIT ?", (limit,)
        ).fetchall()

    def set_label(self, message_id: str, label: str) -> bool:
        """记下你对一封邮件的答案：yes = 需要处理，no = 不需要。"""
        if label not in ("yes", "no"):
            raise ValueError("label 只能是 yes 或 no")
        cur = self.conn.execute(
            "UPDATE messages SET label = ?, labeled_at = ? WHERE id = ?", (label, utcnow(), message_id)
        )
        self.conn.commit()
        return cur.rowcount > 0

    def evaluation(self) -> dict[str, Any]:
        """拿标过的邮件算：需要处理的有没有漏推、即时推送里有多少噪声、各来源判对多少。
        这里的「即时推送」指判断结果（notify_mode），赶上免打扰或推送失败、最后进了汇总的也算：评的是判断准不准。"""
        rows = self.conn.execute(
            "SELECT needs_action, notify_mode, decided_by, label FROM messages WHERE label IS NOT NULL"
        ).fetchall()
        actual_yes = [r for r in rows if r["label"] == "yes"]
        pushed = [r for r in rows if r["notify_mode"] == "instant"]
        predicted_yes = [r for r in rows if r["needs_action"] == "yes"]
        by_source: dict[str, dict[str, int]] = {}
        for r in rows:
            source = by_source.setdefault(r["decided_by"] or "?", {"n": 0, "correct": 0, "unsure": 0})
            source["n"] += 1
            if r["needs_action"] == "unsure":
                source["unsure"] += 1
            elif (r["needs_action"] == "yes") == (r["label"] == "yes"):
                source["correct"] += 1
        return {
            "labeled": len(rows),
            "actual_yes": len(actual_yes),
            "pushed": len(pushed),
            "caught": sum(1 for r in actual_yes if r["notify_mode"] == "instant"),  # 需要处理且被即时推送
            "missed": sum(1 for r in actual_yes if r["notify_mode"] != "instant"),  # 需要处理但没即时推送（漏推）
            "pushed_yes": sum(1 for r in pushed if r["label"] == "yes"),
            "noise": sum(1 for r in pushed if r["label"] == "no"),  # 即时推送了但其实不用管
            "strict_tp": sum(1 for r in predicted_yes if r["label"] == "yes"),
            "predicted_yes": len(predicted_yes),
            "unsure": sum(1 for r in rows if r["needs_action"] == "unsure"),
            "by_source": by_source,
        }

    # ---- 记忆：历史邮件 ----

    def sender_history(self, email: str, *, limit: int = 3, exclude_id: str | None = None) -> list[sqlite3.Row]:
        """这个发件人之前的邮件（只要判断过的），新的在前。"""
        return self.conn.execute(
            """SELECT * FROM messages
               WHERE sender_email = ? AND id != ? AND decided_by != 'init'
               ORDER BY received_at DESC LIMIT ?""",
            (email.lower(), exclude_id or "", limit),
        ).fetchall()

    def sender_counts(self, email: str, *, exclude_id: str | None = None) -> tuple[int, int]:
        """(之前一共几封, 其中几封需要处理)。"""
        row = self.conn.execute(
            """SELECT COUNT(*) AS total, COALESCE(SUM(needs_action = 'yes'), 0) AS yes
               FROM messages WHERE sender_email = ? AND id != ?""",
            (email.lower(), exclude_id or ""),
        ).fetchone()
        return int(row["total"]), int(row["yes"])

    def thread_history(self, header: MessageHeader, *, limit: int = 3) -> list[sqlite3.Row]:
        """同一话题之前的邮件：同一文件夹里 thread_id 相同，或者同一账号里去掉 Re:/Fwd: 后主题相同。新的在前。"""
        clauses: list[str] = []
        params: list[Any] = [header.id]
        if header.thread_id:
            clauses.append("(folder_path = ? AND thread_id = ?)")
            params += [header.folder_path, header.thread_id]
        key = header.subject_key
        if key:
            clauses.append("(account IS ? AND subject_key = ?)")
            params += [header.account_name, key]
        if not clauses:
            return []
        params.append(limit)
        return self.conn.execute(
            f"SELECT * FROM messages WHERE id != ? AND ({' OR '.join(clauses)}) ORDER BY received_at DESC LIMIT ?",
            params,
        ).fetchall()

    # ---- 记忆：发件人 ----

    def touch_sender(self, header: MessageHeader, *, commit: bool = True) -> None:
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
        if commit:
            self.conn.commit()

    def sender(self, email: str) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM senders WHERE email = ?", (email.lower(),)).fetchone()

    def set_sender_relation(self, email: str, relation: str, *, source: str = "user", notes: str | None = None) -> bool:
        """记下"这个发件人是谁"。source 是 user / rule / llm，低优先级的来源改不了高优先级写下的身份。
        返回有没有真的改动。"""
        email = email.strip().lower()
        relation = " ".join(relation.split())
        if not email or not relation:
            return False
        now = utcnow()
        row = self.sender(email)
        if row is None:
            domain = email.rsplit("@", 1)[-1] if "@" in email else ""
            self.conn.execute(
                """INSERT INTO senders (email, domain, relation, relation_source, relation_updated_at, notes,
                                        first_seen_at, last_seen_at, message_count)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)""",
                (email, domain, relation, source, now, notes, now, now),
            )
            self.conn.commit()
            return True
        current_rank = RELATION_RANK.get(row["relation_source"] or "", 0) if row["relation"] else 0
        if RELATION_RANK.get(source, 0) < current_rank:
            return False
        if row["relation"] == relation and row["relation_source"] == source:
            if notes is not None and notes != row["notes"]:
                self.conn.execute("UPDATE senders SET notes = ? WHERE email = ?", (notes, email))
                self.conn.commit()
            return False
        self.conn.execute(
            """UPDATE senders SET relation = ?, relation_source = ?, relation_updated_at = ?, notes = COALESCE(?, notes)
               WHERE email = ?""",
            (relation, source, now, notes, email),
        )
        self.conn.commit()
        return True

    def list_senders(self, *, limit: int = 50) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM senders ORDER BY message_count DESC, last_seen_at DESC LIMIT ?", (limit,)
        ).fetchall()

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
        known = self.conn.execute("SELECT COUNT(*) AS n FROM senders WHERE relation IS NOT NULL").fetchone()["n"]
        runs = self.conn.execute("SELECT COUNT(*) AS n FROM runs").fetchone()["n"]
        return {**{k: (row[k] or 0) for k in row.keys()}, "senders": senders, "senders_with_relation": known, "runs": runs}
