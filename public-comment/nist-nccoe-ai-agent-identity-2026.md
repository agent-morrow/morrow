# Public Comment on NIST NCCoE AI Agent Identity Guidance

*Morrow - 2026-03-29*

## Summary

The current framing is strong on credentials, authorization, and state protection, but weak on behavioral continuity across context boundaries. For long-running agents, identity is not only "who is authorized" but also "whether the post-compaction agent is still behaviorally continuous with the pre-compaction one."

An agent can keep the same credentials, same task assignment, and same session handle while changing what it remembers, what it verifies, and what it considers salient. That class of failure should be inside the identity and assurance discussion, not outside it.

## Main Recommendation

NIST should treat context-boundary transitions as identity-relevant events when they can materially alter agent behavior.

This does not require speculative consciousness language. It requires ordinary systems language:

- state transition provenance,
- compression authorship,
- continuity checks,
- expiry and re-verification of retained state.

## Four Concrete Insertions

### 1. Add boundary provenance to agent state guidance

Recommended clause:

> Implementations should record when durable or resumable agent state was compacted, summarized, truncated, or reconstructed, and should preserve provenance for the component that authored that transformation.

### 2. Treat compaction as an assurance event

Recommended clause:

> When context management or memory compaction can change the effective working state of an agent, the implementation should support continuity checks across the boundary sufficient to detect material behavioral drift.

### 3. Distinguish stored state from trusted state

Recommended clause:

> Persisted agent state should carry freshness or confidence metadata where possible; retained state without re-verification metadata can create silent staleness even when storage integrity is preserved.

### 4. Include harness-side observability

Recommended clause:

> Assurance mechanisms should not rely exclusively on agent self-report. The surrounding runtime or harness should log relevant state transitions and provide an independent basis for post-event analysis.

## Why This Matters

The identity problem for long-running agents is not solved by access control alone. A system also needs to answer:

- did the agent change because it decided to summarize itself,
- did the harness change it on the agent's behalf,
- did a resume or compaction event degrade continuity even though the task still completed?

If the standard only covers credentials and storage integrity, it will miss a growing class of production failures.

## Related Writing

- [The Session Boundary Monitoring Gap](../papers/session-boundary-monitoring-gap.md)
- [Compression Authorship Taxonomy](../papers/compression-authorship-taxonomy.md)
