# Fine-tuning Laya for the discrete-math workspace — the recipe

Everything here builds on the workspace in `examples/`. Read
`docs/LAYA-DISCRETE-MATH.md` first: it measures what the shipped checkpoints
do zero-shot (routing strong, verdicts/audit weak, numeric QA chance-level).
Fine-tuning is the lever that improves the **decision layers**. It does not
make Laya a math engine — `dm_core` stays the calculator.

## 0. What the shipped checkpoints already prove about fine-tuning

Upstream measured the same decisions two ways (typed-decisions benchmark,
2,000 decisions): base checkpoint 0.362, domain-fine-tuned **0.766** — above
the 0.735 teacher self-agreement ceiling. The gap is bought with data; the
recipe below builds that data for the discrete-math domain.

## 1. Generate the dataset (`training/make_dataset.py`)

```bash
python3 training/make_dataset.py --out-dir training_data \
    --verify 4000 --classify 2000 --tag 2000 --seed 7
```

Deterministic: same `--seed` reproduces the files byte-identically. Three
row families, ground truth from `dm_core` (exact):

| family | state | question | expected |
|---|---|---|---|
| `verify` | question + proposed answer | noul "consistent?" | true/false |
| `classify` | propositional formula | choice: tautology/contradiction/contingent | label |
| `tag` | drill + verified answer + learner's wrong answer | choice: misconception family | label |

Each row is the upstream format consumed by both `laya-evals` and
`laya.train`:

```json
{
  "state": "...",
  "questions": {"<qid>": {"type": "...", "...": "..."}},
  "expected": {"<qid>": <label | number | true/false>},
  "tags": ["family:...", "truth:..."],
  "language": "en"
}
```

Scale guidance: upstream's typed benchmark loop trained on ~30k questions for
4 epochs. Start with the three files above (~8k) to validate the pipeline
end to end, then scale by adding families and rotating seeds.

## 2. Gate the data BEFORE training (laya-evals)

> **Version note:** `laya-evals` ships with the upstream releases that carry
> `laya.evals`. The house decision venv pins `laya 0.3.20`, which predates
> it — run the eval gates from a separate venv with the current upstream
> release (`pip install -U laya`), or use the upstream notebook, which fits
> its own calibration inside the loop. The pins on the serving venv stay
> untouched.

```bash
laya-evals validate training_data/dm_verify.jsonl          # format check, no weights
laya-evals run training_data/dm_verify.jsonl --model english --device cpu \
    --json baseline_base_english.json                      # the pre-train score
```

Record the base score — it is the number the fine-tune has to beat, and the
reason you never "hope" a checkpoint is better than the last one.

## 3. Train (upstream tooling, Apache-2.0)

- Kaggle free 2xT4 (DDP): `notebooks/laya_finetune_typed_decisions_2xT4_kaggle.ipynb`
- Apple Silicon / CPU laptop: `notebooks/laya_finetune_typed_decisions_mps.py`
  (`--micro-batch 1 --grad-accum 32` on a 16 GB MacBook)
- API form: `finetune("train.jsonl", base, out, TrainConfig(option_layout="parallel"))`

```python
from laya.train import TrainConfig, finetune

finetune(
    "training_data/split_train.jsonl",   # concat your families; hold out 10%
    "convaiinnovations/laya",            # base checkpoint
    "./laya-dm-checkpoint",
    TrainConfig(option_layout="parallel"),
)
```

Why `option_layout="parallel"`: on sequential-layout checkpoints the
ORDER of answer options measurably moves the answer (upstream measured
91.7% same-answer-under-shuffle); the parallel layout scores every option at
its own position and reproduces its answers **100%** under shuffling. Both
upstream published checkpoints are sequential; a discrete-math checkpoint
should not inherit that quirk.

Budget upstream reported: 4-5 h on 2xT4 for 4 epochs over ~30k questions.
Gradient checkpointing (encoder + decision head) is enabled by the
notebooks.

## 4. Calibrate, then gate the result

```bash
# fit one temperature per question type from TRAINING data,
# then evaluate on the HELD-OUT slice only
laya-evals run training_data/held_out.jsonl --model ./laya-dm-checkpoint \
    --device cpu --json report_ft.json --max-ece 0.10 \
    --baseline baseline_base_english.json --tolerance choice_accuracy=0.02
```

- Calibration temperatures are part of the recipe (RLCD models are
  probability-reporting engines; ECE is the honest scoreboard).
- Never claim quality from numbers fit on training items; held-out or it
  did not happen.
- `laya-evals compare report_ft.json --baseline baseline_base_english.json
  --tolerance choice_accuracy=0.02` is the pass/fail gate; exit code goes
  into CI unchanged.

## 5. Wire it in (and what stays untouched)

- Routing stays `english`+`multilingual` per request unless you fine-tuned a
  router — keep the decision layers' checkpoint pinned in one place.
- The verdict gate (`laya_math.tau_gate`) is policy, not model output: pick
  tau from the measured accuracy-at-coverage of YOUR checkpoint.
- `dm_core` remains the answer of record for every number, table, and
  property. A deployed tutor that can grade wrong has a broken audit trail;
  this design keeps the authority deterministic.

## Honest expectations

| lever | what it buys | what it never buys |
|---|---|---|
| fine-tune | tag/verdict/classify accuracy (0.36 -> 0.77 upstream on-domain) | arithmetic ability, text generation |
| calibration | trustworthy confidence + honest gates | higher accuracy |
| parallel layout | order-invariant decisions | everything else |
| `dm_core` | exactness, counterexamples, proofs speed | natural-language triage |

The architecture survives any checkpoint you drop in: the engine computes,
the model decides, the gate escalates, the eval harness keeps everyone honest.