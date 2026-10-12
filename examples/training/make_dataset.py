"""training/make_dataset.py — deterministic dataset generator for the
discrete-math decision workspace.

Emits JSONL rows in the exact format laya-evals and laya.finetune consume
(upstream format; see training/FINETUNE.md):

    {
      "state": <text>,
      "questions": {<qid>: <question dict exactly as Router.predict accepts>},
      "expected":  {<qid>: <label | number | true/false>},
      "tags": ["domain:...", "difficulty:..."],
      "language": "en"
    }

Three row families, all ground-truthed by dm_core (deterministic, exact):

  verify   — a question plus a proposed answer; noul question "consistent".
             Correct and corrupted proposals in a fixed ratio.
  classify — a propositional formula; choice over tautology/contradiction/
             contingent, ground truth from the truth table.
  tag      — a drill with a plausible wrong learner answer; choice over the
             misconception family (the tutor's triage labels).

Deterministic: random.Random(seed) drives every choice; same seed, same file.
Self-validating: a schema check runs before the files are written.

Usage:
    python3 training/make_dataset.py --out-dir TRAINING_DATA --verify 4000 \
        --classify 2000 --tag 2000 --seed 7
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import dm_core  # noqa: E402

VERIFY_QID = "consistent"
CLASSIFY_QID = "formula_class"
TAG_QID = "misconception"

VERIFY_QUESTION = {
    "type": "noul",
    "instructions": "Is the proposed answer correct for this mathematical question?",
}

CLASSIFY_QUESTION = {
    "type": "choice",
    "instructions": "Classify this propositional formula.",
    "criteria": {
        "tautology": "true under every assignment",
        "contradiction": "false under every assignment",
        "contingent": "true somewhere and false somewhere",
    },
}

TAG_QUESTION = {
    "type": "choice",
    "instructions": "Which misconception most likely explains this learner's wrong answer?",
    "criteria": {
        "ordered_vs_unordered": "counted arrangements where selection order should not matter (or vice versa)",
        "double_counting": "counted the same case more than once or misused inclusion-exclusion",
        "formula_misuse": "plugged numbers into the wrong formula or misread the operation",
        "quantifier_slip": "mixed up all / exists, or implication with conjunction",
        "arithmetic_slip": "reasoning right, value off - plain computation error",
    },
}


# ---- small template pools (deterministic variety) -------------------------

# ---- builders -------------------------------------------------------------
# each builder: rng -> (question, canonical truth string, corrupter)

VERIFY_BUILDERS = [
    lambda rng: gcd_row(rng),
    lambda rng: prime_row(rng),
    lambda rng: modpow_row(rng),
    lambda rng: subsets_row(rng),
    lambda rng: derange_row(rng),
    lambda rng: totient_row(rng),
    lambda rng: choose_row(rng),
    lambda rng: bars_row(rng),
]


def gcd_row(rng):
    a, b = rng.randint(6, 900), rng.randint(6, 900)
    value, _steps = dm_core.gcd_steps(a, b)
    q = f"Compute gcd({a}, {b})."
    return q, str(value), lambda rng: str(value + rng.choice([-2, -1, 1, 2]))


def prime_row(rng):
    n = rng.randint(10, 800)
    value = "yes" if dm_core.is_prime(n) else "no"
    q = f"Is {n} prime? Answer yes or no."
    return q, value, lambda rng: "no" if value == "yes" else "yes"


def modpow_row(rng):
    a, m = rng.randint(2, 40), rng.randint(7, 61)
    e = rng.randint(2, 40)
    value = dm_core.mod_pow(a, e, m)
    q = f"Compute {a}^{e} mod {m}."
    return q, str(value), lambda rng: str(dm_core.mod_pow(a, e, m + rng.randint(1, 5)))


def subsets_row(rng):
    k = rng.randint(3, 12)
    value = 2 ** k
    q = f"How many subsets does a set with {k} elements have?"
    return q, str(value), lambda rng: str(2 ** max(0, k + rng.choice([-1, 1, 2])))


def derange_row(rng):
    k = rng.randint(4, 10)
    value = dm_core.derangements(k)
    q = f"How many derangements of {k} items are there?"
    return q, str(value), lambda rng: str(k if rng.random() < 0.5 else max(0, value + rng.choice([-1, 1, 2])))


def totient_row(rng):
    n = rng.randint(5, 500)
    value = dm_core.totient(n)
    q = f"What is Euler's totient of {n}?"
    return q, str(value), lambda rng: str(n // 2 if rng.random() < 0.4 else max(0, value + rng.choice([-1, 1, 3])))


def choose_row(rng):
    n, k = rng.randint(4, 40), rng.randint(1, 8)
    if k > n:
        n, k = n + k, 5
    value = dm_core.combinations_count(n, k)
    q = f"How many ways are there to choose {k} items from {n} items (order irrelevant)?"
    return q, str(value), lambda rng: str(dm_core.permutations_count(n, k))


def bars_row(rng):
    n = rng.randint(5, 30)
    value = dm_core.stars_and_bars(n, 3)
    q = f"How many non-negative integer solutions does x1 + x2 + x3 = {n} have?"
    return q, str(value), lambda rng: str(value + value // rng.choice([2, 3]) or value + 1)


FORMULA_SPECS = [
    ("p & q", "contingent"),
    ("p | q", "contingent"),
    ("p -> q", "contingent"),
    ("p | ~p", "tautology"),
    ("p & ~p", "contradiction"),
    ("(p -> q) -> (~q -> ~p)", "tautology"),
    ("~(p & q)", "contingent"),
    ("(p -> q) & (q -> p)", "contingent"),
    ("(p & q) -> p", "tautology"),
    ("(p | q) & (~p | ~q)", "contingent"),
    ("(p -> q) & (~p -> q)", "contingent"),
    ("(p -> q) & p -> q", "tautology"),
]

WRONG_DRILLS = [
    # (question, verified answer, wrong answers + their intended families)
    ("How many ways are there to choose a committee of 3 from 10 people?", 120,
     {"720": "ordered_vs_unordered", "30": "formula_misuse", "9880": "double_counting"}),
    ("How many bit strings of length 8 are there?", 256,
     {"512": "double_counting", "64": "formula_misuse", "128": "formula_misuse"}),
    ("How many non-negative integer solutions does a + b + c = 10 have?", 66,
     {"720": "ordered_vs_unordered", "220": "formula_misuse", "120": "double_counting"}),
    ("How many derangements (no fixed point) are there of 4 items?", 9,
     {"24": "formula_misuse", "12": "double_counting", "8": "arithmetic_slip"}),
    ("Is (p -> q) -> (~q -> ~p) a tautology?", "yes",
     {"no": "quantifier_slip", "only sometimes": "quantifier_slip", "true only when p is false": "formula_misuse"}),
    ("What is Euler's totient of 36?", 12,
     {"18": "formula_misuse", "24": "double_counting", "6": "arithmetic_slip"}),
    ("How many ways can 5 distinct books be arranged on a shelf?", 120,
     {"25": "formula_misuse", "60": "double_counting", "10": "arithmetic_slip"}),
]


def build_verify(count: int, rng: random.Random):
    rows = []
    for _ in range(count):
        question, truth, corrupter = VERIFY_BUILDERS[rng.randrange(len(VERIFY_BUILDERS))](rng)
        correct_first = rng.random() < 0.5
        state = f"Question: {question}\nProposed answer: {truth}" if correct_first else \
            f"Question: {question}\nProposed answer: {corrupter(rng)}"
        expected = True if correct_first else False
        rows.append({
            "state": state,
            "questions": {VERIFY_QID: dict(VERIFY_QUESTION)},
            "expected": {VERIFY_QID: expected},
            "tags": ["family:verify", "truth:" + ("true" if expected else "false")],
            "language": "en",
        })
    return rows


def build_classify(count: int, rng: random.Random):
    rows = []
    for _ in range(count):
        text, expected = FORMULA_SPECS[rng.randrange(len(FORMULA_SPECS))]
        # engine re-derives the class every time: it must agree with the spec
        derived = dm_core.formula_classify(text).split(" ")[0]
        if derived != expected:
            raise ValueError(f"spec/engine disagreement for {text!r}: {expected} != {derived}")
        rows.append({
            "state": f"Propositional formula: {text}",
            "questions": {CLASSIFY_QID: dict(CLASSIFY_QUESTION)},
            "expected": {CLASSIFY_QID: expected},
            "tags": ["family:classify", "truth:" + expected],
            "language": "en",
        })
    return rows


def build_tag(count: int, rng: random.Random):
    rows = []
    for _ in range(count):
        question, truth, wrongs = WRONG_DRILLS[rng.randrange(len(WRONG_DRILLS))]
        wrong = rng.choice(list(wrongs))
        family = wrongs[wrong]
        state = (
            f"Question: {question}\n"
            f"Verified correct answer: {truth}\n"
            f"Learner's answer: {wrong}"
        )
        rows.append({
            "state": state,
            "questions": {TAG_QID: dict(TAG_QUESTION)},
            "expected": {TAG_QID: family},
            "tags": ["family:tag", "truth:" + family],
            "language": "en",
        })
    return rows


def schema_check(rows) -> None:
    for row in rows:
        if not isinstance(row.get("state"), str) or not row["state"]:
            raise ValueError(f"row state must be non-empty text: {row!r}")
        questions, expected = row["questions"], row["expected"]
        if set(expected) != set(questions):
            raise ValueError(f"expected keys must match question ids: {row!r}")
        if row.get("tags") and not all(isinstance(t, str) for t in row["tags"]):
            raise ValueError("tags must be strings")
        for qid, question in questions.items():
            if question["type"] == "choice" and expected[qid] not in question["criteria"]:
                raise ValueError(f"choice label not in criteria: {row!r}")
            if question["type"] == "noul" and not isinstance(expected[qid], bool):
                raise ValueError(f"noul expectation must be true/false: {row!r}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", default="training_data")
    parser.add_argument("--verify", type=int, default=4000)
    parser.add_argument("--classify", type=int, default=2000)
    parser.add_argument("--tag", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    rng = random.Random(args.seed)
    os.makedirs(args.out_dir, exist_ok=True)

    suites = {
        "dm_verify.jsonl": build_verify(args.verify, rng),
        "dm_classify.jsonl": build_classify(args.classify, rng),
        "dm_tag.jsonl": build_tag(args.tag, rng),
    }
    for name, rows in suites.items():
        schema_check(rows)
        path = os.path.join(args.out_dir, name)
        with open(path, "w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row) + "\n")
        truth_counts: dict = {}
        for row in rows:
            for tag in row["tags"]:
                if tag.startswith("truth:"):
                    truth_counts[tag] = truth_counts.get(tag, 0) + 1
        print(f"{name}: {len(rows)} rows -> {path}; {truth_counts}")
    print("deterministic: rerun with the same --seed to reproduce byte-identical files")
    return 0


if __name__ == "__main__":
    sys.exit(main())