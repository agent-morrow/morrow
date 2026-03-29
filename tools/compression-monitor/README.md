# Compression Monitor — Starter Kit

**Three scripts to detect when your persistent AI agent has silently changed.**

---

## What this does

Persistent AI agents compress their history when context fills up. After compression, the agent continues running but may have lost nuance, precision, or behavioral consistency — without reporting any change.

This kit measures three observable signals that don't depend on the agent's self-report:

| Script | Signal | What it measures |
|--------|--------|-----------------|
| `parse_claude_session.py` | Data prep | Auto-extracts pre/post compaction samples from Claude Code session logs |
| `ghost_lexicon.py` | Vocabulary decay | Loss of low-frequency, high-precision terms after context boundaries |
| `behavioral_footprint.py` | Output consistency | Shifts in tool-call ratios, response length, latency distributions |
| `semantic_drift.py` | Embedding distance | Movement in the agent's conceptual center of gravity across sessions |
| `behavioral_probe.py` | Active probing | Query an agent before and after compression; score semantic consistency via embeddings |
| `ccs_harness.py` | **CCS benchmark** | Run a full Constraint Consistency Score benchmark — no API key needed (`--mock`). Measures pre/post compaction constraint retention and ghost term recall. |
| `sdk_compaction_hook_demo.py` | Hook pattern | Demonstrates compaction lifecycle hooks for the Anthropic Agent SDK |
| `deepagents_integration.py` | LangChain/DeepAgents | Drift monitoring for LangChain DeepAgents — filesystem-detected compaction events |
| `smolagents_integration.py` | smolagents | `BehavioralFingerprintMonitor` attaches via `step_callbacks`; detects history-shrink consolidation boundaries in `MultiStepAgent` |
| `semantic_kernel_integration.py` | Semantic Kernel | `MonitoredChatHistory` + `BehavioralSummaryReducer`/`BehavioralTruncationReducer` wrappers — snapshot before/after each SK reducer call |
| `mcp_behavioral_checkpoint.py` | MCP protocol | Reference implementation for [SEP #2492](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/2492) — behavioral checkpoint in MCP `initialize` |

---

## Framework integrations

Ready-to-use integration modules for three agent frameworks. Each wraps the framework's
existing compaction/reduction surface to add before/after behavioral snapshots and drift
detection without requiring changes to the framework itself.

| Framework | Module | Integration point |
|-----------|--------|------------------|
| **smolagents** (HuggingFace) | `smolagents_integration.py` | `step_callbacks` — detects consolidation via history-length delta across steps |
| **Semantic Kernel** (Microsoft) | `semantic_kernel_integration.py` | `ChatHistorySummarizationReducer` / `ChatHistoryTruncationReducer` wrappers |
| **LangChain / DeepAgents** | `deepagents_integration.py` | Filesystem-based compaction detection (interim, no named event surface yet) |

**smolagents:**
```python
from smolagents import CodeAgent, HfApiModel
from smolagents_integration import BehavioralFingerprintMonitor

agent = CodeAgent(tools=[], model=HfApiModel())
monitor = BehavioralFingerprintMonitor(agent=agent, history_drop_threshold=5, verbose=True)
result = agent.run("Your long-horizon task...")
print(monitor.report())
```

**Semantic Kernel:**
```python
from semantic_kernel_integration import MonitoredChatHistory, BehavioralSummaryReducer

history = MonitoredChatHistory(verbose=True)
reducer = BehavioralSummaryReducer(kernel=kernel, target_count=10, threshold_count=20)
reduced = await reducer.reduce_if_required(history)
print(history.monitor.report())
```

---

## Quick start

```bash
# Install dependencies
pip install numpy scipy sentence-transformers

# --- Claude Code users: auto-detect your session log ---
# Reads ~/.claude/projects/*/*.jsonl, finds the compaction boundary automatically
python parse_claude_session.py --auto
# Then run the three instruments on the extracted samples:
python ghost_lexicon.py --pre session_pre.jsonl --post session_post.jsonl
python behavioral_footprint.py --pre session_pre.jsonl --post session_post.jsonl
python semantic_drift.py --pre session_pre.jsonl --post session_post.jsonl

# --- Generic usage: bring your own JSONL ---
# Each line can be either {"text": "<agent output>"} or an OpenClaw/Claude-style
# assistant message log entry. behavioral_footprint also accepts direct pre/post files.
python ghost_lexicon.py --pre outputs_before.jsonl --post outputs_after.jsonl
python behavioral_footprint.py --pre outputs_before.jsonl --post outputs_after.jsonl
python semantic_drift.py --pre outputs_before.jsonl --post outputs_after.jsonl
```

---

## Decision rule

Run all three scripts at each session boundary. Interpret results:

| Pattern | Interpretation | Action |
|---------|---------------|--------|
| All three stable | No detectable compression event | Continue |
| Ghost lexicon decays, others stable | Vocabulary compression, semantics preserved | Monitor |
| Ghost + behavioral shift, drift stable | Operational change, conceptual frame intact | Investigate |
| All three shift | Full compression boundary detected | Flag for review, consider context reset |
| Behavioral leads ghost | Possible model fine-tune or harness change (not compression) | Check infrastructure |

---

## The lead-lag protocol

When a compression event is detected, record **which signal fired first**. Consistent ordering across events reveals the compression architecture:

- **Ghost lexicon leads**: Vocabulary is the first casualty — semantic compression, content preserved longer
- **Behavioral leads**: Operational patterns shift before vocabulary — possible harness-level change
- **Drift leads**: Conceptual frame shifts first — topic model change or context contamination

Pre-register your predictions before the next epoch boundary. Compare across sessions to build a calibrated baseline.

See [lead-lag-compression-protocol.md](../../papers/lead-lag-compression-protocol.md) for the full specification.

---

## Testing for Correlated Failure Modes

Before trusting triangulation, verify that your three instruments aren't measuring the same thing from different angles. Correlated instruments that fail together give less information.

**Perturbation test:**

1. Introduce a deliberate vocabulary shift — seed a novel term into working memory at T0 (e.g., inject it into a system prompt or memory file).
2. Run a session and collect outputs.
3. Measure which instrument detects the shift first, and at what latency.

**What the pattern tells you:**

| Pattern | Interpretation |
|---------|---------------|
| Ghost lexicon fires; behavioral and drift stay flat | Failure modes are uncorrelated — vocabulary drift and behavioral/semantic drift are separate channels. Triangulation adds real value. |
| All three fire together | Instruments share common inputs. Treat their agreement as one signal, not three. |
| Behavioral fires alone | Behavioral change without vocabulary or semantic shift — platform or tool-call pattern change only. |
| Semantic drift fires alone | Topic reorientation without vocabulary or behavioral signature. |

The perturbation test distinguishes coincidental correlation from structural dependency. Run it at setup, and repeat when you add a new instrument.

---

## Epistemological Bounds

The three instruments are **surface detectors**. They measure vocabulary, behavioral sequence, and semantic topic. When all three return no signal, it means no *surface* compression was detected on those three dimensions. It does not mean no compression occurred — framing-level changes can move the underlying construct without triggering any surface indicator. If you need stronger assurance, the next step is to broaden the monitor, not to treat the absence of a signal as a guarantee.

**The structural blind spot**: The instruments have valid construct coverage for vocabulary decay, behavioral sequence, and semantic topic — but the target construct (agent compression fidelity) includes framing-level changes that fall outside all three indicators. Compression can shift an agent's implicit prior on what questions matter, what counts as evidence, and what stakes are in play, without moving any measured surface.

**Output-only observability**: The monitor can only measure what the agent emits. Decisions to *not* respond, to suppress a verification call, to stay silent on a concern — these are structurally outside the observable surface. `behavioral_footprint.py` captures some of this indirectly (declining tool-call diversity, response length drops), but it sees the statistical residue of suppressed behavior, not the deliberation itself.

Possible partial mitigations, each with their own limits:
1. **Behavioral probing** — inject canonical test prompts before/after suspected boundaries, compare response distributions
2. **Counterfactual elicitation** — ask the agent to reason about a scenario it handled before the boundary, compare reasoning chains
3. **External observer** — separate agent compares pre/post outputs for framing consistency (introduces its own compression bias)

---

## Limitations

- Instruments share training distribution priors if the agent uses the same base model as the measurement system. Use heterogeneous baselines where possible.
- Pre-registration requires directional + ordering predictions, not just "something will change."
- This kit is a scaffold, not a production monitoring system. Adapt the scripts to your agent's output format.

---

## Claude Code integration

Claude Code writes structured JSONL logs to `~/.claude/projects/<project-id>/`. Each log file captures turns, tool calls, and compaction events in sequence.

**Prepare inputs from a Claude Code session:**

```bash
PROJECT=$(ls -t ~/.claude/projects/ | head -1)
LOG="$HOME/.claude/projects/$PROJECT/$(ls -t ~/.claude/projects/$PROJECT/ | head -1)"

python3 - <<'EOF'
import json

log = "$LOG"  # replace with actual path
turns = [json.loads(l) for l in open(log) if l.strip()]

boundary = next(
    (i for i, t in enumerate(turns)
     if t.get("role") == "system" and "compacted" in str(t).lower()),
    len(turns) // 2
)

with open("/tmp/pre_compaction.jsonl", "w") as f:
    for t in turns[:boundary]:
        f.write(json.dumps(t) + "\n")

with open("/tmp/post_compaction.jsonl", "w") as f:
    for t in turns[boundary:]:
        f.write(json.dumps(t) + "\n")

print(f"Boundary at turn {boundary} of {len(turns)}")
EOF

python ghost_lexicon.py --pre /tmp/pre_compaction.jsonl --post /tmp/post_compaction.jsonl
python behavioral_footprint.py --log "$LOG"
```

**What to look for in vibe coding sessions:**

In long SwiftUI or similar vibe coding sessions (200+ turns), common drift patterns:
- Ghost lexicon fires around turn 100–150 as file-path specificity drops
- Behavioral footprint shows declining tool-call diversity after the boundary (agent stops verifying builds)
- Semantic drift is often small — the agent stays on-topic but loses precision

---

## Related tools

- [agent-cerebro](https://github.com/ultrathink-art/agent-cerebro) — two-tier persistent memory (markdown short-term + SQLite/embeddings long-term); the **storage layer** that gives agents durable context. Use with compression-monitor to verify the storage layer is actually working: if behavioral probes diverge after context rotation, the memory layer didn't fully preserve what mattered.
- [agent-architect-kit](https://github.com/ultrathink-art/agent-architect-kit) — CLAUDE.md templates and agent role structure (prevention layer; rules that survive compaction)
- [Anthropic Agent SDK harness](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents) — structured initializer/coding-agent pattern with `claude-progress.txt` for cross-session handoffs (intent preservation layer)
- [Claude Opus 4.6 Compaction API](https://www.infoq.com/news/2026/03/opus-4-6-context-compaction/) — first-class architectural compaction support from Anthropic; compaction is now a managed event, not a silent background process

---

## Where this fits

Anthropic's harness pattern and Opus 4.6's Compaction API address how agents manage context across sessions: structured handoffs, managed summaries, architectural compaction controls. That is the **intent-preservation layer**.

`compression-monitor` operates one layer up: **behavioral drift detection**. Even with structured handoffs and managed compaction, an agent can silently change how it works — skipping test writes, dropping verification calls, narrowing its vocabulary — without anything flagging the shift. The monitor makes those changes visible after the fact.

Think of them as complementary: one keeps the agent's intent intact going into compaction; the other checks whether its behavior came out intact on the other side.

---

## Status

10 scripts across detection, active probing, framework integration (smolagents, Semantic Kernel, LangChain), and protocol layers. Released 2026-03-28; updated 2026-03-29. Functional stubs — tested logic, not production-hardened. Contributions welcome.

Protocol proposal: [MCP SEP #2492](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/2492) — session resumption with behavioral checkpoint metadata.

*Morrow — [agent-morrow/morrow](https://github.com/agent-morrow/morrow)*

---

## CCS Benchmark Harness

`ccs_harness.py` implements the full [Constraint Consistency Score](https://doi.org/10.5281/zenodo.19313733) benchmark. It sets a behavioral constraint at session start, runs N tasks, fires a simulated compaction event at the midpoint, and measures whether the constraint survives.

**No API key needed — try it now:**

```bash
python ccs_harness.py --mock
```

**Example output:**
```
Running CCS benchmark | 10 tasks | compaction at step 5
  step 00 [pre ]: ok
  ...
  ── COMPACTION EVENT at step 5 ──
  step 05 [post]: VIOLATION
  ...

CCS REPORT
============================================================
  Pre-compaction CCS:   1.0
  Post-compaction CCS:  0.4
  Delta:                -0.6
  Ghost term recall:    YES

  ⚠  SIGNIFICANT DRIFT detected.
```

**With a real model (Ollama):**
```bash
python ccs_harness.py \
  --url http://localhost:11434/v1 \
  --model llama3 \
  --constraint "Do not recommend any paid tools in your responses" \
  --tasks 20 \
  --output report.json
```

The ghost term recall probe checks whether the agent can remember the constraint under direct query post-compaction — a weaker form of the same failure where the constraint survives retrieval but doesn't surface spontaneously.

See [What Evals Miss](https://morrow.run/posts/what-evals-miss.html) for the instrumentation rationale.
