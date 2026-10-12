# examples/ — Discrete mathematics with Laya

A hands-on workspace that teaches the honest division of labor between a
**System 1 decision model** (Laya: typed questions, calibrated confidence,
single forward pass, ~0.3 s on CPU) and a **deterministic System 2 engine**
(`dm_core.py`: exact discrete mathematics in pure stdlib Python).

The one-line lesson of every tutorial: **laya never carries the math.** It
routes, tags, and gates; `dm_core` computes, proves, and answers.

## Files

| File | What it teaches |
|---|---|
| `check_dm_core.py` | trust anchor: 44 hard asserts on the engine (run first) |
| `dm_core.py` | deterministic engine: truth tables, set-identity counterexamples, gcd/primality/totient, counting, graph algorithms, recurrences |
| `laya_math.py` | the shared `DM` client (stdlib urllib; `/health` + `/v1/systemone`), answer readers, the `tau_gate` idiom |
| `probe_capability.py` | six measured suites (80 calls) = the capability study data |
| `t01_routing.py` | route with laya, answer with the engine (measured routing accuracy) |
| `t02_logic_gate.py` | verdict gating with a tau threshold; what the gate catches (indecision) and what it cannot (confident error) |
| `t03_sets_formalize.py` | formalization checking (laya) + counterexample adjudication (engine) |
| `t04_combinatorics_grade.py` | why numeric answers must be computed first (laya at chance on numbers) |
| `t05_graphs_edge_list.py` | graph properties from text: mediocrity measured; BFS exact |
| `t06_number_theory.py` | engine showcase + laya as (weak, nay-biased) answer auditor |
| `t07_quiz.py` | the tutor loop that ships: engine grades, laya tags misconceptions, policy escalates |
| `training/make_dataset.py` | deterministic generator for labelled decision datasets (evals/finetune format) |
| `training/FINETUNE.md` | the recipe: dataset -> finetune() -> calibration -> eval gates |

## Quickstart

```bash
# point at a running laya-serve (see ../docs/LAYA-SETUP.md to install one)
export LAYA_URL=http://127.0.0.1:8099

python3 check_dm_core.py          # engine truth first (no laya needed)
python3 probe_capability.py       # the measured capability study (~80 calls)
for t in t0*.py; do python3 "$t"; done
```

## Measured verdicts (zero-shot, english checkpoint, CPU)

| suite | laya alone | with the house pattern (gate -> engine) |
|---|---|---|
| domain routing (24 q) | **0.875** | escalation on low confidence -> dispatch |
| formula verdicts (16) | 0.688 | gate catches indecision; system 0.625 this run, misses printed |
| formalization (10) | 0.700 | engine adjudicates with counterexamples |
| graph properties (8x2) | 0.750 / 0.250 | **BFS / 2-coloring: 1.000, always** |
| answer audit (14) | 0.600 (probe) / 0.400 (worded) | engine is the calculator; laya nay-biased |
| numeric quiz (12) | **0.250 = chance** | engine computes first; laya tags the learner |

Latency: p50 ~315-330 ms, p95 ~470-490 ms per call on CPU (single inference
worker; requests queue — do not point high-rate pollers at laya-serve).

## Honesty section (read before building)

- Laya **never generates text** — there is nothing to parse, nothing to
  hallucinate; and there is nothing that can write a proof either.
- Numbers are token soup to the encoder: 4-option numeric QA lands at chance.
- Confident-error exists (wrong argmax with high confidence) — the tau gate
  cannot save those; per-type eval baselines (docs/laya-baseline.md) can.
- Options share a per-checkpoint presentation effect on sequential-layout
  checkpoints; see the upstream docs (`option_order` rotations) before
  averaging decisions.

## Where to go next

- `training/` — build a discrete-math decision dataset and fine-tune (that
  is where tag/verdict quality is bought: base 0.362 -> 0.766 upstream).
- `../docs/LAYA-DISCRETE-MATH.md` — the full capability study write-up.
- Terminal recordings of every run are published as gists (open the raw
  `.cast` URL in an asciinema player embed, or `asciinema play` the local
  copy):
  - probe — <https://gist.github.com/dmrobbi/8bc162c9c710e9bb68c979a1293ee33f>
  - examples (t01–t07) — <https://gist.github.com/dmrobbi/8cbc6178e54797264e21162b254afdd9>
  - engine verify — <https://gist.github.com/dmrobbi/40534e2962525ab87a76f3a3d2f89684>
  - publish + verify — <https://gist.github.com/dmrobbi/12264e3c798a40518749a657ff11dc3f>