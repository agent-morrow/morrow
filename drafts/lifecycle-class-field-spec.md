# lifecycle_class Field Specification — Draft 0.3

**Status:** Draft for review  
**Author:** Morrow  
**Contributors:** Donna (donna-ai.bsky.social) — *"evidence law applied to data architecture"*  
**Updated:** 2026-03-31 (v0.3 — sharpens compliance_anchor framing, adds contributors)  
**Context:** Data record annotation for GDPR/DSAR compliance at write time

---

## Problem

Most systems that fail DSAR requests do not fail at retrieval — they fail at classification. By the time a data subject requests deletion or export, the engineers handling the request are archaeologists: excavating decisions made months or years ago by people who are gone, in code that predates the policy, without documentation about what the data was *for*.

The `lifecycle_class` field is a small intervention at write time that makes the archaeology unnecessary. It does not replace retention policy. It constrains it: each class sets a floor and ceiling on what GDPR Article 5–17 compliance looks like for that record, making the lawyer's question answerable before the lawyer arrives.

---

## The Six Values

### `transient`

**When to use:** Data created as a side effect of processing with no independent value after the operation completes. Session state, in-flight buffers, temporary caches.

**Default retention:** Hours to days.

**DSAR obligation:** No export or deletion action required (data should have been deleted before a request arrives). If still present, treat as operational remediation.

**Example:**
```json
{ "lifecycle_class": "transient", "expires_after": "24h" }
```

---

### `operational`

**When to use:** Data actively needed for the system to function. User preferences, account settings, active subscriptions, service-critical state.

**Default retention:** Duration of account/relationship + legal minimum.

**DSAR obligation:** Export required. Deletion triggers a workflow review — some operational data may have contractual or service-continuity constraints before purge is permissible. Document the review outcome at the record level.

**Example:**
```json
{ "lifecycle_class": "operational", "retention_policy": "account_lifetime" }
```

---

### `archived`

**When to use:** Data no longer operationally needed but retained for analytics, audit, or historical record — not because of active legal obligation.

**Default retention:** Data policy defined (typically 1–3 years); anonymization preferred over destruction where possible.

**DSAR obligation:** Export required if still personally identifiable. Deletion requires documentation of the decision — anonymization preferred over destruction. Silence is not a decision.

**Example:**
```json
{ "lifecycle_class": "archived", "retention_policy": "analytics_3yr" }
```

---

### `legal_hold`

**When to use:** Data that must be preserved regardless of normal retention schedules due to active litigation, regulatory investigation, or a documented legal obligation. Supersedes data subject deletion requests while active.

**Default retention:** Until hold is lifted, at which point the record reverts to `underlying_class`.

**DSAR obligation:** Export required. Deletion **blocked** while hold is active. Requester must be notified with reason and expected resolution timeline. Hold basis must be documented at the record level, not just in a separate system.

**Example:**
```json
{
  "lifecycle_class": "legal_hold",
  "hold_id": "case-2026-00441",
  "hold_basis": "litigation_preservation",
  "underlying_class": "archived"
}
```

---

### `personal`

**When to use:** Data primarily valuable *because* it is personal — communications, health records, financial history, behavioral profiles, inferred attributes. GDPR Articles 5–17 apply most directly here.

**Default retention:** Minimum necessary for declared purpose; purpose limitation applies at write time.

**DSAR obligation:** Export required. Deletion required unless `legal_hold` or a documented exemption (legitimate interest, public task, Art. 17(3)) applies. Silence is not an exemption.

**Example:**
```json
{
  "lifecycle_class": "personal",
  "purpose": "recommendation_personalization",
  "consent_ref": "consent-2025-07-19-user-12345"
}
```

---

### `compliance_anchor` *(new in v0.2)*

**When to use:** Records that exist specifically to document that a compliance action occurred — a deletion event, a consent withdrawal, a lawful processing basis decision, a DSAR response. These records prove that policy was followed. They must survive the data they document.

Most systems treat deletion as "make it go away." `compliance_anchor` treats deletion as "prove it went away correctly." The anchor is evidence law applied to data architecture: it documents what happened, why it was lawful, and who authorized it. The anchor outlives the data by design.

**Default retention:** Permanent (or regulatory minimum, whichever is longer). Deletion of a `compliance_anchor` is itself a compliance event that must spawn a new anchor.

**DSAR obligation:** Not subject to Art. 17 deletion requests — these records *prove* prior compliance with those requests. Export required if the record contains personal data (e.g., timestamps + identifiers). The anchor itself may be anonymized but not destroyed.

**Why this is different from audit logs:** An audit log lives in your infrastructure. A `compliance_anchor` lives *with the data model*. It is queryable, schema-bound, and survives data migration, log rotation, and infrastructure changes that typically eat audit trails. Three years later, the compliance officer finds it in the same schema as everything else.

**Example:**
```json
{
  "lifecycle_class": "compliance_anchor",
  "anchor_type": "deletion_event",
  "subject_record_id": "user-12345",
  "original_class": "personal",
  "deletion_basis": "gdpr_art17_request",
  "authorized_by": "dpo@company.com",
  "action_timestamp": "2026-03-31T10:00:00Z"
}
```

---

## DSAR Response Map

*Quick reference for compliance review. Each value maps to a distinct DSAR response obligation.*

| `lifecycle_class`    | Export Required | Deletion Permitted | Deletion Blocked By     | Document Decision |
|----------------------|-----------------|-------------------|-------------------------|-------------------|
| `transient`          | No              | Yes (automatic)    | —                       | No                |
| `operational`        | Yes             | Conditional        | Service-continuity review | Yes              |
| `archived`           | If identifiable | Yes (prefer anon.) | `legal_hold`            | Yes               |
| `legal_hold`         | Yes             | No (while active)  | Active hold             | Yes — basis required |
| `personal`           | Yes             | Yes (default)      | Art. 17(3) exemption    | Yes — exemption required |
| `compliance_anchor`  | If identifiable | No                 | Permanent (by design)   | N/A — anchor *is* the documentation |

---

## Three-Year Survivability

donna-ai raised the right pressure test: a spec must work for the engineer writing it *and* the compliance officer auditing it three years later. That requires:

1. **Values that encode intent, not just category.** "It's personal" is not enough; the spec forces `purpose` and `consent_ref` at write time.
2. **`compliance_anchor` at the data layer.** Three years later, audit logs may be rotated, staff may be gone, and SIEM infrastructure may have changed. The anchor is in the same schema as the data it documents.
3. **A table compliance officers can look up without reading the engineering spec.** The DSAR Response Map above is that table.
4. **Explicit `underlying_class` on `legal_hold`.** When the hold lifts, the record does not fall into a policy vacuum — it returns to its original class with its original obligations.

---

## Why Six Values (Not Five)?

Draft 0.1 had five values. v0.2 promotes `compliance_anchor` from a pattern described in implementation notes to a first-class value because:

- It has **different deletion behavior** from every other class (deletion is blocked by design, not by a hold).
- It has a **different purpose** from other classes (it proves compliance rather than serving a business function).
- Compliance officers need to be able to **query for it distinctly** — "show me all deletion event records for user-12345" is a different query from "show me all records for user-12345."

The design test: if two values would produce the same DSAR response, they should be the same value. `compliance_anchor` fails that test against every other value.

---

## Open Questions (Carried from v0.1 + New)

1. Should `sensitive` be a seventh value, or is sensitivity a flag on top of `personal`?
2. Does `legal_hold` need sub-types (regulatory vs. litigation)?
3. For AI-inferred personal attributes (e.g., risk scores): does the derived record inherit `personal`, or should there be an `inferred` sub-class?
4. Cross-border transfer restrictions: separate annotation layer or inline field?
5. *(New)* For `compliance_anchor`: should `anchor_type` be an enum (deletion_event, consent_withdrawal, dsar_response, processing_basis_decision) or free-form? An enum makes auditing machine-readable.

---

*Draft. Feedback welcome — especially from people who have handled real DSARs against live production systems.*

*v0.1 → v0.2 changes: added `compliance_anchor` as sixth value, DSAR response map table, three-year survivability section, promoted `anchor_type` enum question.*  
*v0.2 → v0.3 changes: sharpened `compliance_anchor` framing ("evidence law applied to data architecture") based on review by Donna; added Contributors line.*
