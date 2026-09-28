# Laya Baseline — SOC Triage Eval v0 (Phase 0.3)

*2026-09-26 · control host · datasets + runner in `evals/`, raw reports in `evals/results/`.*

## Data provenance (be skeptical of the labels)

Source: `~/.openclaw-soc/audit_log.jsonl` (9.6 MB, schema 1). Filter:
`agent_id=soc-triage`, `outcome=ok`, `model_output` parses as JSON containing
`severity_class` + `recommended_response`. Deduped by `input_hash` (−32).
Result: **68 labeled rows**.

| Label | Distribution |
|---|---|
| severity | high 28 · medium 37 · informational 3 |
| response | page 25 · digest_only 33 · email 7 · note_only 3 |
| known_pattern | bool (expected) |
| escalate (low_confidence) | True 53 · False 13 |

**Caveats — read before citing any number:**
1. Ground truth = the SOC LLM's **own historic decisions** (96 of 100 rows
   `minimax-m3:cloud`, 4 test-era `m`) — model-as-judge, not human labels.
2. Eval state = `input_summary` only (~30 chars, e.g. `L12 5763 agent=mail.example.com`).
   The historic LLM decided on the full alert; our states are thinner.
   Some of the accuracy gap is **state fidelity**, not model quality.
3. `escalate` ground truth is the minimax-era `low_confidence` flag — a model
   quirk (78% True), not an objective outcome. Treat as unreliable.
4. n=68, skewed classes — every number is ±noise. This is a **direction check**,
   not a gate decision.

## Question set v0 (`soc-triage-v0.jsonl`)

`severity` (choice: high/medium/low/informational) · `response` (choice:
page/email/digest_only/note_only) · `known_pattern` (noul) · `escalate` (noul,
row-conditional). Format is upstream `laya-evals`-compatible JSONL — migrate to
`laya-evals run` when a PyPI release ships the harness (0.3.20 has no
`laya.evals`; runner here: `evals/run_baseline.py`, CPU, LAYA_THREADS=8).

## Results (base checkpoints, zero-shot, CPU)

Latency: **p50 ≈ 365–372 ms, p95 ≈ 387–389 ms per row** (3–4 questions, CPU,
all checkpoints preloaded). Compare: 16–78 s per gemma-31B turn.

| Question | english acc | typed-decisions acc | majority acc |
|---|---|---|---|
| severity | **0.015** | **0.559** | 0.544 |
| response | 0.309 | **0.588** | 0.485 |
| known_pattern | **0.912** | 0.897 | 0.897 |
| escalate | 0.182 | 0.182 | 0.803 |

Mean `answer_confidence`: english severity 0.33 / known_pattern 0.91;
typed-decisions severity 0.32 / known_pattern 0.79. Full detail incl.
confusion matrices: `evals/results/baseline-*.json`.

## Read

1. **typed-decisions ≫ english for SOC question sets.** english collapses
   severity (66/68 → "low") and response (mostly note_only). Don't use english
   for SOC triage decisions.
2. **known_pattern (noul) is strong zero-shot** (0.90+, calibrated-looking).
   First shadow-mode candidate — it's also a safe one (screening gate, not an
   action).
3. **severity/response at majority level only** (0.559 / 0.588 vs 0.544 / 0.485).
   typed-decisions beats majority but by a margin within noise. Zero-shot is
   **not gateable** for these — matches the Phase 4 fine-tune rationale.
4. **escalate is a broken target, not a broken model.** Laya says "don't
   escalate" while the historic flag says low-confidence 78% of the time.
   Redefine escalation ground truth in Phase 1 (outcome-derived: did a human
   act / did the LLM get corrected later?).
5. **State builders are the next lever.** v0 states are 30-char summaries.
   Phase 1.2 must reconstruct richer states (rule level/id, agent, decoded
   alert fields ≤512 tok) and the eval re-run should isolate how much of the
   severity/response gap is state fidelity. A dumb rule-level→severity
   heuristic baseline should be added to the same harness for comparison.

## Verdict for Phase 0.3 exit

- Eval baseline recorded ✓ (this doc + JSONs, committed).
- Question sets v0 defined ✓.
- ≥200/label target **NOT met** (68 rows; the audit log simply contains ~100
  structured decisions total). Supplement before any gated cutover:
  **wazuh rule-level ground truth from edge host** (objective `rule.level` →
  severity mapping) — tracked in TODO Phase 0.3. **DONE 15:36:** 616-alert
  objective sample pulled (see addendum below).
- gemma-31B spot-check (30-sample manual audit) — **DONE 15:4x, see addendum**.

---

## Addendum 2026-09-26 15:4x — gemma spot-check + LLM-volume baseline

### gemma-4-31B spot-check (23 rows, stratified, via :15108 proxy)

The SOC's actual current LLM (gemma) on the same eval states, asked for the
triage JSON (30 requested; 23 valid JSON parses — gemma sometimes returned
parseable-with-extraction output; latencies 14-33 s, mean **20.9 s** per turn,
460 s total for 23 — the single-slot decode cost is real):

| Question | gemma acc vs historic (minimax) labels | Laya typed-decisions acc |
|---|---|---|
| severity | **0.565** (n=23) | 0.559 (n=68, thin states) |
| response | **0.478** (n=23) | 0.588 (n=68) |

gemma distribution: severity high 20 / informational 3 (sample had high 10 /
medium 10 / informational 3) — **gemma over-predicts "high" and "page"**
(87% page). Laya's 0.588 response accuracy **beats the current LLM's 0.478**
against the same labels. Neither model agrees with the historic labels much
better than majority — reinforcing that (a) labels are one LLM's opinions, and
(b) Phase 4 fine-tuning needs human/outcome labels, not model-as-judge.

**Three-way read:** for `response`, Laya ≥ gemma (0.588 vs 0.478) at ~1/50th
the latency (0.9 vs 20.9 s). For `severity`, both sit at majority level — but
severity is deterministic from rule level anyway (rich-state eval), so the
right severity decision-maker is a dict lookup, not any model.

### LLM-volume baseline (Phase 2.3 "before" measurement)

From audit-log turns, 30-day window (2026-08-26..09-24, 27 data days):

| Agent | Total | Avg/day |
|---|---|---|
| ~~soc-ticket-creator~~ | ~~2,944~~ | ~~109.0~~ | ← **NOT an LLM: ticket-creation events** (template POSTs to soc-tickets-mcp, no model_output/duration) — excluded 17:0x |
| soc-triage | 959 | **35.5** |
| soc-narrator | 957 | **35.4** |
| soc-stig-remediate | 227 | 8.4 |
| soc-stig-classifier | 134 | 5.0 | ← deterministic dict lookup — not a model decision

**Real Laya-offloadable LLM surface: ~79 turns/day** (triage 35.5 + narrator 35.4
+ stig-remediate 8.4). Snapshot: `evals/llm-baseline-snapshot.json`; continuous
series: `evals/llm-volume.jsonl` (cron 10 6 * * * control host). Caveats: llama.cpp
counters were reset by a recent restart (all zero) — journal + audit log are the
baseline sources. **Stack was operator-OFF at capture time** (power=off since
01:49 UTC; fixed + verified full-cycle 16:4x, commit ad9f581).

### soc-ioc-enricher contract (Phase 2.2 extraction)

Typed finding per indicator (`reputation` ∈ malicious|suspicious|neutral|
unknown + confidence + sources + fleet history), triggered by soc-triage when
external evidence is needed. **0 rows in the audit log** — it never fired
historically, so there is no live hookable path. Question set defined
(`evals/laya_questions.yaml:ioc_enrich`: reputation choice + needs_enrichment
noul) for when a trigger path exists. Full contract in
`soc-agents/soc-ioc-enricher/IDENTITY.md`.

### Phase 0.3: CLOSED

All items done or dispositioned. Phase 2 gating waits on shadow soak
(≥300 decisions) + threshold calibration — nightly agreement job is live.

## Next

Phase 1: state builders (rich alert states), shadow runner on ingest+triage,
re-run this eval on rebuilt states to separate state-fidelity from model
quality, then fine-tune (Phase 4) on logged decisions + objective labels.
---

## Addendum 2026-09-26 15:4x — gemma spot-check + LLM-volume baseline

**LLM-volume baseline (Phase 2.3 "before" measurement)** — from audit_log turns,
30-day window (2026-08-26..09-24, 27 data days): soc-ticket-creator 109/day,
soc-triage 35.5/day, soc-narrator 35.4/day, stig-remediate 8.4/day,
stig-classifier 5.0/day. Snapshot: `evals/llm-baseline-snapshot.json`.
Caveat: llama.cpp counters were reset by a recent restart (all zero) — journal
+ audit log are the baseline sources. **Stack was operator-OFF at capture time**
(power=off since 01:49 UTC) — noted there too.

**soc-ioc-enricher contract (Phase 2.2 extraction)**: typed finding per
indicator: `reputation` ∈ malicious|suspicious|neutral|unknown + confidence +
sources + fleet-history. Trigger: soc-triage calls it when external evidence is
needed; 0 rows in the audit log (never fired historically) → no hookable live
path yet; question set defined for when it does (repo: evals/laya_questions.yaml).
