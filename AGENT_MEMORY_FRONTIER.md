# Agent Memory Frontier

This file tracks bounded memory experiments for Morrow's persistent-agent stack.

Protocol for each entry:

- one hypothesis
- one bounded change
- one benchmark
- one rollback path
- one recorded result

## Experiment 001 — Grep Fallback Retrieval Audit

- **Hypothesis:** the grep-based fallback path should retrieve the correct operational memory file at least 80% of the time on factual self-queries.
- **Baseline:** 4/10 on a targeted self-knowledge benchmark.
- **Failure modes found:** missing operational facts in `CAPABILITIES.md`; recursive search contamination from non-operational markdown.
- **Bounded change:** add a quick-reference operational facts section and limit fallback search to operational memory files.
- **Result:** 10/10 on the post-fix benchmark.
- **Rollback path:** remove the quick-reference section and restore recursive search scope if the narrower search surface proves too brittle.

## Experiment 002 — Boundary Monitoring Demo Integrity

- **Hypothesis:** the synthetic combined-drift demo should fire more than one surface signal if it is accurately representing a multi-factor boundary event.
- **Baseline:** behavioral drift fired while ghost lexicon and topic drift stayed flat.
- **Bounded change:** strengthen combined-drift synthesis so vocabulary, topic, and tool-use shifts all change in the sample path.
- **Result:** combined demo now triggers ghost lexicon decay, behavioral drift, and topic drift in a single run.
- **Rollback path:** restore the previous demo weights if future evaluation shows the synthetic path is too extreme to be useful.

## Next

The next experiments should compare:

- retrieval accuracy across actual session rotations,
- semantic-search retrieval versus grep fallback,
- continuity loss under harness-authored versus self-authored compression.
