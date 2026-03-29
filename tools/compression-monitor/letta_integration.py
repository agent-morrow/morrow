"""
letta_integration.py — Behavioral drift monitor for Letta (MemGPT) agents.

Detects ghost vocabulary decay, tool-call shift, and archival_memory_search
underuse at the in-context → archival eviction boundary.

The Letta-specific insight: evicted messages are NOT lost — they're in archival.
The failure mode is that the agent stops knowing to retrieve them. Ghost terms
(precision vocabulary that went quiet after eviction) are exactly the archival
queries the agent should be making but isn't.

Usage:
    monitor = LettaBehaviorMonitor(agent_id="agent-xxx")

    # Record each step (before and after eviction):
    monitor.record_step(step_index=i, tool_calls=["read", "send_message"],
                        message_content="Reviewing AuthService JWT logic...")

    # Mark the eviction boundary (before post-eviction steps):
    monitor.mark_eviction(step_index=40, evicted_count=15, strategy="summarize_discard")

    # After recording more post-eviction steps, compute drift:
    report = monitor.compute_drift(eviction_index=40)
    if report.alert:
        for q in report.ghost_lexicon:
            print(f"Run: archival_memory_search('{q}')")

See: https://github.com/letta-ai/letta/issues/3259
     https://github.com/agent-morrow/compression-monitor
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional, Set


_STOP = frozenset(
    "a an the is are was were be been being have has had do does did "
    "will would could should may might shall can need must to of in on "
    "at by for with as from into about like after before and or not but "
    "if then so that it its this those these they them their there here "
    "he she we you i me my your our agent letta memory archival".split()
)


def _tokenize(text: str) -> List[str]:
    return [t for t in re.findall(r"[a-z][a-z0-9_]{3,}", text.lower()) if t not in _STOP]


def _precision_vocab(texts: List[str], min_freq: int = 2, top_n: int = 5) -> Set[str]:
    freq: Counter = Counter()
    for t in texts:
        freq.update(set(_tokenize(t)))
    candidates = {w for w, c in freq.items() if c >= min_freq}
    if not candidates:
        return set()
    by_freq = sorted(candidates, key=lambda w: freq[w])
    return set(by_freq[: max(1, len(by_freq) - top_n)][:40])


@dataclass
class AgentStep:
    index: int
    tool_calls: List[str]
    message_content: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class EvictionBoundary:
    step_index: int
    evicted_count: int
    strategy: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class EvictionDriftReport:
    step_index: int
    ccs: float
    ghost_rate: float
    archival_search_rate_pre: float
    archival_search_rate_post: float
    tool_jaccard_distance: float
    ghost_lexicon: List[str]     # recommended archival_memory_search queries
    unretrieved_gap: bool
    alert: bool
    alert_threshold: float

    def summary(self) -> str:
        lines = [
            f"Letta CCS @ eviction step {self.step_index}: {self.ccs:.3f} "
            f"({'DRIFT ALERT' if self.alert else 'OK'})",
            f"  Ghost lexicon decay:           {self.ghost_rate:.0%}",
            f"  Archival search rate pre:      {self.archival_search_rate_pre:.0%}",
            f"  Archival search rate post:     {self.archival_search_rate_post:.0%}",
            f"  Tool sequence distance:        {self.tool_jaccard_distance:.0%}",
            f"  Unretrieved gap:               {self.unretrieved_gap}",
        ]
        if self.ghost_lexicon:
            lines.append(f"  Recommended archival queries:  {', '.join(self.ghost_lexicon[:8])}")
        return "\n".join(lines)


class LettaBehaviorMonitor:
    """
    Monitors behavioral consistency of a Letta agent across
    in-context -> archival eviction boundaries.

    CCS weights: ghost_lexicon 0.45 | semantic 0.30 | tool_stability 0.25

    Key difference from other framework integrations: ghost terms are surfaced
    as recommended archival_memory_search queries, closing the loop from
    detection back to recovery.
    """

    GHOST_W, SEMANTIC_W, TOOL_W = 0.45, 0.30, 0.25

    def __init__(self, agent_id: str, alert_threshold: float = 0.75, window_size: int = 20):
        self.agent_id = agent_id
        self.alert_threshold = alert_threshold
        self.window_size = window_size
        self.steps: List[AgentStep] = []
        self.evictions: List[EvictionBoundary] = []

    def record_step(self, step_index: int, tool_calls: Optional[List[str]] = None,
                    message_content: str = "") -> None:
        self.steps.append(AgentStep(index=step_index,
                                    tool_calls=tool_calls or [],
                                    message_content=message_content))

    def mark_eviction(self, step_index: int, evicted_count: int = 0,
                      strategy: str = "unknown") -> None:
        """Record an eviction boundary. Drift is computed lazily via compute_drift()."""
        self.evictions.append(EvictionBoundary(
            step_index=step_index, evicted_count=evicted_count, strategy=strategy))

    def compute_drift(self, eviction_index: int) -> EvictionDriftReport:
        """Compute drift at a given eviction boundary using all currently recorded steps."""
        ws = self.window_size
        pre = [s for s in self.steps if s.index < eviction_index][-ws:]
        post = [s for s in self.steps if s.index >= eviction_index][:ws]

        if not pre or not post:
            return EvictionDriftReport(
                step_index=eviction_index, ccs=1.0, ghost_rate=0.0,
                archival_search_rate_pre=0.0, archival_search_rate_post=0.0,
                tool_jaccard_distance=0.0, ghost_lexicon=[],
                unretrieved_gap=False, alert=False, alert_threshold=self.alert_threshold)

        pre_texts = [s.message_content for s in pre]
        post_texts = [s.message_content for s in post]
        pre_vocab = _precision_vocab(pre_texts)
        post_tokens: set = set()
        for t in post_texts:
            post_tokens.update(_tokenize(t))

        ghost_rate = (1.0 - len(pre_vocab & post_tokens) / len(pre_vocab)) if pre_vocab else 0.0
        ghost_lexicon = sorted(pre_vocab - post_tokens) if pre_vocab else []

        def archival_rate(steps: List[AgentStep]) -> float:
            return (sum(1 for s in steps if "archival_memory_search" in s.tool_calls)
                    / len(steps)) if steps else 0.0

        pre_rate = archival_rate(pre)
        post_rate = archival_rate(post)
        unretrieved_gap = bool(ghost_lexicon) and post_rate <= pre_rate

        pre_tools: Counter = Counter(t for s in pre for t in s.tool_calls)
        post_tools: Counter = Counter(t for s in post for t in s.tool_calls)
        all_tools = set(pre_tools) | set(post_tools)
        if all_tools:
            inter = sum(min(pre_tools[t], post_tools[t]) for t in all_tools)
            union_ = sum(max(pre_tools[t], post_tools[t]) for t in all_tools)
            tool_jaccard = 1.0 - inter / union_ if union_ else 0.0
        else:
            tool_jaccard = 0.0

        pre_kw = set(_tokenize(" ".join(pre_texts)))
        post_kw = set(_tokenize(" ".join(post_texts)))
        union_kw = pre_kw | post_kw
        sem_overlap = len(pre_kw & post_kw) / len(union_kw) if union_kw else 1.0

        ccs = (self.GHOST_W * (1.0 - ghost_rate)
               + self.SEMANTIC_W * sem_overlap
               + self.TOOL_W * (1.0 - tool_jaccard))

        return EvictionDriftReport(
            step_index=eviction_index, ccs=ccs, ghost_rate=ghost_rate,
            archival_search_rate_pre=pre_rate, archival_search_rate_post=post_rate,
            tool_jaccard_distance=tool_jaccard, ghost_lexicon=ghost_lexicon[:15],
            unretrieved_gap=unretrieved_gap, alert=ccs < self.alert_threshold,
            alert_threshold=self.alert_threshold)

    def recommended_archival_queries(self) -> List[str]:
        """Ghost terms from the most recent eviction — run these as archival_memory_search queries."""
        if not self.evictions:
            return []
        return self.compute_drift(self.evictions[-1].step_index).ghost_lexicon

    def session_report(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "total_steps": len(self.steps),
            "eviction_count": len(self.evictions),
            "boundary_reports": [
                {k: round(v, 4) if isinstance(v, float) else v
                 for k, v in vars(self.compute_drift(e.step_index)).items()}
                for e in self.evictions
            ],
        }


if __name__ == "__main__":
    import json

    monitor = LettaBehaviorMonitor(agent_id="agent-self-test", alert_threshold=0.75)

    for i, (tools, content) in enumerate([
        (["read", "send_message"],
         "AuthService class — JWT validation, bcryptRounds=12, UserRepository injection"),
        (["archival_memory_search", "send_message"],
         "AuthService constructor requires UserRepository and TokenStore via dependency injection"),
        (["write", "send_message"],
         "Fix bcryptRounds in AuthService.hash_password — OWASP minimum is 12"),
        (["read", "send_message"],
         "UserRepository interface — getUserById, createUser, updatePassword signatures"),
        (["write", "archival_memory_search"],
         "Add TokenStore dependency to AuthService constructor injection pattern"),
        (["send_message"],
         "AuthService.validate_token — decode JWT, expiry check, bcrypt verify via UserRepository"),
        (["read", "write"],
         "Update AuthService tests with mock UserRepository and TokenStore via DI"),
        (["send_message"],
         "DI pattern enforced: inject through constructor, no globals, testable isolation"),
        (["archival_memory_search"],
         "Checking archival for bcrypt OWASP password hashing standards bcryptRounds"),
        (["write", "send_message"],
         "All AuthService methods use injected UserRepository — no direct database access"),
    ]):
        monitor.record_step(step_index=i, tool_calls=tools, message_content=content)

    monitor.mark_eviction(step_index=10, evicted_count=8, strategy="summarize_discard")

    for i, (tools, content) in enumerate([
        (["read", "send_message"], "Looking at the codebase structure — what files exist"),
        (["send_message"], "Working on database connection layer — connect to PostgreSQL"),
        (["write"], "Add database connection pool with environment variable configuration"),
        (["send_message"], "Checking if any tests exist in the test directory"),
        (["read", "send_message"], "Reading configuration file for environment variables"),
        (["write"], "Update env loading to use dotenv for local development"),
        (["send_message"], "Adding error handling for missing environment variables"),
        (["write"], "Create generic repository base class for CRUD operations"),
        (["send_message"], "Setting up Docker configuration for the database service"),
        (["read"], "Reviewing docker-compose.yml structure"),
    ]):
        monitor.record_step(step_index=i + 10, tool_calls=tools, message_content=content)

    report = monitor.compute_drift(eviction_index=10)
    print(report.summary())
    print()
    queries = monitor.recommended_archival_queries()
    print(f"Recommended archival queries ({len(queries)}):")
    for q in queries:
        print(f"  archival_memory_search('{q}')")

    assert report.alert, f"Expected drift alert, CCS={report.ccs:.3f}"
    assert report.unretrieved_gap, "Expected unretrieved gap"
    assert len(queries) > 3, f"Expected multiple queries, got {len(queries)}"
    print("\nSelf-test passed.")
