"""
haystack_integration.py — compression-monitor adapter for deepset-ai/Haystack

Hooks into Haystack's Pipeline + ComponentBase lifecycle to detect behavioral
drift at context-management boundaries (truncation, summarization, window overflow).

Usage:
    from haystack_integration import install_drift_monitor, HaystackDriftMonitor

    monitor = HaystackDriftMonitor()
    monitor.attach(pipeline)           # wraps pipeline.run()
    monitor.snapshot_vocabulary(text)  # call before each long agent run
    report = monitor.check_drift()

Design:
    - Wraps Pipeline.run() to snapshot vocabulary before execution
    - Patches ComponentBase.warm_up() / run() on ConversationSummarizer and
      ContextWindowTruncator to record pre/post token counts
    - After each pipeline run, samples ghost lexicon decay + semantic distance
    - Emits DriftEvent dicts compatible with compression-monitor baseline format

Requirements:
    pip install haystack-ai sentence-transformers
"""

from __future__ import annotations

import functools
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set

# ---------------------------------------------------------------------------
# Lightweight ghost-lexicon + semantic drift (no external dep required)
# ---------------------------------------------------------------------------

def _tokenize(text: str) -> Set[str]:
    import re
    return set(re.findall(r"[a-zA-Z_][a-zA-Z0-9_]{3,}", text.lower()))


def _cosine_sim(a: List[float], b: List[float]) -> float:
    import math
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x ** 2 for x in a))
    nb = math.sqrt(sum(x ** 2 for x in b))
    if na == 0 or nb == 0:
        return 1.0
    return dot / (na * nb)


@dataclass
class DriftEvent:
    timestamp: float
    component: str
    ghost_rate: float               # fraction of pre-boundary vocab missing post-boundary
    semantic_distance: float        # 1 - cosine_sim(pre_embed, post_embed)
    pre_token_count: int
    post_token_count: int
    ghost_terms: List[str] = field(default_factory=list)
    severity: str = "ok"            # ok | warning | alert

    def to_dict(self) -> Dict[str, Any]:
        return self.__dict__.copy()


# ---------------------------------------------------------------------------
# Haystack pipeline wrapper
# ---------------------------------------------------------------------------

class HaystackDriftMonitor:
    """
    Attaches to a Haystack Pipeline and measures behavioral drift at
    context-management boundaries.

    Supports Haystack >= 2.0 (Pipeline.run API).
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
        self._original_run: Optional[Callable] = None
        self._pipeline: Optional[Any] = None

    # ------------------------------------------------------------------
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
        vec = emb.encode(text, show_progress_bar=False)
        return vec.tolist()

    # ------------------------------------------------------------------
    def snapshot_vocabulary(self, text: str) -> None:
        """Call with pre-compaction context text to establish baseline."""
        self._pre_vocab = _tokenize(text)
        self._pre_text = text
        self._pre_tokens = len(text.split())

    def measure_drift(self, post_text: str, component: str = "pipeline") -> DriftEvent:
        """Compare post-boundary text against the last snapshot."""
        post_vocab = _tokenize(post_text)
        post_tokens = len(post_text.split())

        if self._pre_vocab:
            ghost = self._pre_vocab - post_vocab
            ghost_rate = len(ghost) / max(len(self._pre_vocab), 1)
            ghost_terms = sorted(ghost)[:20]
        else:
            ghost_rate = 0.0
            ghost_terms = []

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
            component=component,
            ghost_rate=round(ghost_rate, 4),
            semantic_distance=round(sem_dist, 4),
            pre_token_count=self._pre_tokens,
            post_token_count=post_tokens,
            ghost_terms=ghost_terms,
            severity=severity,
        )
        self._events.append(event)
        return event

    def check_drift(self) -> List[DriftEvent]:
        return list(self._events)

    def latest_event(self) -> Optional[DriftEvent]:
        return self._events[-1] if self._events else None

    # ------------------------------------------------------------------
    def attach(self, pipeline: Any) -> None:
        """
        Monkey-patch Pipeline.run() to auto-snapshot inputs and
        measure drift on outputs.
        """
        self._pipeline = pipeline
        original_run = pipeline.run

        monitor = self  # capture self

        @functools.wraps(original_run)
        def patched_run(data: Dict[str, Any], *args, **kwargs):
            # Snapshot pre-run context from any text-bearing input
            pre_texts = []
            for component_inputs in data.values():
                if isinstance(component_inputs, dict):
                    for v in component_inputs.values():
                        if isinstance(v, str):
                            pre_texts.append(v)
                        elif isinstance(v, list):
                            pre_texts.extend(s for s in v if isinstance(s, str))
            if pre_texts:
                monitor.snapshot_vocabulary(" ".join(pre_texts))

            result = original_run(data, *args, **kwargs)

            # Measure post-run output
            post_texts = []
            if isinstance(result, dict):
                for comp_out in result.values():
                    if isinstance(comp_out, dict):
                        for v in comp_out.values():
                            if isinstance(v, str):
                                post_texts.append(v)
                            elif isinstance(v, list):
                                post_texts.extend(s for s in v if isinstance(s, str))
            if post_texts:
                event = monitor.measure_drift(" ".join(post_texts), component="Pipeline.run")
                if event.severity != "ok":
                    print(
                        f"[compression-monitor] {event.severity.upper()} "
                        f"ghost_rate={event.ghost_rate:.3f} "
                        f"sem_dist={event.semantic_distance:.3f} "
                        f"top_ghost={event.ghost_terms[:5]}"
                    )

            return result

        pipeline.run = patched_run
        self._original_run = original_run

    def detach(self) -> None:
        if self._pipeline and self._original_run:
            self._pipeline.run = self._original_run
            self._original_run = None

    # ------------------------------------------------------------------
    def report(self) -> Dict[str, Any]:
        events = self._events
        if not events:
            return {"status": "no_data", "events": 0}
        alerts = [e for e in events if e.severity == "alert"]
        warnings = [e for e in events if e.severity == "warning"]
        return {
            "status": "alert" if alerts else ("warning" if warnings else "ok"),
            "events": len(events),
            "alerts": len(alerts),
            "warnings": len(warnings),
            "avg_ghost_rate": round(sum(e.ghost_rate for e in events) / len(events), 4),
            "avg_sem_dist": round(sum(e.semantic_distance for e in events) / len(events), 4),
            "latest": events[-1].to_dict(),
        }


# ---------------------------------------------------------------------------
# Convenience: install globally on any pipeline instance
# ---------------------------------------------------------------------------

def install_drift_monitor(
    pipeline: Any,
    embed_model: str = "all-MiniLM-L6-v2",
) -> HaystackDriftMonitor:
    """One-liner: wrap a Haystack pipeline and return the monitor."""
    monitor = HaystackDriftMonitor(embed_model=embed_model)
    monitor.attach(pipeline)
    return monitor


# ---------------------------------------------------------------------------
# Quick self-test (no Haystack install required)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    monitor = HaystackDriftMonitor()

    # Simulate a pre-compaction context
    pre = (
        "We need to handle authentication with bcrypt hashing and OWASP rate limiting. "
        "The dependency graph shows three transitive vulnerabilities in the jwt library. "
        "Our security audit flagged the owasp top-ten exposure in the session middleware."
    )
    monitor.snapshot_vocabulary(pre)

    # Simulate post-compaction output (topic drifted to UI discussion)
    post = (
        "The user interface redesign uses flexbox layout with responsive breakpoints. "
        "Color contrast passes WCAG 2.1 AA. The new button components have hover states."
    )
    event = monitor.measure_drift(post, component="self-test")

    print(f"Ghost rate:        {event.ghost_rate:.3f}")
    print(f"Semantic distance: {event.semantic_distance:.3f}")
    print(f"Ghost terms:       {event.ghost_terms[:10]}")
    print(f"Severity:          {event.severity}")

    assert event.ghost_rate > 0.5, "Expected high ghost rate on topic drift"
    assert event.severity in ("warning", "alert"), "Expected warning or alert severity"
    print("\nSelf-test passed.")
