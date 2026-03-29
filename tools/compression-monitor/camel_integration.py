"""
camel_integration.py — Behavioral drift monitor for CAMEL agent context truncation.

CAMEL's BaseAgent and ChatAgent maintain a message history (context_len_limit).
When the history exceeds the limit, older messages are silently dropped.
This integration wraps the context-management step to snapshot behavioral
fingerprints before and after truncation, then emits a CompressionSession
with ghost lexicon decay and semantic distance scores.

Usage:
    from camel_integration import CamelDriftMonitor
    from camel.agents import ChatAgent
    from camel.models import ModelFactory

    monitor = CamelDriftMonitor(window=20, threshold=0.15)
    agent = ChatAgent(system_message=..., model=model)
    monitor.attach(agent)
    # Now every context truncation event is fingerprinted automatically.

Requires: camel-ai, sentence-transformers (optional for semantic scoring)
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

# Try sentence-transformers for semantic distance; fall back to jaccard.
try:
    from sentence_transformers import SentenceTransformer
    import numpy as np
    _SBERT_AVAILABLE = True
except ImportError:
    _SBERT_AVAILABLE = False


# ── Types ────────────────────────────────────────────────────────────────────

@dataclass
class CompressionSession:
    """Represents one context-truncation boundary event."""
    session_id: str
    timestamp: float
    messages_before: int
    messages_after: int
    ghost_terms: List[str]          # vocab present before but absent after
    ccs_score: float                # Compression Coherence Score (0..1, lower = more drift)
    semantic_distance: float        # embedding distance (0..1) or jaccard fallback
    payload: Dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(self.__dict__, default=str)

    @property
    def alert(self) -> bool:
        return self.ccs_score < 0.5 or self.semantic_distance > 0.25


# ── Ghost lexicon ─────────────────────────────────────────────────────────────

_STOP = frozenset(
    "a an the is are was were be been being have has had do does did "
    "will would could should may might shall can need dare ought used "
    "i you he she it we they me him her us them my your his its our "
    "their this that these those which who whom what when where why how "
    "and or but nor so yet for of to in on at by up as if".split()
)


def _tokenize(text: str) -> Counter:
    tokens = re.findall(r"[a-z][a-z0-9_'-]*", text.lower())
    return Counter(t for t in tokens if t not in _STOP and len(t) > 2)


def _extract_text(messages: list) -> str:
    """Pull text out of CAMEL message objects or plain dicts."""
    parts = []
    for m in messages:
        if hasattr(m, "content"):
            parts.append(str(m.content))
        elif isinstance(m, dict):
            parts.append(str(m.get("content", "")))
    return " ".join(parts)


def _ghost_terms(before_text: str, after_text: str) -> List[str]:
    before_counts = _tokenize(before_text)
    after_counts = _tokenize(after_text)
    threshold = 3
    ghosts = [
        t for t, c in before_counts.items()
        if c >= threshold and after_counts[t] == 0
    ]
    return sorted(ghosts)


def _ccs_score(before_text: str, after_text: str) -> float:
    before_vocab = set(_tokenize(before_text))
    after_vocab = set(_tokenize(after_text))
    if not before_vocab:
        return 1.0
    overlap = len(before_vocab & after_vocab) / len(before_vocab)
    return round(overlap, 4)


def _semantic_distance(before_text: str, after_text: str,
                        model: Optional[Any] = None) -> float:
    if _SBERT_AVAILABLE and model is not None:
        try:
            vecs = model.encode([before_text[:512], after_text[:512]])
            cos = float(
                np.dot(vecs[0], vecs[1])
                / (np.linalg.norm(vecs[0]) * np.linalg.norm(vecs[1]) + 1e-9)
            )
            return round(1.0 - cos, 4)
        except Exception:
            pass
    # Jaccard fallback
    before_vocab = set(_tokenize(before_text))
    after_vocab = set(_tokenize(after_text))
    if not before_vocab and not after_vocab:
        return 0.0
    jaccard = len(before_vocab & after_vocab) / max(len(before_vocab | after_vocab), 1)
    return round(1.0 - jaccard, 4)


# ── Monitor ───────────────────────────────────────────────────────────────────

class CamelDriftMonitor:
    """
    Attaches to a CAMEL ChatAgent and intercepts context truncation.

    CAMEL's ChatAgent.update_memory() (or equivalent) drops old messages when
    the context_len_limit is exceeded.  We monkey-patch that path to snapshot
    the message list before/after and compute drift metrics.
    """

    def __init__(
        self,
        window: int = 20,
        threshold: float = 0.15,
        sbert_model: str = "all-MiniLM-L6-v2",
        on_event: Optional[Callable[[CompressionSession], None]] = None,
    ):
        self.window = window
        self.threshold = threshold
        self.sessions: List[CompressionSession] = []
        self._sbert: Optional[Any] = None
        if _SBERT_AVAILABLE:
            try:
                self._sbert = SentenceTransformer(sbert_model)
            except Exception:
                pass
        self._on_event = on_event or self._default_log
        self._attached_agents: list = []

    def attach(self, agent: Any) -> None:
        """
        Monkey-patch agent.update_memory or the first callable that trims
        the stored message list.  Falls back to wrapping step() if needed.
        """
        if hasattr(agent, "update_memory"):
            original = agent.update_memory

            def patched_update_memory(*args, **kwargs):
                before = list(getattr(agent, "stored_messages", []))
                result = original(*args, **kwargs)
                after = list(getattr(agent, "stored_messages", []))
                if len(after) < len(before):
                    self._record(before, after)
                return result

            agent.update_memory = patched_update_memory
        elif hasattr(agent, "step"):
            original_step = agent.step

            def patched_step(*args, **kwargs):
                before = list(getattr(agent, "stored_messages", []))
                result = original_step(*args, **kwargs)
                after = list(getattr(agent, "stored_messages", []))
                if len(after) < len(before):
                    self._record(before, after)
                return result

            agent.step = patched_step
        self._attached_agents.append(agent)

    def _record(self, before: list, after: list) -> None:
        before_text = _extract_text(before)
        after_text = _extract_text(after)
        ghosts = _ghost_terms(before_text, after_text)
        ccs = _ccs_score(before_text, after_text)
        sdist = _semantic_distance(before_text, after_text, self._sbert)
        sid = hashlib.sha1(f"{time.time()}{len(before)}".encode()).hexdigest()[:8]
        session = CompressionSession(
            session_id=sid,
            timestamp=time.time(),
            messages_before=len(before),
            messages_after=len(after),
            ghost_terms=ghosts[:20],
            ccs_score=ccs,
            semantic_distance=sdist,
        )
        self.sessions.append(session)
        self._on_event(session)

    @staticmethod
    def _default_log(session: CompressionSession) -> None:
        label = "⚠️ ALERT" if session.alert else "✓ ok"
        print(
            f"[CamelDrift {session.session_id}] {label} | "
            f"msgs {session.messages_before}→{session.messages_after} | "
            f"CCS={session.ccs_score:.3f} | "
            f"semDist={session.semantic_distance:.3f} | "
            f"ghosts={session.ghost_terms[:5]}"
        )

    def summary(self) -> Dict[str, Any]:
        if not self.sessions:
            return {"events": 0}
        alerts = [s for s in self.sessions if s.alert]
        return {
            "events": len(self.sessions),
            "alerts": len(alerts),
            "avg_ccs": round(sum(s.ccs_score for s in self.sessions) / len(self.sessions), 4),
            "avg_sem_dist": round(sum(s.semantic_distance for s in self.sessions) / len(self.sessions), 4),
            "total_ghosts": sum(len(s.ghost_terms) for s in self.sessions),
        }


# ── Smoke test ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    """
    Offline smoke test using mock messages — no CAMEL install required.
    """
    class MockMessage:
        def __init__(self, content):
            self.content = content

    class MockAgent:
        def __init__(self, messages):
            self.stored_messages = [MockMessage(m) for m in messages]

        def update_memory(self):
            # Simulate truncation: drop oldest half
            self.stored_messages = self.stored_messages[len(self.stored_messages)//2:]

    long_history = [
        "We need to check authentication headers, bcrypt hashing, owasp guidelines",
        "The endpoint validates jwt tokens with hs256 signing",
        "Rate limiting is enforced via redis sliding window, 100req/min",
        "Database schema has user_id, session_token, created_at columns",
        "Recent conversation about deployment infrastructure is here",
    ]
    short_history = [
        "Recent conversation about deployment infrastructure is here",
        "New topic: UI button color and layout padding",
    ]
    agent = MockAgent(long_history + short_history)
    monitor = CamelDriftMonitor()
    monitor.attach(agent)
    agent.update_memory()  # triggers truncation → monitoring
    print("\nSummary:", json.dumps(monitor.summary(), indent=2))
    if monitor.sessions:
        print("Ghost terms:", monitor.sessions[0].ghost_terms[:10])
        print("CCS:", monitor.sessions[0].ccs_score)
        print("Alert:", monitor.sessions[0].alert)
