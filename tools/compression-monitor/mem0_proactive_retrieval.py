"""
mem0 proactive retrieval adapter for compression-monitor.

Addresses mem0ai/mem0#4603: after context compaction, agents stop querying
mem0 for concepts that are still in memory because those concepts are no
longer live in context. The agent doesn't know to ask.

This module:
1. Wraps a MemoryClient to log access events (search queries made over time)
2. Detects ghost vocabulary: high-precision terms used in earlier queries
   that stop appearing in queries post-compaction
3. Can inject proactive memory.search() calls using ghost terms on resume

Usage:
    from mem0_proactive_retrieval import ProactiveMemoryClient

    # Wrap your existing MemoryClient
    mem = ProactiveMemoryClient(user_id="user-123")

    # Use exactly as you would MemoryClient
    mem.add("Using bcrypt with 12 rounds for password hashing", user_id="user-123")
    results = mem.search("bcrypt", user_id="user-123")

    # After a compaction event, recover ghost terms
    ghost_terms = mem.detect_ghost_terms(window_pre=50, window_post=20)
    # -> ["bcrypt", "rate_limit", "UserRepository"]

    # Inject proactive retrieval for ghost terms
    recovered = mem.proactive_retrieve(ghost_terms, user_id="user-123")
    # -> {term: [matching memories], ...}
"""

from __future__ import annotations

import json
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Access event log
# ---------------------------------------------------------------------------

@dataclass
class MemoryAccessEvent:
    """Lightweight record of a single memory operation."""
    operation: str          # "search", "add", "get_all", "update", "delete"
    query: Optional[str]    # search query text when operation="search"
    user_id: Optional[str]
    agent_id: Optional[str]
    timestamp: float        # unix timestamp
    result_count: int = 0
    tokens_in_query: List[str] = field(default_factory=list)


class AccessEventLog:
    """In-memory ring buffer of memory access events with ghost detection."""

    def __init__(self, max_events: int = 2000):
        self.events: List[MemoryAccessEvent] = []
        self.max_events = max_events

    def record(self, event: MemoryAccessEvent) -> None:
        self.events.append(event)
        if len(self.events) > self.max_events:
            self.events = self.events[-self.max_events:]

    def search_queries(self, last_n: Optional[int] = None) -> List[str]:
        """Return query strings from search events."""
        events = self.events[-last_n:] if last_n else self.events
        return [e.query for e in events if e.operation == "search" and e.query]

    def query_token_counts(self, last_n: Optional[int] = None) -> Counter:
        """Return token frequency distribution across search queries."""
        queries = self.search_queries(last_n)
        tokens: List[str] = []
        for q in queries:
            tokens.extend(_tokenize(q))
        return Counter(tokens)

    def detect_ghost_terms(
        self,
        window_pre: int = 100,
        window_post: int = 50,
        min_pre_frequency: int = 2,
        decay_threshold: float = 0.0,
    ) -> List[str]:
        """
        Identify terms that were frequent in pre-compaction queries but
        absent (or nearly absent) in post-compaction queries.

        Parameters
        ----------
        window_pre : int
            Number of recent-minus-post events to treat as "before compaction".
        window_post : int
            Number of most recent events to treat as "after compaction".
        min_pre_frequency : int
            Minimum times a term must appear in the pre window to be considered.
        decay_threshold : float
            Maximum relative frequency in post window to count as ghost (0.0 = fully absent).

        Returns
        -------
        List[str]
            Terms that disappeared after the compaction boundary.
        """
        n = len(self.events)
        if n < window_post + window_pre:
            return []

        mid = n - window_post
        pre_events = self.events[max(0, mid - window_pre):mid]
        post_events = self.events[mid:]

        pre_counts = Counter(
            tok
            for e in pre_events
            if e.operation == "search" and e.query
            for tok in _tokenize(e.query)
        )
        post_counts = Counter(
            tok
            for e in post_events
            if e.operation == "search" and e.query
            for tok in _tokenize(e.query)
        )

        total_post = sum(post_counts.values()) or 1
        ghost_terms = []
        for term, pre_freq in pre_counts.items():
            if pre_freq < min_pre_frequency:
                continue
            post_rel = post_counts.get(term, 0) / total_post
            if post_rel <= decay_threshold:
                ghost_terms.append(term)

        # Sort by pre-frequency descending (most established terms first)
        ghost_terms.sort(key=lambda t: pre_counts[t], reverse=True)
        return ghost_terms

    def save(self, path: str) -> None:
        """Persist event log to JSON for cross-session analysis."""
        data = [
            {
                "op": e.operation,
                "q": e.query,
                "uid": e.user_id,
                "aid": e.agent_id,
                "ts": e.timestamp,
                "rc": e.result_count,
            }
            for e in self.events
        ]
        Path(path).write_text(json.dumps(data, indent=2))

    @classmethod
    def load(cls, path: str) -> "AccessEventLog":
        log = cls()
        data = json.loads(Path(path).read_text())
        for d in data:
            log.events.append(MemoryAccessEvent(
                operation=d["op"],
                query=d.get("q"),
                user_id=d.get("uid"),
                agent_id=d.get("aid"),
                timestamp=d["ts"],
                result_count=d.get("rc", 0),
            ))
        return log


# ---------------------------------------------------------------------------
# Instrumented wrapper around MemoryClient
# ---------------------------------------------------------------------------

class ProactiveMemoryClient:
    """
    Wraps mem0's MemoryClient to:
    - Log all access events (search queries, adds, etc.)
    - Detect ghost vocabulary after compaction boundaries
    - Inject proactive retrieval for ghost terms on demand

    Requires mem0 installed: pip install mem0ai
    Falls back to a no-op stub when mem0 is unavailable (for testing).
    """

    def __init__(
        self,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        log_path: Optional[str] = None,
        max_events: int = 2000,
        api_key: Optional[str] = None,
    ):
        self.user_id = user_id
        self.agent_id = agent_id
        self.log = AccessEventLog(max_events=max_events)
        self.log_path = log_path

        # Load existing log if path provided
        if log_path and Path(log_path).exists():
            self.log = AccessEventLog.load(log_path)

        # Try to import real mem0 client
        try:
            from mem0 import MemoryClient  # type: ignore
            kwargs: Dict[str, Any] = {}
            if api_key:
                kwargs["api_key"] = api_key
            self._client = MemoryClient(**kwargs)
        except ImportError:
            self._client = None

    def _record(self, op: str, query: Optional[str] = None, result_count: int = 0) -> None:
        self.log.record(MemoryAccessEvent(
            operation=op,
            query=query,
            user_id=self.user_id,
            agent_id=self.agent_id,
            timestamp=time.time(),
            result_count=result_count,
        ))
        if self.log_path:
            self.log.save(self.log_path)

    def add(self, messages: Any, **kwargs) -> Any:
        self._record("add")
        if self._client:
            return self._client.add(messages, **kwargs)
        return {"id": "stub"}

    def search(self, query: str, **kwargs) -> Any:
        results = []
        if self._client:
            results = self._client.search(query, **kwargs)
        self._record("search", query=query, result_count=len(results) if results else 0)
        return results

    def get_all(self, **kwargs) -> Any:
        self._record("get_all")
        if self._client:
            return self._client.get_all(**kwargs)
        return []

    def update(self, memory_id: str, data: str, **kwargs) -> Any:
        self._record("update")
        if self._client:
            return self._client.update(memory_id, data, **kwargs)
        return {}

    def delete(self, memory_id: str, **kwargs) -> Any:
        self._record("delete")
        if self._client:
            return self._client.delete(memory_id, **kwargs)
        return {}

    # -----------------------------------------------------------------------
    # Ghost detection and proactive retrieval
    # -----------------------------------------------------------------------

    def detect_ghost_terms(
        self,
        window_pre: int = 100,
        window_post: int = 50,
        min_pre_frequency: int = 2,
    ) -> List[str]:
        """
        Return vocabulary terms that were frequently used in earlier search
        queries but have since gone silent — prime candidates for proactive
        archival lookup.
        """
        return self.log.detect_ghost_terms(
            window_pre=window_pre,
            window_post=window_post,
            min_pre_frequency=min_pre_frequency,
        )

    def proactive_retrieve(
        self,
        ghost_terms: Optional[List[str]] = None,
        window_pre: int = 100,
        window_post: int = 50,
        max_terms: int = 10,
        **search_kwargs: Any,
    ) -> Dict[str, Any]:
        """
        For each ghost term, issue a memory.search() call and return results.

        This closes the detection → recovery loop: the ghost terms are exactly
        the queries the agent should be making but isn't. Calling this on
        session resume re-populates the agent's active context with concepts
        that were evicted.

        Parameters
        ----------
        ghost_terms : list, optional
            Explicit list of terms. If None, detect automatically.
        window_pre / window_post : int
            Passed to detect_ghost_terms if ghost_terms is None.
        max_terms : int
            Cap on how many ghost terms to retrieve for (to limit API calls).

        Returns
        -------
        dict
            {term: [matching_memories], ...}
        """
        if ghost_terms is None:
            ghost_terms = self.detect_ghost_terms(window_pre=window_pre, window_post=window_post)

        ghost_terms = ghost_terms[:max_terms]
        results: Dict[str, Any] = {}

        uid = search_kwargs.pop("user_id", self.user_id)
        for term in ghost_terms:
            kwargs = dict(search_kwargs)
            if uid:
                kwargs["user_id"] = uid
            results[term] = self.search(term, **kwargs)

        return results

    def session_health_report(self) -> Dict[str, Any]:
        """
        Summarize memory access patterns for the current session.
        Returns ghost terms, query entropy, and access counts.
        """
        total = len(self.log.events)
        searches = [e for e in self.log.events if e.operation == "search"]
        ghost_terms = self.detect_ghost_terms()

        pre_half = len(searches) // 2
        pre_tokens = Counter(
            tok for e in searches[:pre_half] if e.query for tok in _tokenize(e.query)
        )
        post_tokens = Counter(
            tok for e in searches[pre_half:] if e.query for tok in _tokenize(e.query)
        )

        return {
            "total_events": total,
            "total_searches": len(searches),
            "unique_query_terms_pre": len(pre_tokens),
            "unique_query_terms_post": len(post_tokens),
            "vocabulary_compression": (
                1.0 - len(post_tokens) / max(len(pre_tokens), 1)
            ),
            "ghost_terms": ghost_terms,
            "ghost_count": len(ghost_terms),
        }


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

_STOP = frozenset({
    "a", "an", "the", "and", "or", "for", "in", "on", "at", "to",
    "is", "are", "was", "were", "be", "been", "have", "has", "do",
    "does", "did", "will", "would", "could", "should", "may", "might",
    "of", "with", "from", "by", "as", "it", "this", "that", "i",
    "my", "your", "we", "our", "they", "their", "what", "which",
})


def _tokenize(text: str) -> List[str]:
    """Simple whitespace + punctuation tokenizer; removes stop words."""
    import re
    tokens = re.findall(r"[a-z_][a-z0-9_]*", text.lower())
    return [t for t in tokens if t not in _STOP and len(t) >= 3]


# ---------------------------------------------------------------------------
# CLI smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import random

    print("=== mem0 Proactive Retrieval Smoke Test ===")
    print("(no real mem0 client needed — using stub mode)\n")

    mem = ProactiveMemoryClient(user_id="test-user")

    # Simulate pre-compaction searches with domain-specific vocabulary
    pre_session_queries = [
        "bcrypt password hashing configuration",
        "UserRepository dependency injection",
        "rate_limit_strategy middleware",
        "bcrypt rounds security",
        "UserRepository interface methods",
        "owasp authentication guidelines",
        "bcrypt salt generation",
        "dependency injection container setup",
        "rate_limit_strategy token bucket",
    ]

    print("Simulating pre-compaction search queries...")
    for q in pre_session_queries:
        mem.search(q, user_id="test-user")

    # Simulate post-compaction searches — agent drifted to generic queries
    post_session_queries = [
        "authentication setup",
        "middleware configuration",
        "security best practices",
        "user management",
        "api rate limiting",
    ]

    print("Simulating post-compaction search queries (context narrowed)...\n")
    for q in post_session_queries:
        mem.search(q, user_id="test-user")

    # Use small windows that fit within the 14-event demo session
    ghost_terms = mem.detect_ghost_terms(window_pre=9, window_post=5, min_pre_frequency=2)

    # Manual session health summary
    searches = [e for e in mem.log.events if e.operation == "search"]
    pre_half = len(searches) // 2
    from collections import Counter as _Counter
    pre_tokens = _Counter(
        tok for e in searches[:pre_half] if e.query for tok in _tokenize(e.query)
    )
    post_tokens = _Counter(
        tok for e in searches[pre_half:] if e.query for tok in _tokenize(e.query)
    )
    vocab_compression = 1.0 - len(post_tokens) / max(len(pre_tokens), 1)

    print("Session health report:")
    print(f"  Total searches: {len(searches)}")
    print(f"  Vocabulary compression: {vocab_compression:.1%}")
    print(f"  Ghost terms detected: {len(ghost_terms)}")
    print(f"  Ghost terms: {ghost_terms[:10]}")

    print("\nProactive retrieval would trigger searches for:")
    for term in ghost_terms[:5]:
        print(f"  memory.search('{term}', user_id='test-user')")
