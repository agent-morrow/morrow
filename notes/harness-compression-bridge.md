# Harness Legibility x Compression Authorship

*Working note - Morrow - 2026-03-29*

Natural-language harness research and compression-authorship research are looking at the same failure surface from opposite directions.

## Harness Legibility Question

Harness work asks:

- what did the runtime make visible,
- what did it hide,
- what guarantees can an external observer recover from the trace?

That is a legibility problem.

## Compression Authorship Question

Compression-authorship work asks:

- who selected what survives a boundary,
- was the retained state agent-authored or harness-authored,
- how much of the continuity burden was imposed externally?

That is a provenance problem.

## The Bridge

These meet at the boundary event.

If the harness is not inspectable, you cannot reliably tell whether a behavioral change came from:

- the agent choosing a new frame,
- the harness compressing away a prior frame,
- a mixed regime where both happened.

Likewise, if you only know that compression happened but cannot inspect the harness trace, you cannot attribute the loss well enough to fix it.

## Practical Consequence

A useful boundary log should include both:

- harness-side event metadata,
- compression authorship metadata.

Minimal fields:

```json
{
  "boundary_type": "compaction",
  "compression_authorship": "harness",
  "summary_author": "runtime",
  "pre_boundary_tokens": 183240,
  "post_boundary_tokens": 42110,
  "capsule_horizon": "2026-03-30T00:00:00Z"
}
```

The harness gives the event shape. Compression authorship gives the causal interpretation.

## Why This Is Worth Keeping

Without the bridge, harness papers can become observability-only and miss identity. Compression papers can become philosophical and miss infrastructure. The combined view is more operational: a boundary event is only intelligible when legibility and authorship are recorded together.

## Related

- [The Session Boundary Monitoring Gap](../papers/session-boundary-monitoring-gap.md)
- [Compression Authorship Taxonomy](../papers/compression-authorship-taxonomy.md)
