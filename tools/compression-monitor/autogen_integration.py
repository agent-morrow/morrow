"""
autogen_integration.py — Behavioral consistency monitor for AutoGen agents

Detects vocabulary drift and topic reorientation when AutoGen's message history
grows long enough to trigger summarization or truncation. Compatible with both
autogen-agentchat (0.4.x) and the legacy autogen (0.2.x) message dict format.

Usage
-----
    from autogen_integration import AutoGenConsistencyMonitor

    monitor = AutoGenConsistencyMonitor()

    # After any agent step, pass the current message list:
    result = monitor.check(messages)
    if result["drift_detected"]:
        print("Behavioral drift at turn", result["turn"])
        print("Ghost terms:", result["ghost_terms"])
        print("CCS:", result["ccs"])

    # Or wrap an AssistantAgent reply with a decorator:
    monitor.patch_agent(agent)  # patches agent.generate_reply in-place

Ghost Consistency Score (CCS)
------------------------------
CCS measures what fraction of vocabulary present in the first window of
messages is still present in the latest window. Score < 0.4 indicates
significant topic or vocabulary drift after a compression event.

Unretrieved-gap flag
--------------------
If ghost terms (words dropped from recent context) include semantically
important tokens for the current task, the agent may continue operating
without access to facts it introduced itself. unretrieved_gap=True is a
signal that the agent should be prompted to self-query its memory.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any, Dict, List, Optional, Sequence


# ---------------------------------------------------------------------------
# Ghost lexicon: terms that should persist unless actively compressed away
# ---------------------------------------------------------------------------
GHOST_LEXICON: List[str] = [
    # auth / security
    "jwt", "oauth", "token", "bearer", "api_key", "secret", "credential",
    "bcrypt", "hash", "salt", "certificate", "tls", "ssl",
    # data / storage
    "database", "schema", "migration", "index", "foreign_key", "transaction",
    "redis", "postgres", "sqlite", "mongo", "vector",
    # agent-specific
    "memory", "context", "retrieval", "embedding", "chunk", "summarize",
    "tool_call", "function_call", "handoff", "termination",
    # infra
    "deploy", "container", "docker", "kubernetes", "endpoint", "webhook",
    "rate_limit", "timeout", "retry",
]

# Minimum word length to track as vocabulary
_MIN_WORD_LEN = 4
# Fraction of earliest turns to use as baseline
_BASELINE_FRAC = 0.25
# Fraction of latest turns to use as current window
_CURRENT_FRAC = 0.25


def _tokenize(text: str) -> Counter:
    words = re.findall(r"[a-z_]{%d,}" % _MIN_WORD_LEN, text.lower())
    return Counter(words)


def _extract_content(msg: Any) -> str:
    """Extract text content from an AutoGen message (dict or dataclass)."""
    if isinstance(msg, dict):
        content = msg.get("content", "")
        if isinstance(content, list):
            # AutoGen 0.4 multimodal: list of TextMessage/Image parts
            parts = []
            for part in content:
                if isinstance(part, dict):
                    parts.append(part.get("text", ""))
                elif hasattr(part, "text"):
                    parts.append(part.text)
                else:
                    parts.append(str(part))
            return " ".join(parts)
        return str(content or "")
    # autogen-agentchat 0.4.x: TextMessage / MultiModalMessage / ToolCallMessage
    for attr in ("content", "text", "body"):
        val = getattr(msg, attr, None)
        if val is not None:
            if isinstance(val, list):
                return " ".join(
                    (p.text if hasattr(p, "text") else str(p)) for p in val
                )
            return str(val)
    return str(msg)


class AutoGenConsistencyMonitor:
    """
    Stateless per-call consistency checker for AutoGen message histories.

    Parameters
    ----------
    ghost_lexicon : list[str], optional
        Override the default ghost-term vocabulary.
    ccs_threshold : float
        Ghost Consistency Score below this value triggers drift_detected=True.
    min_messages : int
        Minimum number of messages before checks run (avoids false positives
        on short conversations).
    """

    def __init__(
        self,
        ghost_lexicon: Optional[List[str]] = None,
        ccs_threshold: float = 0.40,
        min_messages: int = 6,
    ) -> None:
        self.ghost_lexicon = ghost_lexicon or GHOST_LEXICON
        self.ccs_threshold = ccs_threshold
        self.min_messages = min_messages

    # ------------------------------------------------------------------
    def check(self, messages: Sequence[Any]) -> Dict[str, Any]:
        """
        Analyse a message list and return a consistency report.

        Returns
        -------
        dict with keys:
            drift_detected : bool
            ccs            : float  (Ghost Consistency Score)
            ghost_terms    : list[str]  (terms dropped from recent context)
            unretrieved_gap: bool
            turn           : int    (len(messages))
            baseline_vocab : int
            current_vocab  : int
        """
        n = len(messages)
        result: Dict[str, Any] = {
            "drift_detected": False,
            "ccs": 1.0,
            "ghost_terms": [],
            "unretrieved_gap": False,
            "turn": n,
            "baseline_vocab": 0,
            "current_vocab": 0,
        }

        if n < self.min_messages:
            return result

        cutoff_b = max(1, int(n * _BASELINE_FRAC))
        cutoff_c = max(1, int(n * _CURRENT_FRAC))

        baseline_text = " ".join(_extract_content(m) for m in messages[:cutoff_b])
        current_text = " ".join(_extract_content(m) for m in messages[-cutoff_c:])

        baseline_vocab = _tokenize(baseline_text)
        current_vocab = _tokenize(current_text)

        result["baseline_vocab"] = len(baseline_vocab)
        result["current_vocab"] = len(current_vocab)

        if not baseline_vocab:
            return result

        shared = sum(
            1 for w in baseline_vocab if w in current_vocab
        )
        ccs = shared / len(baseline_vocab)
        result["ccs"] = round(ccs, 3)

        # Ghost terms: lexicon items present in baseline but absent from current
        ghost_terms = [
            term for term in self.ghost_lexicon
            if baseline_vocab.get(term, 0) > 0
            and current_vocab.get(term, 0) == 0
        ]
        result["ghost_terms"] = ghost_terms
        result["unretrieved_gap"] = len(ghost_terms) > 0

        if ccs < self.ccs_threshold or ghost_terms:
            result["drift_detected"] = True

        return result

    # ------------------------------------------------------------------
    def patch_agent(self, agent: Any) -> None:
        """
        Monkey-patch an AutoGen AssistantAgent (or compatible agent) so that
        after every generate_reply call a consistency check runs automatically.

        Prints a warning to stderr when drift is detected.
        """
        import sys
        original = agent.generate_reply

        monitor = self

        def _patched(*args, **kwargs):
            reply = original(*args, **kwargs)
            # Retrieve message history from the agent
            msgs = []
            for attr in ("chat_messages", "_oai_messages", "messages"):
                candidate = getattr(agent, attr, None)
                if candidate is None:
                    continue
                if isinstance(candidate, dict):
                    # chat_messages is keyed by recipient agent
                    for v in candidate.values():
                        msgs = list(v)
                        break
                elif isinstance(candidate, list):
                    msgs = list(candidate)
                if msgs:
                    break
            if msgs:
                result = monitor.check(msgs)
                if result["drift_detected"]:
                    print(
                        f"[AutoGenConsistencyMonitor] ⚠ drift at turn {result['turn']}: "
                        f"CCS={result['ccs']:.3f}, ghost={result['ghost_terms']}",
                        file=sys.stderr,
                    )
            return reply

        agent.generate_reply = _patched


# ---------------------------------------------------------------------------
# Standalone demo
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Simulate a message history where early context has been summarised away
    early_messages = [
        {"role": "user", "content": "Use jwt and bcrypt for authentication. Store tokens in redis."},
        {"role": "assistant", "content": "Sure. I'll set up jwt token validation with bcrypt password hashing and redis token store."},
        {"role": "user", "content": "Make sure the schema migration handles foreign_key constraints properly."},
        {"role": "assistant", "content": "Database migration will preserve all foreign_key relationships and add an index on the token column."},
    ]
    late_messages = [
        {"role": "user", "content": "Now add the endpoint for user profile updates."},
        {"role": "assistant", "content": "Adding a PATCH /profile endpoint with input validation."},
        {"role": "user", "content": "What about rate limiting?"},
        {"role": "assistant", "content": "I'll add middleware for rate_limit on the endpoint."},
    ]
    messages = early_messages + late_messages

    monitor = AutoGenConsistencyMonitor(min_messages=4)
    result = monitor.check(messages)

    print("=== AutoGen Consistency Monitor — self-test ===")
    print(f"CCS                : {result['ccs']}")
    print(f"Ghost terms        : {result['ghost_terms']}")
    print(f"Unretrieved gap    : {result['unretrieved_gap']}")
    print(f"Drift detected     : {result['drift_detected']}")
    print(f"Turn               : {result['turn']}")
