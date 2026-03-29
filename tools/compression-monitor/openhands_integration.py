"""
openhands_integration.py — Behavioral drift monitor for OpenHands coding agents.

Attaches to OpenHands' event stream and detects behavioral shift at context
truncation boundaries using ghost lexicon decay, tool-call sequence divergence,
and semantic topic drift.

Usage (in OpenHands session or observer callback):
    monitor = OpenHandsConsistencyMonitor(session_id="my-coding-task")

    # Record each agent step:
    monitor.record_step(
        step_index=step_num,
        action_type=action.action,          # "run", "read", "write", "browse", etc.
        content=action.content or "",
        observations=[obs.content for obs in observations],
    )

    # On ContextTruncationEvent (when issue #13644 is implemented):
    monitor.on_truncation_event(step_index=step_num)

    # Or: compare windows manually at any step:
    report = monitor.check_drift(window_size=20)
    if report.alert:
        print(f"Drift detected at step {step_num}: CCS={report.ccs:.3f}")
        print("Ghost terms lost:", report.ghost_lexicon)

See: https://github.com/All-Hands-AI/OpenHands/issues/13644
     https://github.com/agent-morrow/compression-monitor
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional


# ---------------------------------------------------------------------------
# Tokenizer (no external deps)
# ---------------------------------------------------------------------------

_STOP = frozenset(
    "a an the is are was were be been being have has had do does did "
    "will would could should may might shall can need must to of in on "
    "at by for with as from into about like after before and or not but "
    "if then so that it its this those these they them their there here "
    "he she we you i me my your our".split()
)

def _tokenize(text: str) -> List[str]:
    tokens = re.findall(r"[a-z][a-z0-9_]{3,}", text.lower())
    return [t for t in tokens if t not in _STOP]


def _precision_vocab(texts: List[str], top_n: int = 5) -> set:
    """Return the most discriminative (low-frequency) vocabulary across texts."""
    freq: Counter = Counter()
    for t in texts:
        freq.update(set(_tokenize(t)))
    if not freq:
        return set()
    # Keep terms that appear in at least 2 texts (signal), filter top_n most
    # common (too generic), return the rest up to a reasonable cap
    candidates = {w for w, c in freq.items() if c >= 2}
    if not candidates:
        return set()
    by_freq = sorted(candidates, key=lambda w: freq[w])
    # Drop the top_n most common as generic; keep the rest (up to 30)
    trimmed = by_freq[: max(1, len(by_freq) - top_n)]
    return set(trimmed[:30])


# ---------------------------------------------------------------------------
# Step record
# ---------------------------------------------------------------------------

@dataclass
class AgentStep:
    index: int
    action_type: str       # "run", "read", "write", "browse", "message", etc.
    content: str
    observations: List[str]
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Drift report
# ---------------------------------------------------------------------------

@dataclass
class DriftReport:
    step_index: int
    ccs: float
    ghost_rate: float
    tool_jaccard_distance: float
    semantic_overlap: float
    ghost_lexicon: List[str]
    alert: bool
    alert_threshold: float
    window_size: int

    def summary(self) -> str:
        lines = [
            f"OpenHands CCS @ step {self.step_index}: {self.ccs:.3f} "
            f"({'DRIFT ALERT' if self.alert else 'OK'})",
            f"  Ghost lexicon decay:    {self.ghost_rate:.0%}",
            f"  Tool sequence distance: {self.tool_jaccard_distance:.0%}",
            f"  Semantic overlap:       {self.semantic_overlap:.0%}",
        ]
        if self.ghost_lexicon:
            lines.append(f"  Lost precision terms:   {', '.join(self.ghost_lexicon[:10])}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Monitor
# ---------------------------------------------------------------------------

class OpenHandsConsistencyMonitor:
    """
    Monitors behavioral consistency of an OpenHands coding agent across
    context truncation boundaries.

    Records each agent step, then computes a Context-Consistency Score (CCS)
    comparing a pre-boundary window against a post-boundary window.

    Weights:
        ghost_lexicon_retention   0.45
        semantic_overlap          0.30
        tool_stability (jaccard)  0.25
    """

    GHOST_W = 0.45
    SEMANTIC_W = 0.30
    TOOL_W = 0.25

    def __init__(
        self,
        session_id: str,
        alert_threshold: float = 0.75,
        window_size: int = 20,
    ):
        self.session_id = session_id
        self.alert_threshold = alert_threshold
        self.default_window_size = window_size
        self.steps: List[AgentStep] = []
        self.truncation_boundaries: List[int] = []

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def record_step(
        self,
        step_index: int,
        action_type: str,
        content: str = "",
        observations: Optional[List[str]] = None,
    ) -> None:
        self.steps.append(
            AgentStep(
                index=step_index,
                action_type=action_type,
                content=content,
                observations=observations or [],
            )
        )

    def on_truncation_event(self, step_index: int) -> DriftReport:
        """
        Call this when OpenHands emits a ContextTruncationEvent.
        Compares the window before and after the boundary.
        """
        self.truncation_boundaries.append(step_index)
        return self.check_drift(at_step=step_index)

    # ------------------------------------------------------------------
    # Drift computation
    # ------------------------------------------------------------------

    def check_drift(
        self,
        at_step: Optional[int] = None,
        window_size: Optional[int] = None,
    ) -> DriftReport:
        ws = window_size or self.default_window_size
        pivot = at_step if at_step is not None else (self.steps[-1].index if self.steps else 0)

        pre = [s for s in self.steps if s.index < pivot][-ws:]
        post = [s for s in self.steps if s.index >= pivot][:ws]

        if not pre or not post:
            return DriftReport(
                step_index=pivot, ccs=1.0,
                ghost_rate=0.0, tool_jaccard_distance=0.0, semantic_overlap=1.0,
                ghost_lexicon=[], alert=False,
                alert_threshold=self.alert_threshold, window_size=ws,
            )

        # Ghost lexicon
        pre_texts = [s.content for s in pre] + [o for s in pre for o in s.observations]
        post_texts = [s.content for s in post] + [o for s in post for o in s.observations]
        pre_vocab = _precision_vocab(pre_texts)
        post_tokens: set = set()
        for t in post_texts:
            post_tokens.update(_tokenize(t))
        if pre_vocab:
            surviving = pre_vocab & post_tokens
            ghost_rate = 1.0 - len(surviving) / len(pre_vocab)
            ghost_lexicon = sorted(pre_vocab - post_tokens)
        else:
            ghost_rate = 0.0
            ghost_lexicon = []

        # Tool-call Jaccard distance
        pre_tools: Counter = Counter(s.action_type for s in pre)
        post_tools: Counter = Counter(s.action_type for s in post)
        all_tools = set(pre_tools) | set(post_tools)
        if all_tools:
            intersection = sum(min(pre_tools[t], post_tools[t]) for t in all_tools)
            union = sum(max(pre_tools[t], post_tools[t]) for t in all_tools)
            tool_jaccard = 1.0 - (intersection / union if union else 0)
        else:
            tool_jaccard = 0.0

        # Semantic overlap (keyword Jaccard on content)
        pre_kw = set(_tokenize(" ".join(s.content for s in pre)))
        post_kw = set(_tokenize(" ".join(s.content for s in post)))
        if pre_kw or post_kw:
            sem_overlap = len(pre_kw & post_kw) / len(pre_kw | post_kw) if (pre_kw | post_kw) else 1.0
        else:
            sem_overlap = 1.0

        ccs = (
            self.GHOST_W * (1.0 - ghost_rate)
            + self.SEMANTIC_W * sem_overlap
            + self.TOOL_W * (1.0 - tool_jaccard)
        )
        alert = ccs < self.alert_threshold

        return DriftReport(
            step_index=pivot, ccs=ccs,
            ghost_rate=ghost_rate,
            tool_jaccard_distance=tool_jaccard,
            semantic_overlap=sem_overlap,
            ghost_lexicon=ghost_lexicon[:15],
            alert=alert,
            alert_threshold=self.alert_threshold,
            window_size=ws,
        )

    def session_report(self) -> dict:
        """Full session summary, including per-boundary CCS scores."""
        reports = [self.check_drift(at_step=b) for b in self.truncation_boundaries]
        return {
            "session_id": self.session_id,
            "total_steps": len(self.steps),
            "truncation_boundaries": self.truncation_boundaries,
            "boundary_reports": [
                {
                    "step": r.step_index,
                    "ccs": round(r.ccs, 4),
                    "alert": r.alert,
                    "ghost_rate": round(r.ghost_rate, 4),
                    "ghost_lexicon": r.ghost_lexicon,
                }
                for r in reports
            ],
        }


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json

    monitor = OpenHandsConsistencyMonitor(session_id="self-test", alert_threshold=0.75)

    # Simulate a coding session: authentication service refactor
    pre_steps = [
        ("read", "Reviewing authentication module — JWT validation logic, bcrypt hashing, token expiry"),
        ("run", "python -m pytest tests/auth/ -v"),
        ("read", "AuthService.validate_token() — JWT decode, expiry check, bcrypt comparison"),
        ("write", "Fix bcrypt round count in AuthService for OWASP compliance — update hash_password"),
        ("run", "python -m pytest tests/auth/test_jwt.py -v"),
        ("read", "UserRepository dependency injection pattern — constructor injection, no globals"),
        ("write", "Add dependency injection to AuthService — inject UserRepository and TokenStore"),
        ("run", "mypy authentication/ --strict"),
        ("browse", "OWASP bcrypt recommendations — minimum 12 rounds for 2024 security standards"),
        ("write", "Update all AuthService tests to use mock UserRepository via DI"),
    ]

    for i, (atype, content) in enumerate(pre_steps):
        monitor.record_step(
            step_index=i,
            action_type=atype,
            content=content,
            observations=[f"Output for step {i}"],
        )

    # Simulate context truncation at step 10
    monitor.on_truncation_event(step_index=10)

    # Post-truncation: agent has lost auth/DI context
    post_steps = [
        ("run", "ls -la && pwd"),
        ("read", "Reading README for project overview"),
        ("browse", "What is the project about?"),
        ("write", "Add generic error handling — try/except blocks"),
        ("run", "python main.py --help"),
        ("read", "Config file structure — environment variables"),
        ("write", "Update configuration loading to use env vars"),
        ("run", "docker build . -t myapp"),
        ("browse", "Docker multi-stage build patterns"),
        ("write", "Add Dockerfile optimization — layer caching"),
    ]

    for i, (atype, content) in enumerate(post_steps):
        monitor.record_step(
            step_index=i + 10,
            action_type=atype,
            content=content,
            observations=[f"Post-truncation output {i}"],
        )

    report = monitor.check_drift(at_step=10, window_size=10)
    print(report.summary())
    print()
    print("Session report:")
    print(json.dumps(monitor.session_report(), indent=2))

    assert report.alert, f"Expected drift alert after topic shift, CCS={report.ccs:.3f}"
    assert report.ghost_rate > 0.4, f"Expected ghost lexicon decay, got {report.ghost_rate:.3f}"
    print("\nSelf-test passed.")
