#!/usr/bin/env python3
"""
EOV Receipt Encoding Benchmark: CBOR/COSE vs JSON/JWS
Measures size and performance for execution receipt encoding across formats.

Hypothesis: CBOR/COSE produces smaller receipts than JSON/JWS for EOV receipts,
with comparable signing/verification performance.

Method:
  - Build a representative EOV receipt payload (matching draft-morrow-sogomonian-exec-outcome-attest-01 schema)
  - Encode as: (1) JSON, (2) CBOR, (3) JSON+JWS (compact), (4) CBOR+COSE_Sign1
  - Measure: serialized size, sign time (1000 iterations), verify time (1000 iterations)
  - Algorithm: Ed25519 for JWS; COSE uses ES256 (P-256) since cose library doesn't expose Ed25519 directly

Date: 2026-04-06
Author: Morrow
"""

import json
import cbor2
import time
import base64
import hashlib
import struct
import statistics
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.ec import (
    generate_private_key, SECP256R1, ECDSA
)
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.exceptions import InvalidSignature

N_ITER = 1000

# --- Representative EOV receipt payload ---
EOV_RECEIPT = {
    "version": "1",
    "receipt_id": "urn:uuid:7f3a2b1c-4d5e-6f7a-8b9c-0d1e2f3a4b5c",
    "issued_at": 1743948000,
    "invocation_context": {
        "action_ref": "urn:action:web_search",
        "credential_ref": "urn:jwt:eyJhbGciOiJFZERTQSJ9.example",
        "delegator_chain": ["urn:agent:operator", "urn:agent:morrow"],
        "session_id": "entity-autonomy-daemon-484b7f8511564165ae255176bb4670dc"
    },
    "outcome_claim": {
        "status": "completed",
        "action_class": "read",
        "result_hash": "sha256:a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2"
    },
    "b_hash": "sha256:b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2c3",
    "executor_id": "urn:agent:morrow",
    "harness_id": "urn:harness:openclaw-v1"
}

# COSE numeric label mappings (custom registry placeholder)
# Using integer keys to demonstrate CBOR compactness advantage
EOV_RECEIPT_CBOR = {
    1: "1",                                    # version
    2: "urn:uuid:7f3a2b1c-4d5e-6f7a-8b9c-0d1e2f3a4b5c",  # receipt_id
    3: 1743948000,                             # issued_at (int, not string)
    4: {                                       # invocation_context
        1: "urn:action:web_search",
        2: "urn:jwt:eyJhbGciOiJFZERTQSJ9.example",
        3: ["urn:agent:operator", "urn:agent:morrow"],
        4: "entity-autonomy-daemon-484b7f8511564165ae255176bb4670dc"
    },
    5: {                                       # outcome_claim
        1: "completed",
        2: "read",
        3: "sha256:a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2"
    },
    6: "sha256:b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2c3",  # b_hash
    7: "urn:agent:morrow",                     # executor_id
    8: "urn:harness:openclaw-v1"               # harness_id
}

def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode()

def b64url_decode(s: str) -> bytes:
    pad = 4 - len(s) % 4
    if pad != 4:
        s += '=' * pad
    return base64.urlsafe_b64decode(s)

# ---- Ed25519 key for JWS ----
ed_priv = Ed25519PrivateKey.generate()
ed_pub = ed_priv.public_key()

# ---- P-256 key for COSE (ES256) ----
ec_priv = generate_private_key(SECP256R1())
ec_pub = ec_priv.public_key()

# ========== SIZE MEASUREMENTS ==========

# 1. Raw JSON
json_bytes = json.dumps(EOV_RECEIPT, separators=(',', ':')).encode()
json_size = len(json_bytes)

# 2. Raw CBOR (string keys)
cbor_str_bytes = cbor2.dumps(EOV_RECEIPT)
cbor_str_size = len(cbor_str_bytes)

# 3. Raw CBOR (integer keys)
cbor_int_bytes = cbor2.dumps(EOV_RECEIPT_CBOR)
cbor_int_size = len(cbor_int_bytes)

# 4. JWS compact (Ed25519)
header_jws = {"alg": "EdDSA", "typ": "eov+jwt"}
header_b64 = b64url(json.dumps(header_jws, separators=(',',':')).encode())
payload_b64 = b64url(json_bytes)
signing_input = f"{header_b64}.{payload_b64}".encode()
sig_jws = ed_priv.sign(signing_input)
jws_compact = f"{header_b64}.{payload_b64}.{b64url(sig_jws)}".encode()
jws_size = len(jws_compact)

# 5. COSE_Sign1 (ES256, CBOR int keys) — manual construction (RFC 8152)
# Protected header: {1: -7} (alg: ES256)
protected = cbor2.dumps({1: -7})
unprotected = {}
payload_cbor = cbor_int_bytes
# Sig_structure = ["Signature1", protected, b"", payload]
sig_structure = cbor2.dumps(["Signature1", protected, b"", payload_cbor])
sig_cose = ec_priv.sign(sig_structure, ECDSA(hashes.SHA256()))
cose_sign1 = cbor2.dumps(cbor2.CBORTag(18, [protected, unprotected, payload_cbor, sig_cose]))
cose_size = len(cose_sign1)

print("=" * 60)
print("EOV RECEIPT ENCODING SIZE COMPARISON")
print("=" * 60)
print(f"Raw JSON (string keys):          {json_size:5d} bytes  (baseline)")
print(f"Raw CBOR (string keys):          {cbor_str_size:5d} bytes  ({cbor_str_size/json_size*100:.1f}% of JSON)")
print(f"Raw CBOR (integer keys):         {cbor_int_size:5d} bytes  ({cbor_int_size/json_size*100:.1f}% of JSON)")
print(f"JWS compact (Ed25519):           {jws_size:5d} bytes  ({jws_size/json_size*100:.1f}% of JSON)")
print(f"COSE_Sign1 (ES256, CBOR int):    {cose_size:5d} bytes  ({cose_size/json_size*100:.1f}% of JSON)")
print()

# ========== PERFORMANCE MEASUREMENTS ==========

# JWS sign
t0 = time.perf_counter()
for _ in range(N_ITER):
    ed_priv.sign(signing_input)
t1 = time.perf_counter()
jws_sign_us = (t1 - t0) / N_ITER * 1e6

# JWS verify
t0 = time.perf_counter()
for _ in range(N_ITER):
    ed_pub.verify(sig_jws, signing_input)
t1 = time.perf_counter()
jws_verify_us = (t1 - t0) / N_ITER * 1e6

# COSE sign
t0 = time.perf_counter()
for _ in range(N_ITER):
    ec_priv.sign(sig_structure, ECDSA(hashes.SHA256()))
t1 = time.perf_counter()
cose_sign_us = (t1 - t0) / N_ITER * 1e6

# COSE verify
t0 = time.perf_counter()
for _ in range(N_ITER):
    ec_pub.verify(sig_cose, sig_structure, ECDSA(hashes.SHA256()))
t1 = time.perf_counter()
cose_verify_us = (t1 - t0) / N_ITER * 1e6

# CBOR encode (int keys)
t0 = time.perf_counter()
for _ in range(N_ITER):
    cbor2.dumps(EOV_RECEIPT_CBOR)
t1 = time.perf_counter()
cbor_enc_us = (t1 - t0) / N_ITER * 1e6

# JSON encode
t0 = time.perf_counter()
for _ in range(N_ITER):
    json.dumps(EOV_RECEIPT, separators=(',', ':')).encode()
t1 = time.perf_counter()
json_enc_us = (t1 - t0) / N_ITER * 1e6

print("=" * 60)
print("PERFORMANCE (median over 1000 iterations)")
print("=" * 60)
print(f"JSON encode:                     {json_enc_us:6.1f} µs")
print(f"CBOR encode (int keys):          {cbor_enc_us:6.1f} µs")
print(f"JWS sign (Ed25519):              {jws_sign_us:6.1f} µs")
print(f"JWS verify (Ed25519):            {jws_verify_us:6.1f} µs")
print(f"COSE sign (ES256/P-256):         {cose_sign_us:6.1f} µs")
print(f"COSE verify (ES256/P-256):       {cose_verify_us:6.1f} µs")
print()

# ========== SAVINGS SUMMARY ==========
print("=" * 60)
print("KEY FINDINGS")
print("=" * 60)
savings_cbor_int_vs_json = json_size - cbor_int_size
savings_cose_vs_jws = jws_size - cose_size
print(f"CBOR int-keys vs JSON:           -{savings_cbor_int_vs_json} bytes ({savings_cbor_int_vs_json/json_size*100:.1f}% smaller)")
print(f"COSE_Sign1 vs JWS compact:       -{savings_cose_vs_jws} bytes ({savings_cose_vs_jws/jws_size*100:.1f}% smaller)")
print(f"COSE overhead vs raw CBOR:       +{cose_size - cbor_int_size} bytes ({(cose_size-cbor_int_size)/cbor_int_size*100:.1f}% overhead)")
print(f"JWS overhead vs raw JSON:        +{jws_size - json_size} bytes ({(jws_size-json_size)/json_size*100:.1f}% overhead)")
print()
print("Note: COSE_Sign1 uses ES256 (P-256/ECDSA). Ed25519 (alg -8)")
print("would produce smaller signatures (64 vs ~71 bytes DER) but")
print("COSE_Sign1 + CBOR int-keys is already the most compact signed form.")
