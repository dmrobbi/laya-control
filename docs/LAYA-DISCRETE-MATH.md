# Laya × discrete mathematics — capability study, tutorials, and training kit

*2026-10-12 · Dawn Robbins · repo: laya-control*

**TL;DR.** Laya is a *decision model* — it answers typed questions
(`choice` / `score` / `noul`) with calibrated probabilities in one forward
pass and **never generates text**. That shapes the honest answer to "can it
do discrete mathematics": it cannot carry the math, and no prompt will
change that. What it does measurably well is the natural-language decision
layer around the math. The pattern that ships: **Laya routes, checks, tags,
and gates — a deterministic stdlib engine (`examples/dm_core.py`) computes.**
This doc records the measured study; `examples/` contains seven runnable
tutorials, the capability probe, and a fine-tune dataset generator.

---

## 1. What Laya is (shipped facts)

Open-source (Apache-2.0), non-autoregressive "System 1" decision engine —
upstream: <https://github.com/NandhaKishorM/laya>, checkpoints:
<https://huggingface.co/convaiinnovations/laya>. Training = RLCD
(reinforcement learning against strictly proper scoring rules): reporting
honest probabilities is the *only* way to maximize reward, so the confidence
field is a designed feature, not an afterthought.

| checkpoint | encoder | params | context | use |
|---|---|---|---|---|
| `english` | ModernBERT-large | 421M | 512 | English short states (router default) |
| `multilingual` | mmBERT-base | 322M | 1024 (→8192 via max_len) | 100+ languages, 2× faster |
| `typed-decisions` | ModernBERT-large | 421M | 1024 | fine-tuned typed workflows (0.766 vs 0.362 base) |

House serving (this repo, docs/LAYA-SETUP.md): `laya-serve` on the control
host, loopback-only, CPU, all three checkpoints preloaded, `POST
/v1/systemone {state, questions, model?}` — max 64 questions, max 50k-char
state, single inference worker (requests queue; `/health` never queues).

## 2. What a decision model cannot do for discrete math

Measured, not assumed (§3):

1. **No generation.** Laya emits typed answers over a given state. It cannot
   write a proof, a derivation, an explanation, or code — ever. A study
   tool needing explanations needs a generative layer alongside.
2. **Numbers are token soup.** Ask 12 four-option numeric questions and it
   scored **3/12 = 0.250 — exactly chance** — while honestly reporting low
   confidence (mean 0.163). It is not "bad at arithmetic" in a fixable way;
   numeric magnities are not represented as magnitudes at all.
3. **Verdict/audit noul is weak and biased.** On "is this proposed answer
   correct?" rows the noul read 0.06–0.60 with argmax "no" on most rows: it
   **misses true claims almost systematically** (0/5 in the all-worded
   suite) while rejecting most false ones. A nay-biased filter, not a judge.
4. **Graph properties from text encode poorly.** Connectivity 0.750,
   bipartiteness 0.250 from edge-list text. BFS is microseconds and exact.
5. **Confident error exists.** `~(p & q)` with q irrelevant-but-false-sat
   read as "not satisfied" at 0.83 confidence — the tau gate cannot catch
   confident error, only indecision (§4).

## 3. The measured capability study

Environment: laya-serve 0.3.20, CPU (`LAYA_DEVICE=cpu`), loopback endpoint,
sequential calls, zero-shot `english` checkpoint (Router default routing).
Probe: `examples/probe_capability.py` → `probe_results.json`.

| suite | n | laya zero-shot | verdict |
|---|---|---|---|
| A domain routing (choice, 6 ways) | 24 | **0.875** | genuinely strong — ship it |
| B formula verdicts (noul) | 16 | 0.688 direct / 0.938 gated system | triage-quality |
| C formalization match (noul) | 10 | 0.700 | misses subtle quantifier swaps |
| D graph connected / bipartite (noul) | 8×2 | 0.750 / 0.250 | weak — engine computes |
| E answer audit (noul) | 10 | 0.600 (mixed worded+bare) | nay-biased filter |
| F numeric quiz (choice, 4 options) | 12 | **0.250 = chance** | engine computes first |

Latency over the 80 probe calls: p50 **295 ms**, p95 518 ms, max 591 ms
(CPU; one inference worker). Suite notes worth keeping:

- **Routing misses are instructive:** a stars-and-bars counting question
  routed to `recurrence` (the word "solutions"), a relation-property
  question to `combinatorics`, totient to `combinatorics`. Routing
  confidence was mid-range (0.14–0.44) on exactly those rows — a usable
  humility signal for the gate.
- **The same verdict question scored differently under one extra sentence
  of state text:** probe suite B (state ends with a rubric sentence)
  direct-hits 11/16; tutorial t02 (same pairs, no rubric sentence)
  direct-hits 6/16. Both runs recorded. Prompt-sensitivity at zero-shot is
  *real* — another reason the deliverable quality lives in the gate + the
  measured baseline, not in prompt craft.
- **Gate arithmetic (t02, the honest version):** direct 6/16, escalations
  4/16 (resolved exactly by the engine), laya-wrong-and-accepted 6/16 →
  system accuracy 10/16 = 0.625. The gate upgrades humble-but-right and
  humble-but-wrong alike; it cannot upgrade confident-wrong. In the SOC the
  same lesson is why per-type eval baselines (docs/laya-baseline.md) decide
  what may auto-act.
- **Set identities:** laya confirmed the obvious mismatches but confidently
  affirmed both subtly-wrong formalizations ("B subseteq A" 0.743,
  conjunction-instead-of-implication 0.907). The engine's brute-force
  counterexample machine (`dm_core.set_identity_check`) answers the same
  question with a concrete witness in every case — the strongest evidence a
  study tool can cite.
- **Misconception tagging (t07):** zero-shot tag choices came back with
  confidences 0.03–0.21 — weak triage. The tutor escalates on policy
  (repeat-miss family), never on tag trust.

## 4. The architecture that works

```
 learner/task (natural language, math in it)
      │
      ▼
 [Laya route]    choice: which engine/branch?        ~0.3 s CPU
      │   low route confidence → escalate instead
      ▼
 [dm_core]       deterministic compute + evidence    exact, offline
      │  (truth tables · counterexamples · BFS · counts · totients)
      ▼
 [Laya tag/audit]  classify the learner's wrong answer into a misconception
      │   family; audit worded claims (weak — human-read tail)
      ▼
 [tau gate]      |p − 0.5| < τ → escalate to the engine / a worked example;
                 tau is POLICY, picked from measured accuracy-at-coverage
```

Division of labor:

| job | owner | why |
|---|---|---|
| which domain/engine? | laya (`choice`) | language judgment; measured 0.875 |
| every number, table, property | `dm_core` | exact; provable; offline |
| is this assignment/text coherent? | laya (`noul`) | only as triage with a human/escalation tail |
| what did the learner misunderstand? | laya (`choice` over taxonomy) | language judgment; fine-tune buys the accuracy |
| when to walk through a worked example | gate + policy | confidence orders; policy decides |
| anything numeric | engine | laya scored 0.250 on 4-option numeric QA |

## 5. The tutorials (`examples/`)

Each tutorial self-asserts its engine truth and *measures* laya (never
asserts it). Run order teaches the pattern:

| file | lesson |
|---|---|
| `t01_routing.py` | route with laya → dispatch the engine → exact answer |
| `t02_logic_gate.py` | tau-gated verdicts; what the gate catches and what leaks |
| `t03_sets_formalize.py` | laya checks the phrasing; engine counterexamples decide identities |
| `t04_combinatorics_grade.py` | numeric QA = chance → compute first, ask later |
| `t05_graphs_edge_list.py` | edge-list text: encoder mediocrity vs BFS exactness |
| `t06_number_theory.py` | engine showcase (Fermat's evidence/proof asymmetry) + nay-biased audit |
| `t07_quiz.py` | the tutor loop that ships: engine grades, laya tags, policy escalates |

```bash
export LAYA_URL=http://127.0.0.1:8099     # or any laya-serve
python3 examples/check_dm_core.py         # 44 engine asserts, offline
python3 examples/probe_capability.py      # the study, reproducible
python3 examples/t01_routing.py           # ... through t07
```

## 6. Training for people who want better decisions

`examples/training/` carries the recipe (`FINETUNE.md`) and a deterministic
dataset generator (`make_dataset.py`; same seed → byte-identical rows;
sample output committed under `training/sample/`). Shape of the loop:

1. **Generate** labelled rows in the upstream format (`state` / `questions`
   / `expected` / `tags` / `language`) — three families: `verify` (noul),
   `classify` (tautology/contradiction/contingent), `tag` (misconception).
2. **Baseline** the shipped checkpoint with `laya-evals` (the pre-train
   score is what the fine-tune must beat).
3. **Fine-tune** with upstream's RLCD loop — Kaggle 2×T4 notebook (~4-5 h
   for 4 epochs over ~30k questions) or the MPS script; API form
   `finetune("train.jsonl", base, out, TrainConfig(option_layout="parallel"))`.
   The parallel option layout removes the measured presentation-order
   effect (100% same-answer-under-shuffle vs 91.7% sequential).
4. **Calibrate** (one temperature per question type) and **gate** on
   held-out data (`--max-ece`, `--tolerance choice_accuracy=...`) —
   held-out or it did not happen.

What a fine-tune buys: the decision layers (route/tag/verdict/classify) —
upstream measured 0.362 → 0.766 on-domain. What it never buys: generation
or arithmetic. The engine stays the calculator by design.

## 7. Honest limits (the checklist to keep next to any deployment)

- no generation, no arithmetic; numbers via `dm_core` only
- zero-shot verdicts/audits are weak and nay-biased; use as triage + human tail
- the tau gate catches indecision, never confident error
- state budgets: 512 tokens (`english`) / 1024 (`multilingual`,
  `typed-decisions`) — states are built compactly, never raw turns
- >20 options per choice degrade (token-budget sharing); shortlist first
- option order moves sequential-layout decisions; prefer a parallel-layout
  checkpoint or `option_order` rotation averaging (upstream `option_order`)
- one inference worker: sequential or modest-rate callers only
- confidence is calibrated to the checkpoint's own evals; re-fit
  temperatures after any fine-tune and re-check with held-out data

## 8. Reproduce

Everything above is reproducible from this repo with no keys:

```bash
export LAYA_URL=http://127.0.0.1:8099
python3 examples/probe_capability.py           # writes probe_results.json
python3 examples/check_dm_core.py              # engine = 44/44 asserts
for t in examples/training ... training/make_dataset.py --seed 7 ...
```

Terminal recordings (`asciinema .cast`, player-ready, gist links below):
a capability-probe run, a full examples run, an engine verification run,
and the publish/verification run.

**Terminal recordings (public gists, raw `.cast` — open in the asciinema
player or `asciinema play`):**

- probe run — (link added in the recordings commit)
- examples run — (link added in the recordings commit)
- engine verify — (link added in the recordings commit)
- publish + verify — (link added in the recordings commit)