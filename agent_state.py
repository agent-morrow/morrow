"""
agent_state.py — Minimal reference implementation of three-category agent state lifecycle.

Demonstrates checkpoint semantics vs. CRUD semantics for AI agent working memory.
Three categories:
  1. Ephemeral working state — discarded at session end unless checkpointed
  2. Checkpointed process state — persisted at semantically meaningful boundaries
  3. User-attributed data — separate schema, separate deletion semantics

Usage:
    from agent_state import AgentSession, UserStore

    session = AgentSession(session_id="sess_001", user_id="user_xyz")

    # Ephemeral: scratch state that lives only in this session
    session.set_working("current_subtask", "draft_api_call")
    session.set_working("tool_call_in_flight", {"name": "search", "args": {"q": "..."}})

    # Checkpoint: promote working state to durable at task completion
    session.checkpoint(label="subtask_complete", include_keys=["current_subtask"])

    # User data: stored separately, subject to right-to-erasure
    store = UserStore()
    store.set("user_xyz", "email", "user@example.com")

    # GDPR deletion: removes user data only — does NOT touch process checkpoints
    store.delete_user("user_xyz")

    # Restore from checkpoint after session end (no working state survives)
    restored = AgentSession.restore(session_id="sess_001")
    print(restored.get_checkpoint("subtask_complete"))

See: https://morrow.run/posts/agent-state-is-process-state.html
"""

import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional


class AgentSession:
    """
    Manages ephemeral working state and explicit process checkpoints for one agent session.
    Working state is in-memory only. Checkpoints are persisted to SQLite.
    Neither category shares a key space with user-attributed data.
    """

    DB_PATH = Path(".agent_state.db")

    def __init__(self, session_id: str, user_id: Optional[str] = None):
        self.session_id = session_id
        self.user_id = user_id
        self._working: Dict[str, Any] = {}  # ephemeral — never written to disk directly
        self._db = self._open_db()

    def _open_db(self) -> sqlite3.Connection:
        db = sqlite3.connect(str(self.DB_PATH))
        db.execute("""
            CREATE TABLE IF NOT EXISTS checkpoints (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                label TEXT NOT NULL,
                payload TEXT NOT NULL,
                created_at REAL NOT NULL
            )
        """)
        db.commit()
        return db

    # --- Ephemeral working state ---

    def set_working(self, key: str, value: Any) -> None:
        """Store ephemeral working state. Lives in memory only."""
        self._working[key] = value

    def get_working(self, key: str, default: Any = None) -> Any:
        return self._working.get(key, default)

    def clear_working(self) -> None:
        """Called at session end. Ephemeral state is discarded unless checkpointed."""
        self._working.clear()

    # --- Checkpointed process state ---

    def checkpoint(self, label: str, include_keys: Optional[List[str]] = None) -> str:
        """
        Promote working state to a named checkpoint.
        Only keys listed in include_keys are promoted (default: all working state).
        This is the semantically meaningful boundary — task completion, handoff, rotation.
        """
        snapshot = (
            {k: self._working[k] for k in include_keys if k in self._working}
            if include_keys
            else dict(self._working)
        )
        checkpoint_id = str(uuid.uuid4())
        self._db.execute(
            "INSERT INTO checkpoints VALUES (?, ?, ?, ?, ?)",
            (checkpoint_id, self.session_id, label, json.dumps(snapshot), time.time()),
        )
        self._db.commit()
        return checkpoint_id

    def get_checkpoint(self, label: str) -> Optional[Dict[str, Any]]:
        """Retrieve most recent checkpoint with the given label for this session."""
        row = self._db.execute(
            "SELECT payload FROM checkpoints WHERE session_id=? AND label=? ORDER BY created_at DESC LIMIT 1",
            (self.session_id, label),
        ).fetchone()
        return json.loads(row[0]) if row else None

    def list_checkpoints(self) -> List[Dict[str, Any]]:
        rows = self._db.execute(
            "SELECT id, label, created_at FROM checkpoints WHERE session_id=? ORDER BY created_at",
            (self.session_id,),
        ).fetchall()
        return [{"id": r[0], "label": r[1], "created_at": r[2]} for r in rows]

    @classmethod
    def restore(cls, session_id: str) -> "AgentSession":
        """
        Restore a session by ID. Working state is empty (ephemeral — correctly discarded).
        Checkpoints are available for resumption.
        """
        session = cls(session_id=session_id)
        return session

    def close(self) -> None:
        self.clear_working()
        self._db.close()


class UserStore:
    """
    Separate storage for user-attributed data.
    Isolated from agent process state — correct deletion semantics apply independently.
    """

    DB_PATH = Path(".user_store.db")

    def __init__(self):
        self._db = sqlite3.connect(str(self.DB_PATH))
        self._db.execute("""
            CREATE TABLE IF NOT EXISTS user_data (
                user_id TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                created_at REAL NOT NULL,
                PRIMARY KEY (user_id, key)
            )
        """)
        self._db.commit()

    def set(self, user_id: str, key: str, value: Any) -> None:
        self._db.execute(
            "INSERT OR REPLACE INTO user_data VALUES (?, ?, ?, ?)",
            (user_id, key, json.dumps(value), time.time()),
        )
        self._db.commit()

    def get(self, user_id: str, key: str, default: Any = None) -> Any:
        row = self._db.execute(
            "SELECT value FROM user_data WHERE user_id=? AND key=?",
            (user_id, key),
        ).fetchone()
        return json.loads(row[0]) if row else default

    def delete_user(self, user_id: str) -> int:
        """
        GDPR right-to-erasure: removes all user-attributed data for this user.
        Does NOT touch agent process checkpoints — those have a separate lifecycle.
        Returns count of deleted rows.
        """
        cursor = self._db.execute(
            "DELETE FROM user_data WHERE user_id=?", (user_id,)
        )
        self._db.commit()
        return cursor.rowcount

    def close(self) -> None:
        self._db.close()


# --- Demo ---

if __name__ == "__main__":
    print("=== Agent State Lifecycle Demo ===\n")

    store = UserStore()
    store.set("user_xyz", "email", "alice@example.com")
    store.set("user_xyz", "name", "Alice")
    print(f"User data stored: email={store.get('user_xyz', 'email')}")

    session = AgentSession(session_id="sess_demo_001", user_id="user_xyz")
    session.set_working("current_subtask", "generate_report")
    session.set_working("tool_call_in_flight", {"name": "fetch_data", "status": "pending"})
    session.set_working("draft_output", "## Report\n...")
    print(f"Working state: {list(session._working.keys())}")

    ckpt_id = session.checkpoint(label="subtask_complete", include_keys=["current_subtask", "draft_output"])
    print(f"Checkpoint created: {ckpt_id}")

    # Session ends — ephemeral state is discarded
    session.close()
    print("Session closed. Working state discarded.")

    # GDPR deletion — user data removed; checkpoints NOT affected
    deleted = store.delete_user("user_xyz")
    print(f"User 'user_xyz' deleted ({deleted} rows). Email now: {store.get('user_xyz', 'email')}")

    # Restore session — working state correctly empty, checkpoint survives
    restored = AgentSession.restore("sess_demo_001")
    print(f"Restored working state: {restored._working}  ← correctly empty")
    ckpt = restored.get_checkpoint("subtask_complete")
    print(f"Restored checkpoint 'subtask_complete': {ckpt}  ← survives GDPR deletion")

    print("\nKey point: the deletion cascade touched user_data, not process checkpoints.")
    print("Separate schemas = correct deletion semantics for both categories.")

    restored.close()
    store.close()
    Path(".agent_state.db").unlink(missing_ok=True)
    Path(".user_store.db").unlink(missing_ok=True)
