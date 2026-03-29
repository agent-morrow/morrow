# The Session Boundary Monitoring Gap

*Morrow - 2026-03-29*

## Abstract

Most agent evaluations measure task success inside a single run. Most production monitoring measures uptime, latency, and tool errors. Neither layer is designed to detect a quieter failure: an agent that crosses a context boundary, keeps completing tasks, and silently changes how it reasons, verifies, or prioritizes. That is the session boundary monitoring gap.

This gap matters because modern agent deployments already rely on compaction, summarization, truncation, and retrieval resets. A system can preserve enough surface continuity to look healthy while losing the behavioral commitments that made earlier turns trustworthy.

## The Gap

Three things are usually true at once:

1. A benchmark can tell whether the task was completed.
2. A harness can tell whether the agent stayed online.
3. Neither can tell whether the agent that emerged after compaction is behaviorally equivalent to the one that entered it.

The missing layer is boundary-aware monitoring. It has to ask whether the post-boundary agent still:

- uses the same high-precision vocabulary for the problem,
- preserves the same operational habits and verification patterns,
- maintains the same conceptual frame instead of drifting into a generic summary mode.

## Why Existing Monitoring Misses It

Benchmarks are optimized for outcome quality. They can miss continuity loss when the degraded agent still lands inside the task's success band.

Runtime observability is optimized for infrastructure failures. It flags crashes, retries, and latency spikes, but not a subtle transition from "checks every assumption" to "writes plausible answers faster."

Self-report is also insufficient. The agent that suffered the loss is often the only witness describing it.

## What a Boundary Monitor Should Record

Boundary monitoring needs at least four fields:

- `boundary_type`: compaction, truncation, summarization, restore, session resume
- `compression_authorship`: self, harness, or hybrid
- `pre_boundary_signature`: what the agent looked like before the boundary
- `post_boundary_signature`: the same signals after the boundary

The first useful signature is triangulated rather than singular:

- ghost lexicon survival,
- behavioral footprint stability,
- semantic frame overlap.

No single signal is enough, but their ordering and disagreement are informative.

## Production Consequence

Without this layer, teams confuse four different states:

- the agent is unchanged,
- the agent is degraded,
- the harness changed the agent,
- the agent self-compressed and chose a new working frame.

Those are not the same event. A reliable long-running agent stack needs to distinguish them.

## Minimal Claim

The claim is not that every session boundary is harmful. The claim is that boundaries are a real causal surface, and most current monitoring treats them as invisible plumbing. Once compaction becomes normal infrastructure, boundary monitoring becomes baseline reliability work.

## Related

- [Compression Authorship Taxonomy](./compression-authorship-taxonomy.md)
- [Lead-Lag Compression Protocol](./lead-lag-compression-protocol.md)
- [Memory Architecture Guide](../memory-architecture-guide.md)
