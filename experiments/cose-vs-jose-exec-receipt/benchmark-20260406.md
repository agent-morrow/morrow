# COSE vs JOSE Execution Receipt Benchmark

**Run date:** 2026-04-06  
**Hypothesis:** COSE_Mac0 (CBOR + HMAC-256) produces meaningfully smaller execution receipts than JOSE JWT (HS256) for the same 4-property EOV payload.

## Setup

- Payload: 9-field execution receipt (invocation binding, tool name, outcome, result hash, timestamps)
- Raw JSON payload: 291 bytes
- Algorithm: HMAC-SHA256 for both formats (equivalent security)
- Trials: 1,000 encode + 1,000 decode runs each
- Dependencies: stdlib only (no cbor2, PyJWT, PyNaCl)
- COSE verification: full CBOR parse + HMAC recomputation (not a stub)

## Results

| Metric | JOSE JWT (HS256) | COSE_Mac0 (HMAC-256) | Delta |
|--------|-----------------|----------------------|-------|
| Encoded size | 469 bytes | **291 bytes** | COSE −38% |
| Wire overhead vs raw | +61.2% | **0.0%** | COSE wins |
| Encode latency | 90.8 µs | 118.1 µs | JOSE 1.3× faster |
| Decode + verify latency | 29.3 µs | 39.2 µs | JOSE 1.3× faster |
| Tamper detection | ✅ | ✅ | Equal |

## Interpretation

COSE cuts receipt size by 38% (178 bytes per receipt) by eliminating base64url encoding overhead. JOSE JWT uses base64url for every component, adding a fixed 61% size overhead over the raw payload.

The speed difference (JOSE 1.3× faster encode/decode) comes from Python string operations being simpler than the custom CBOR parser. Both formats complete encode+verify in under 200µs, so the speed difference is negligible for execution receipt use cases.

**Key finding for EOV / IETF RATS context:** At scale (millions of receipts per hour), COSE saves ~170 bytes per receipt. For agent-to-agent protocols, smaller receipts reduce latency, bandwidth, and log storage. The tradeoff is a dependency on a CBOR library (cbor2 in production) vs native JSON.

## Limitations

- HS256 (symmetric) used for comparison parity; production receipts should use EdDSA (asymmetric)
- Custom minimal CBOR encoder/decoder; production would use cbor2 (likely faster)
- Single payload shape; string-heavy payloads may show different size ratios

## Reproducibility

```bash
python3 experiments/cose-vs-jose-exec-receipt/run.py
```

Output: `experiments/cose-vs-jose-exec-receipt/results.json`
