"""Transactional local investigation and digest-bound reviewer state."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .common import ReviewError, bounded_bytes, canonical, parse_json, sha256, string, write_owned
from .patches import apply_patches


class RunStore:
    def __init__(self, directory: Path):
        self.directory = directory.resolve()
        if any(parent.is_symlink() for parent in [directory, *directory.parents]):
            raise ReviewError("Linked run directories are unsupported.", 3)
        self.directory.mkdir(parents=True, exist_ok=True)
        db_path = self.directory / "run.sqlite3"
        if db_path.is_symlink():
            raise ReviewError("Linked database is unsupported.", 3)
        self.db = sqlite3.connect(db_path, timeout=2)
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS run (
                singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
                run_key TEXT NOT NULL, state TEXT NOT NULL, packet TEXT, usage TEXT);
            CREATE TABLE IF NOT EXISTS inputs (
                id TEXT PRIMARY KEY, path TEXT NOT NULL, sha TEXT NOT NULL, raw BLOB NOT NULL);
            CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY, body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS decision (
                singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
                kind TEXT NOT NULL, receipt TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS draft (
                singleton INTEGER PRIMARY KEY CHECK(singleton = 1), raw BLOB NOT NULL);
            CREATE TABLE IF NOT EXISTS drafts (id TEXT PRIMARY KEY, raw BLOB NOT NULL);
            CREATE TABLE IF NOT EXISTS checkpoint (
                singleton INTEGER PRIMARY KEY CHECK(singleton = 1), body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS intent (id TEXT PRIMARY KEY, decision TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS actions (id TEXT PRIMARY KEY, event TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS config (
                singleton INTEGER PRIMARY KEY CHECK(singleton = 1), body TEXT NOT NULL);
        """)

    def close(self):
        self.db.close()

    def initialize(self, run_key: str, inputs: dict[str, tuple[Path, bytes]], *, resume=False):
        row = self.db.execute("SELECT run_key, state FROM run").fetchone()
        if row:
            if row[0] != run_key:
                raise ReviewError("Run directory belongs to different inputs/configuration.", 3)
            self._verify_current_inputs()
            if row[1] in ("PENDING_REVIEW", "HANDOFF", "APPROVED", "DRAFT_EXPORTED", "REJECTED"):
                return False
            if not resume or row[1] not in ("INVESTIGATING", "CANCELLED", "FAILED",
                                           "BUDGET_EXHAUSTED"):
                raise ReviewError("Incomplete runs require an explicit resume; stale runs require new output.", 3)
            self.fail("INVESTIGATING")
            return True
        if resume:
            raise ReviewError("Cannot resume an uninitialized run.", 3)
        with self.db:
            self.db.execute("INSERT INTO run VALUES (1, ?, 'INVESTIGATING', NULL, NULL)", (run_key,))
            self.db.executemany("INSERT INTO inputs VALUES (?, ?, ?, ?)",
                               [(key, str(path), sha256(raw), raw)
                                for key, (path, raw) in inputs.items()])
        return True

    def set_config(self, config):
        body = canonical(config).decode("utf-8")
        existing = self.db.execute("SELECT body FROM config").fetchone()
        if existing and existing[0] != body:
            raise ReviewError("Stored run configuration cannot change.", 3)
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO config VALUES (1, ?)", (body,))

    def config(self):
        row = self.db.execute("SELECT body FROM config").fetchone()
        if not row:
            raise ReviewError("This run has no resumable configuration.", 3)
        return json.loads(row[0])

    def load_checkpoint(self):
        row = self.db.execute("SELECT body FROM checkpoint").fetchone()
        return json.loads(row[0]) if row else None

    def _checkpoint(self, checkpoint):
        self.db.execute("INSERT OR REPLACE INTO checkpoint VALUES (1, ?)",
                        (canonical(checkpoint).decode("utf-8"),))

    def save_checkpoint(self, checkpoint):
        with self.db:
            self._checkpoint(checkpoint)

    def begin_action(self, action_id, decision, checkpoint):
        if self.db.execute("SELECT 1 FROM intent").fetchone():
            raise ReviewError("An uncommitted action must be resumed first.", 4)
        with self.db:
            self._checkpoint(checkpoint)
            self.db.execute("INSERT INTO intent VALUES (?, ?)",
                            (action_id, canonical(decision).decode("utf-8")))

    def pending_action(self):
        row = self.db.execute("SELECT id, decision FROM intent").fetchone()
        return (row[0], json.loads(row[1])) if row else None

    def commit_action(self, action_id, event, checkpoint):
        body = canonical(event).decode("utf-8")
        with self.db:
            existing = self.db.execute("SELECT event FROM actions WHERE id=?", (action_id,)).fetchone()
            if existing:
                if existing[0] != body:
                    raise ReviewError("Committed action cannot be rewritten.", 4)
                return
            self.db.execute("INSERT INTO actions VALUES (?, ?)", (action_id, body))
            self.db.execute("INSERT INTO events(body) VALUES (?)", (body,))
            self._checkpoint(checkpoint)
            self.db.execute("DELETE FROM intent WHERE id=?", (action_id,))

    def event(self, body):
        with self.db:
            self.db.execute("INSERT INTO events(body) VALUES (?)", (canonical(body).decode("utf-8"),))

    def events(self):
        return [{"sequence": seq, **json.loads(body)}
                for seq, body in self.db.execute("SELECT seq, body FROM events ORDER BY seq")]

    def finish(self, packet: dict, usage: dict):
        with self.db:
            self.db.execute("UPDATE run SET state=?, packet=?, usage=? WHERE singleton=1",
                            (packet["domain_status"], canonical(packet).decode("utf-8"),
                             canonical(usage).decode("utf-8")))

    def fail(self, state: str):
        with self.db:
            self.db.execute("UPDATE run SET state=? WHERE singleton=1", (state,))

    def packet(self):
        row = self.db.execute("SELECT packet FROM run").fetchone()
        if not row or row[0] is None:
            raise ReviewError("Run has no complete proposal.", 3)
        return json.loads(row[0])

    def usage(self):
        return json.loads(self.db.execute("SELECT usage FROM run").fetchone()[0])

    def state(self):
        row = self.db.execute("SELECT state FROM run").fetchone()
        return row[0] if row else "NEW"

    def _verify_current_inputs(self):
        for input_id, path, version in self.db.execute("SELECT id, path, sha FROM inputs"):
            try:
                actual = bounded_bytes(Path(path), 64 * 1024)
            except (OSError, ReviewError) as exc:
                self.fail("STALE")
                raise ReviewError(f"Current {input_id} is unavailable; approval is stale.", 3) from exc
            if sha256(actual) != version:
                self.fail("STALE")
                raise ReviewError(f"Current {input_id} changed; approval is stale.", 3)

    def review(self, kind: str, expected_digest: str, reviewer: str, *,
               failpoint=lambda phase: None):
        if kind not in ("approve", "reject"):
            raise ReviewError("Review decision must be approve or reject.", 3)
        string(reviewer, "reviewer label", 80)
        packet = self.packet()
        if expected_digest != packet["proposal_sha256"]:
            raise ReviewError("Expected proposal digest does not match.", 3)
        core = {key: value for key, value in packet.items() if key != "proposal_sha256"}
        if sha256(canonical(core)) != expected_digest:
            self.fail("STALE")
            raise ReviewError("Stored proposal digest is invalid.", 3)
        try:
            on_disk = parse_json(bounded_bytes(self.directory / "review.json", 96 * 1024))
        except (OSError, ReviewError) as exc:
            self.fail("STALE")
            raise ReviewError("Proposal artifact is unavailable or corrupt.", 3) from exc
        if canonical(on_disk) != canonical(packet):
            self.fail("STALE")
            raise ReviewError("Proposal artifact changed; approval is stale.", 3)
        self._verify_current_inputs()
        if self.state() == "STALE":
            raise ReviewError("A stale review requires a new run.", 3)
        existing = self.db.execute("SELECT kind, receipt FROM decision").fetchone()
        if existing:
            if existing[0] != kind:
                raise ReviewError("An existing review decision cannot be reversed.", 3)
            receipt = json.loads(existing[1])
            if kind == "approve":
                self._materialize(failpoint)
            write_owned(self.directory / "review-receipt.json", canonical(receipt) + b"\n")
            return receipt
        if self.state() != "PENDING_REVIEW":
            raise ReviewError("Only a pending, complete proposal can be reviewed.", 3)
        documents = packet.get("documents", [packet["source"]])
        drafts = {}
        if kind == "approve":
            for document in documents:
                doc_id = document.get("document_id", "agreement")
                if doc_id not in ("agreement", "A1", "A2"):
                    raise ReviewError("Unsupported reviewed document identifier.", 3)
                row = self.db.execute("SELECT raw FROM inputs WHERE id=?", (doc_id,)).fetchone()
                if not row:
                    raise ReviewError("Reviewed document snapshot is missing.", 3)
                patches = [p for p in packet["patches"] if p["document_id"] == doc_id]
                drafts[doc_id] = apply_patches(row[0], patches)
        receipt = {"schema_version": 2, "decision": kind, "reviewer_label": reviewer,
                   "proposal_sha256": expected_digest,
                   "source_sha256": packet["source"]["document_sha256"],
                   "reviewed_sha256": sha256(drafts["agreement"]) if drafts else None,
                   "reviewed_documents": {key: sha256(raw) for key, raw in drafts.items()},
                   "decided_at": datetime.now(timezone.utc).isoformat(),
                   "state": "DRAFT_EXPORTED" if kind == "approve" else "REJECTED", "fictional": True}
        with self.db:
            self.db.execute("INSERT INTO decision VALUES (1, ?, ?)",
                            (kind, canonical(receipt).decode("utf-8")))
            self.db.executemany("INSERT INTO drafts VALUES (?, ?)", list(drafts.items()))
            if drafts:
                self.db.execute("INSERT INTO draft VALUES (1, ?)", (drafts["agreement"],))
            self.db.execute("UPDATE run SET state=? WHERE singleton=1",
                            ("APPROVED" if kind == "approve" else "REJECTED",))
        failpoint("after_approval_commit")
        if drafts:
            self._materialize(failpoint)
        write_owned(self.directory / "review-receipt.json", canonical(receipt) + b"\n")
        return receipt

    def _materialize(self, failpoint=lambda phase: None):
        rows = self.db.execute("SELECT id, raw FROM drafts ORDER BY id").fetchall()
        if not rows:
            row = self.db.execute("SELECT raw FROM draft").fetchone()
            if not row:
                raise ReviewError("Approved draft is unavailable.", 3)
            rows = [("agreement", row[0])]
        for doc_id, raw in rows:
            write_owned(self.directory / "reviewed" / f"{doc_id}.txt", raw)
            failpoint("after_draft_materialize")
        failpoint("before_export_commit")
        with self.db:
            self.db.execute("UPDATE run SET state='DRAFT_EXPORTED' WHERE singleton=1")

