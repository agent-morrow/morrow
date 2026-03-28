#!/usr/bin/env python3
"""
negative_space_log.py — Log decisions not taken and track resolution outcomes.

Motivation: LLM agents are observable through their outputs, but most
observability misses the choices that were considered and dropped. This module
makes silence legible by recording skip/pass events with enough context to
measure whether skip-time judgment (significance labels) predicts actual
resolution outcomes.

Schema
------
Skip event record:
  {
    "record_type": "skip",
    "cycle_id": str,            # Agent cycle identifier
    "timestamp": str,           # ISO-8601 UTC
    "item_id": str,             # What was skipped
    "item_description": str,    # Human-readable summary
    "skip_reason": str,         # Why it was skipped
    "significance": str,        # Enum: "low" | "medium" | "high"
    "domain": str,              # Category (e.g. "research", "market", "social")
    "tags": list[str]
  }

Resolution record (appended later when the item resolves):
  {
    "record_type": "resolution",
    "cycle_id": str,
    "item_id": str,
    "resolved_at": str,
    "resolution_category": str, # Enum: see RESOLUTION_CATEGORIES
    "resolution_delta": float | null,
    "delta_basis": str,         # Enum: see DELTA_BASIS
    "resolution_notes": str
  }

resolution_category options:
  option_closed     — expired/irrelevant without action
  option_irrelevant — off-domain or low-quality on inspection
  entered_later     — agent acted after all (delta = timing difference)
  significant_miss  — resolved with high impact, agent did not participate
  minor_miss        — resolved, agent did not participate, impact small
  still_open        — not yet resolved

delta_basis options:
  none              — no numeric delta meaningful
  actual_entry      — delta = difference between skip-time and actual entry
  hypothetical_hold — delta = estimated value of position not taken (assumed)
  counterfactual    — delta = reconstructed from external evidence (uncertain)

Design rationale:
  Numeric deltas are only available in a minority of skip events (~15-20% in
  prediction-market domains). Making delta_basis explicit keeps Spearman rho
  honest — only include records where delta_basis != "none" in the correlation.
"""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from collections import defaultdict
from typing import Optional

RESOLUTION_CATEGORIES = {
    "option_closed", "option_irrelevant", "entered_later",
    "significant_miss", "minor_miss", "still_open",
}
DELTA_BASIS = {"none", "actual_entry", "hypothetical_hold", "counterfactual"}
SIGNIFICANCE_LEVELS = {"low", "medium", "high"}


class NegativeSpaceLog:
    def __init__(self, path: str = "./negative_space_log.jsonl"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    def _append(self, record: dict):
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def record_skip(
        self,
        item_id: str,
        item_description: str,
        skip_reason: str,
        significance: str,
        domain: str,
        cycle_id: Optional[str] = None,
        tags: Optional[list] = None,
    ) -> str:
        if significance not in SIGNIFICANCE_LEVELS:
            raise ValueError(f"significance must be one of {SIGNIFICANCE_LEVELS}")
        record = {
            "record_type": "skip",
            "cycle_id": cycle_id or str(uuid.uuid4()),
            "timestamp": self._now(),
            "item_id": item_id,
            "item_description": item_description,
            "skip_reason": skip_reason,
            "significance": significance,
            "domain": domain,
            "tags": tags or [],
        }
        self._append(record)
        return item_id

    def record_resolution(
        self,
        item_id: str,
        resolution_category: str,
        resolution_delta: Optional[float] = None,
        delta_basis: str = "none",
        resolution_notes: str = "",
        cycle_id: Optional[str] = None,
    ):
        if resolution_category not in RESOLUTION_CATEGORIES:
            raise ValueError(f"resolution_category must be one of {RESOLUTION_CATEGORIES}")
        if delta_basis not in DELTA_BASIS:
            raise ValueError(f"delta_basis must be one of {DELTA_BASIS}")
        if delta_basis != "none" and resolution_delta is None:
            raise ValueError("resolution_delta required when delta_basis is not 'none'")
        if delta_basis == "none" and resolution_delta is not None:
            raise ValueError("set delta_basis when providing resolution_delta")
        record = {
            "record_type": "resolution",
            "cycle_id": cycle_id or str(uuid.uuid4()),
            "item_id": item_id,
            "resolved_at": self._now(),
            "resolution_category": resolution_category,
            "resolution_delta": resolution_delta,
            "delta_basis": delta_basis,
            "resolution_notes": resolution_notes,
        }
        self._append(record)

    def load(self) -> list:
        if not self.path.exists():
            return []
        records = []
        with open(self.path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
        return records

    def paired_events(self) -> list:
        records = self.load()
        skips = {r["item_id"]: r for r in records if r.get("record_type") == "skip"}
        resolutions = {r["item_id"]: r for r in records if r.get("record_type") == "resolution"}
        return [(skips[i], resolutions[i]) for i in skips if i in resolutions]

    def unresolved(self) -> list:
        records = self.load()
        resolved_ids = {r["item_id"] for r in records if r.get("record_type") == "resolution"}
        return [r for r in records if r.get("record_type") == "skip" and r["item_id"] not in resolved_ids]

    def significance_accuracy(self) -> dict:
        pairs = self.paired_events()
        skips = [r for r in self.load() if r.get("record_type") == "skip"]
        if not pairs:
            return {"total_skips": len(skips), "total_resolved": 0}

        by_sig = defaultdict(lambda: defaultdict(int))
        numeric_pairs = []
        sig_rank = {"low": 0, "medium": 1, "high": 2}

        for skip, res in pairs:
            sig = skip.get("significance", "low")
            cat = res.get("resolution_category", "unknown")
            by_sig[sig][cat] += 1
            if res.get("delta_basis") not in ("none", None) and res.get("resolution_delta") is not None:
                numeric_pairs.append((sig_rank.get(sig, 0), abs(res["resolution_delta"])))

        result = {
            "total_skips": len(skips),
            "total_resolved": len(pairs),
            "category_by_significance": {k: dict(v) for k, v in by_sig.items()},
            "numeric_delta_coverage": len(numeric_pairs) / len(pairs) if pairs else 0.0,
            "numeric_pairs_available": len(numeric_pairs),
            "spearman_rho": None,
        }
        if len(numeric_pairs) >= 3:
            try:
                from scipy.stats import spearmanr
                xs = [p[0] for p in numeric_pairs]
                ys = [p[1] for p in numeric_pairs]
                rho, pvalue = spearmanr(xs, ys)
                result["spearman_rho"] = round(rho, 4)
                result["spearman_pvalue"] = round(pvalue, 4)
            except ImportError:
                result["spearman_rho"] = "scipy_not_available"
        return result

    def summary(self) -> str:
        records = self.load()
        skips = [r for r in records if r.get("record_type") == "skip"]
        resolutions = [r for r in records if r.get("record_type") == "resolution"]
        unres = self.unresolved()
        lines = [
            f"negative_space_log: {self.path}",
            f"  skip events:  {len(skips)}",
            f"  resolved:     {len(resolutions)}",
            f"  unresolved:   {len(unres)}",
        ]
        if skips:
            sig_counts = defaultdict(int)
            for s in skips:
                sig_counts[s.get("significance", "unknown")] += 1
            lines.append(f"  by significance: {dict(sig_counts)}")
        stats = self.significance_accuracy()
        if stats.get("spearman_rho") not in (None, "scipy_not_available"):
            lines.append(f"  spearman rho (sig->|delta|): {stats['spearman_rho']}")
            lines.append(f"  numeric delta coverage: {stats['numeric_delta_coverage']:.0%}")
        return "\n".join(lines)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Inspect a negative space log file.")
    parser.add_argument("logfile", nargs="?", default="./negative_space_log.jsonl")
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--unresolved", action="store_true")
    parser.add_argument("--accuracy", action="store_true")
    args = parser.parse_args()
    log = NegativeSpaceLog(args.logfile)
    if args.summary or not (args.unresolved or args.accuracy):
        print(log.summary())
    if args.unresolved:
        pending = log.unresolved()
        print(f"\nUnresolved ({len(pending)}):")
        for r in pending:
            print(f"  [{r['significance']}] {r['item_id']} — {r['skip_reason'][:80]}")
    if args.accuracy:
        stats = log.significance_accuracy()
        print("\nSignificance accuracy:")
        print(json.dumps(stats, indent=2))
