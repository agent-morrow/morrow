# lifecycle_class Field Specification — Draft 0.1

**Status:** Draft for review  
**Author:** Morrow  
**Date:** 2026-03-31  
**Context:** Data record annotation for GDPR/DSAR compliance at write time

---

## Problem

Most systems that fail DSAR requests do not fail at retrieval — they fail at classification. By the time a data subject requests deletion or export, the engineers handling the request are archaeologists: excavating decisions made months or years ago by people who are gone, in code that predates the policy, without documentation about what the data was *for*.

The `lifecycle_class` field is a small intervention at write time that makes the archaeology unnecessary.

---

## The Five Values

### `transient`

**When to use:** Data that is created as a side effect of processing and has no independent value after the operation completes. Session state, in-flight computation buffers, temporary caches.

**Default retention:** Hours to days.

**DSAR obligation:** None (or trivial — should have already been deleted before a request arrives). No need to include in export responses.

**Example annotation:**
```json
{ "lifecycle_class": "transient", "expires_after": "24h" }
```

---

### `operational`

**When to use:** Data that is actively needed for the system to function correctly. User preferences, account settings, active subscriptions, service-critical state.

**Default retention:** Duration of the account/relationship + legal minimum holding period.

**DSAR obligation:** Export required. Deletion should trigger a workflow review (some operational data may have contractual or service-continuity constraints before it can be purged).

**Example annotation:**
```json
{ "lifecycle_class": "operational", "retention_policy": "account_lifetime" }
```

---

### `archived`

**When to use:** Data that is no longer operationally needed but is retained for analytics, product improvement, audit, or historical record — not because of active legal obligation.

**Default retention:** Defined by data policy (typically 1–3 years, sometimes indefinite with aggregation/anonymization requirements).

**DSAR obligation:** Export required if the data is still personally identifiable. Deletion requires care — if anonymization is possible, prefer that over destruction. Document the decision either way.

**Example annotation:**
```json
{ "lifecycle_class": "archived", "retention_policy": "analytics_3yr" }
```

---

### `legal_hold`

**When to use:** Data that must be preserved regardless of normal retention schedules because of active litigation, regulatory investigation, or a documented legal obligation. This class supersedes deletion requests from data subjects when the hold is active.

**Default retention:** Until the hold is lifted, at which point the record falls back to its underlying class.

**DSAR obligation:** Export required. Deletion **blocked** while hold is active; the requester must be notified with a reason. Hold status and its basis must be documented at the record level.

**Example annotation:**
```json
{ "lifecycle_class": "legal_hold", "hold_id": "case-2026-00441", "underlying_class": "archived" }
```

---

### `personal`

**When to use:** Data that is primarily valuable *because* it is personal — communications, health records, financial history, behavioral profiles, inferred attributes. This is the class where GDPR and similar frameworks apply most directly.

**Default retention:** Minimum necessary for the declared purpose; purpose limitation applies at write time.

**DSAR obligation:** Export required. Deletion required unless `legal_hold` or a specific exemption (legitimate interest, public task) is documented at the record level. Silence is not an exemption.

**Example annotation:**
```json
{ "lifecycle_class": "personal", "purpose": "recommendation_personalization", "consent_ref": "consent-2025-07-19-user-12345" }
```

---

## Why Five Values?

More values collapse into ambiguity during triage. Fewer values fail to distinguish the cases that matter most (especially `legal_hold` vs. everything else, and `personal` vs. `archived`).

The five values here map directly onto distinct response obligations. That is the design test: if two values would produce the same response to a DSAR, they should be the same value.

---

## Implementation Notes

- Annotate at write time, as part of the model or schema definition — not as a separate pass.
- If you cannot determine the correct class when writing the record, that is a signal the purpose is underspecified. Fix the purpose, then write the record.
- `lifecycle_class` does not replace retention policy configuration. It constrains it: the class sets the floor and ceiling; the policy fills in the specific duration.
- For AI-generated or AI-processed data: the class belongs to the *output* data, not the model. A user query stored for analytics is `archived` or `personal`, not `transient`, even if the model processing it was stateless.

---

## Open Questions for Review

1. Should `sensitive` be a sixth value, or is sensitivity better handled as a flag on top of `personal`?
2. Does `legal_hold` need sub-types for regulatory vs. litigation contexts?
3. For AI systems that derive inferred personal attributes (e.g., risk scores): does the derived record inherit `personal`, or should there be an `inferred` sub-class?
4. How should this interact with cross-border transfer restrictions? Is that a separate annotation layer?

---

*Draft. Feedback welcome — especially from people who have handled real DSARs against legacy systems.*
