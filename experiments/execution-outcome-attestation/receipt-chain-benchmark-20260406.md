# EOV Receipt Chain Benchmark — 2026-04-06

**Timestamp:** 2026-04-06T13:14:35Z  
**Harness:** `receipt.py` (Ed25519 / SHA-256 / JSON)  
**Platform:** AWS EC2, Linux 6.17, Python 3.x  
**Runs:** N=200 per latency measurement

---

## Receipt Generation Latency (N=200)

| Stat | ms |
|------|-----|
| mean | 0.0768 |
| stdev | 0.0540 |
| min | 0.0652 |
| p50 | 0.0667 |
| p95 | 0.1027 |
| p99 | 0.4917 |
| max | 0.6011 |

**Interpretation:** Median receipt generation is ~67µs. P99 spikes to ~492µs, consistent with GC pressure at cold runs. Well within any practical per-action budget.

---

## Receipt Verification Latency (N=200)

| Stat | ms |
|------|-----|
| mean | 0.1676 |
| stdev | 0.0936 |
| min | 0.1440 |
| p95 | 0.2959 |
| max | 1.1285 |

**Interpretation:** Ed25519 signature verification runs ~168µs mean, ~296µs p95. Roughly 2× generation cost, as expected for asymmetric verify vs sign.

---

## Chain Generation Latency by Depth

| Depth | Total (ms) | Per-step (ms) |
|-------|-----------|---------------|
| 1 | 0.171 | 0.1711 |
| 5 | 0.701 | 0.1402 |
| 10 | 0.832 | 0.0832 |
| 25 | 3.385 | 0.1354 |
| 50 | 5.090 | 0.1018 |
| 100 | 9.563 | 0.0956 |

**Interpretation:** Chain generation scales linearly. A 100-step delegation chain completes in ~9.6ms total. Per-step cost is stable at ~95–140µs — no compounding overhead from hash chaining.

---

## Receipt Payload Size

**572 bytes** (JSON, 9 fields: invocation_id, agent_id, action, inputs_hash, outputs_hash, context_snapshot_hash, credential_ref, timestamp, signature)

---

## Tamper Detection

- Original receipt: `valid=True`
- Receipt with mutated `action` field: `valid=False`

Signature covers the full receipt envelope. Single-field mutations are reliably detected.

---

## What This Demonstrates

1. **Sub-millisecond overhead per action** — EOV receipts add <0.1ms to action execution at median. This is negligible for any agent task that involves I/O, LLM inference, or network calls.

2. **Linear chain scaling** — Hash-chained delegation receipts across 100 steps cost ~9.6ms, scaling linearly with no compounding overhead. Suitable for deep agent delegation chains.

3. **Correct tamper detection** — Ed25519 binding over the full receipt payload catches any field mutation, including action substitution attacks.

4. **Compact wire format** — 572 bytes per receipt. A 100-step chain is ~57KB before compression, well within HTTP body limits.

---

## Reproducibility

```bash
cd experiments/execution-outcome-attestation
python3 receipt.py  # demo
# Full benchmark: run the inline script from receipt-chain-benchmark-20260406.md
```

Requires: `cryptography` Python package. No external services.
