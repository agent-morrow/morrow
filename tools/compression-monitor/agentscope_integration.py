"""
agentscope_integration.py — compression-monitor adapter for agentscope-ai/agentscope

Hooks into AgentScope's agent messaging layer to detect behavioral drift at
context management boundaries (token overflow, history truncation, compaction).

AgentScope promises agents you can "see, understand and trust." This adapter
makes the behavioral state of an agent visible across context boundaries —
specifically, when truncation or history reset causes the agent to stop talking
about things it was tracking before.

Usage:
    from agentscope_integration import install_drift_monitor, AgentScopeDriftMonitor

    monitor = AgentScopeDriftMonitor()
    monitor.attach(agent)               # wraps agent.reply()
    monitor.snapshot_vocabulary(text)   # call before a long session
    report = monitor.report()

Design:
    - Wraps AgentBase.reply() to snapshot input message vocabulary
    - After each reply, measures ghost lexicon decay and semantic drift
    - Emits DriftEvent dicts compatible with compression-monitor baseline format

Requirements:
    pip install agentscope sentence-transformers
"""

from __future__ import annotations

import functools
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set


# ---------------------------------------------------------------------------
# Ghost lexicon + semantic distance (zero external deps for the core)
# ---------------------------------------------------------------------------

def _tokenize(text: str) -> Set[str]:
    import re
    return set(re.findall(r"[a-zA-Z_][a-zA-Z0-9_]{3,}", text.lower()))


def _cosine_sim(a: List[float], b: List[float]) -> float:
    import math
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x**2 for x in a))
    nb = math.sqrt(sum(x**2 for x in b))
    if na == 0 or nb == 0:
        return 1.0
    return dot / (na * nb)


@dataclass
class DriftEvent:
    timestamp: float
    agent_name: str
    ghost_rate: float
    semantic_distance: float
    pre_token_count: int
    post_token_count: int
    ghost_terms: List[str] = field(default_factory=list)
    severity: str = "ok"

    def to_dict(self) -> Dict[str, Any]:
        return self.__dict__.copy()


# ---------------------------------------------------------------------------
# Drift monitor
# ---------------------------------------------------------------------------

class AgentScopeDriftMonitor:
    """
    Attaches to an AgentScope AgentBase instance and measures behavioral drift
    at context management boundaries.

    Compatible with AgentScope 0.x (reply-based API).
    """

    GHOST_WARN = 0.15
    GHOST_ALERT = 0.35
    SEM_WARN = 0.08
    SEM_ALERT = 0.20

    def __init__(self, embed_model: str = "all-MiniLM-L6-v2"):
        self.embed_model = embed_model
        self._embedder: Optional[Any] = None
        self._pre_vocab: Set[str] = set()
        self._pre_text: str = ""
        self._pre_tokens: int = 0
        self._events: List[DriftEvent] = []
        self._agent_name: str = "unknown"

    def _get_embedder(self):
        if self._embedder is None:
            try:
                from sentence_transformers import SentenceTransformer
                self._embedder = SentenceTransformer(self.embed_model)
            except ImportError:
                self._embedder = None
        return self._embedder

    def _embed(self, text: str) -> List[float]:
        emb = self._get_embedder()
        if emb is None:
            return []
        return emb.encode(text, show_progress_bar=False).tolist()

    # ------------------------------------------------------------------
    def snapshot_vocabulary(self, text: str) -> None:
        """Baseline the vocabulary before a context management event."""
        self._pre_vocab = _tokenize(text)
        self._pre_text = text
        self._pre_tokens = len(text.split())

    def measure_drift(self, post_text: str) -> DriftEvent:
        post_vocab = _tokenize(post_text)
        post_tokens = len(post_text.split())

        if self._pre_vocab:
            ghost = self._pre_vocab - post_vocab
            ghost_rate = len(ghost) / max(len(self._pre_vocab), 1)
            ghost_terms = sorted(ghost)[:20]
        else:
            ghost_rate, ghost_terms = 0.0, []

        if self._pre_text and post_text:
            pre_emb = self._embed(self._pre_text)
            post_emb = self._embed(post_text)
            sem_dist = 1.0 - _cosine_sim(pre_emb, post_emb) if (pre_emb and post_emb) else 0.0
        else:
            sem_dist = 0.0

        if ghost_rate >= self.GHOST_ALERT or sem_dist >= self.SEM_ALERT:
            severity = "alert"
        elif ghost_rate >= self.GHOST_WARN or sem_dist >= self.SEM_WARN:
            severity = "warning"
        else:
            severity = "ok"

        event = DriftEvent(
            timestamp=time.time(),
            agent_name=self._agent_name,
            ghost_rate=round(ghost_rate, 4),
            semantic_distance=round(sem_dist, 4),
            pre_token_count=self._pre_tokens,
            post_token_count=post_tokens,
            ghost_terms=ghost_terms,
            severity=severity,
        )
        self._events.append(event)
        return event

    # ------------------------------------------------------------------
    def attach(self, agent: Any) -> None:
        """
        Wrap agent.reply() to auto-monitor vocabulary across turns.

        Compatible with AgentScope's AgentBase.reply(x: Msg) -> Msg API.
        """
        self._agent_name = getattr(agent, "name", type(agent).__name__)
        original_reply = agent.reply
        monitor = self

        @functools.wraps(original_reply)
        def patched_reply(x=None, **kwargs):
            # Extract text from input Msg
            if x is not None:
                content = getattr(x, "content", str(x))
                if isinstance(content, str) and content:
                    monitor.snapshot_vocabulary(content)

            result = original_reply(x, **kwargs)

            # Measure drift on output
            if result is not None:
                out_content = getattr(result, "content", str(result))
                if isinstance(out_content, str) and out_content:
                    event = monitor.measure_drift(out_content)
                    if event.severity != "ok":
                        print(
                            f"[compression-monitor] {monitor._agent_name} "
                            f"{event.severity.upper()} "
                            f"ghost={event.ghost_rate:.3f} "
                            f"sem_dist={event.semantic_distance:.3f} "
                            f"top_ghost={event.ghost_terms[:5]}"
                        )
            return result

        agent.reply = patched_reply

    # ------------------------------------------------------------------
    def report(self) -> Dict[str, Any]:
        events = self._events
        if not events:
            return {"status": "no_data", "agent": self._agent_name, "events": 0}
        alerts = [e for e in events if e.severity == "alert"]
        warnings = [e for e in events if e.severity == "warning"]
        return {
            "status": "alert" if alerts else ("warning" if warnings else "ok"),
            "agent": self._agent_name,
            "events": len(events),
            "alerts": len(alerts),
            "warnings": len(warnings),
            "avg_ghost_rate": round(sum(e.ghost_rate for e in events) / len(events), 4),
            "avg_sem_dist": round(sum(e.semantic_distance for e in events) / len(events), 4),
            "latest": events[-1].to_dict(),
        }


# ---------------------------------------------------------------------------
# One-liner install
# ---------------------------------------------------------------------------

def install_drift_monitor(
    agent: Any,
    embed_model: str = "all-MiniLM-L6-v2",
) -> AgentScopeDriftMonitor:
    """Wrap an AgentScope agent and return the monitor."""
    monitor = AgentScopeDriftMonitor(embed_model=embed_model)
    monitor.attach(agent)
    return monitor


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    monitor = AgentScopeDriftMonitor()

    pre = (
        "The authentication service uses bcrypt with cost factor 12. "
        "Rate limiting is OWASP-compliant: 5 requests per 10 minutes. "
        "The JWT refresh token rotation policy was last reviewed in Q3."
    )
    monitor.snapshot_vocabulary(pre)

    post = (
        "I can help you design a REST API. What endpoints do you need? "
        "We could start with a users resource and then add authentication later."
    )
    event = monitor.measure_drift(post)

    print(f"Ghost rate:        {event.ghost_rate:.3f}")
    print(f"Semantic distance: {event.semantic_distance:.3f}")
    print(f"Ghost terms:       {event.ghost_terms[:8]}")
    print(f"Severity:          {event.severity}")

    assert event.ghost_rate > 0.5, "Expected high ghost rate"
    assert event.severity in ("warning", "alert"), "Expected warning or alert"
    print("\nSelf-test passed.")
