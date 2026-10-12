"""t04_combinatorics_grade.py — Tutorial 04: what laya does NOT do for math.

The measured lesson: ask laya to PICK A NUMBER across 4 numeric options and it
lands at chance (0.25) with honest-but-low confidence. The same questions are
trivial for the deterministic engine. So the production pattern is
COMPUTE FIRST, ASK LATER — laya grades and classifies; it never decides value.

Run:  python3 t04_combinatorics_grade.py
Needs: a laya-serve endpoint (env LAYA_URL, default http://127.0.0.1:8099).
"""

import sys

import dm_core
import laya_math as lm

CLIENT = lm.DM()

# (question, distractor-free options, engine closure for the true value)
ITEMS = [
    ("How many ways are there to choose a committee of 3 people from 10 people?",
     ["120", "720", "9880", "30"], lambda: dm_core.combinations_count(10, 3)),
    ("How many bit strings of length 8 are there?",
     ["64", "128", "256", "512"], lambda: 2 ** 8),
    ("How many ways can 3 candies be picked from 40 distinct candies (order irrelevant)?",
     ["9880", "69000", "59040", "120"], lambda: dm_core.combinations_count(40, 3)),
    ("How many non-negative integer solutions does a + b + c = 10 have?",
     ["66", "720", "120", "220"], lambda: dm_core.stars_and_bars(10, 3)),
    ("How many derangements (no fixed point) are there of 4 items?",
     ["9", "24", "8", "12"], lambda: dm_core.derangements(4)),
    ("In how many orders can 5 distinct books be arranged on a shelf?",
     ["60", "120", "24", "25"], lambda: dm_core.permutations_count(5, 5)),
    ("How many subsets does a set with 6 elements have (including the empty set)?",
     ["32", "36", "64", "12"], lambda: 2 ** 6),
    ("How many binary strings of length 4 have no two adjacent 1s?",
     ["4", "6", "8", "16"], lambda: sum(1 for s in range(16) if not any((s >> k) & 1 and (s >> (k + 1)) & 1 for k in range(3)))),
    ("Four people stand in a row for a photo. How many arrangements are there?",
     ["16", "24", "12", "8"], lambda: dm_core.permutations_count(4, 4)),
    ("How many 5-card hands can be drawn from a 52-card deck?",
     ["2598960", "311875200", "25989600", "2639760"], lambda: dm_core.combinations_count(52, 5)),
    ("How many ways can 8 items be chosen from 10 items?",
     ["90", "45", "40", "80"], lambda: dm_core.combinations_count(10, 8)),
    ("With |A|=15, |B|=10, |C|=12, |A and B|=5, |A and C|=4, |B and C|=3, |A and B and C|=2: how large is A union B union C?",
     ["22", "25", "27", "37"], lambda: dm_core.inclusion_exclusion_3(15, 10, 12, 5, 4, 3, 2)),
]


def quiz_question(options):
    return {
        "answer": {
            "type": "choice",
            "instructions": "Which value is correct?",
            "criteria": {opt: f"the value {opt}" for opt in options},
        }
    }


def main() -> int:
    lm.banner("Tutorial 04 — numeric answers: laya vs the engine")
    hits, low_conf = 0, 0
    for index, (text, options, engine_fn) in enumerate(ITEMS):
        truth = str(engine_fn())  # engine = authority (deterministic, exact)
        options_assert = options.copy()
        if truth not in options_assert:
            print(f"  [FAIL] item {index}: engine truth {truth} missing from options")
            return 1
        result = CLIENT.decide(text, quiz_question(options))
        chosen = lm.choice(result, "answer")
        conf = lm.confidence(result, "answer")
        low_conf += conf < 0.30
        hit = chosen == truth
        hits += hit
        print(f"  truth={truth:>8s} laya={chosen:>8s} conf={conf:.2f} {'YES' if hit else 'MISS'} | {text[:54]}")
    lm.banner("Results")
    print(f"  laya pick-a-number accuracy : {hits}/{len(ITEMS)} = {hits / len(ITEMS):.3f} (chance = 0.250)")
    print(f"  laya rows at low confidence : {low_conf}/{len(ITEMS)} (it half-knows)")
    print(f"  engine accuracy             : {len(ITEMS)}/{len(ITEMS)} = 1.000, by construction")
    print(f"\nWHAT TO NOTICE")
    print(f"  * numeric option strings are meaningless token soup to the encoder:")
    print(f"    4-option numeric QA = coin flip, NOT a reasoning failure to fix with prompts.")
    print(f"  * the fix is architectural, not prompt-engineering: compute first with the")
    print(f"    engine, THEN use laya to grade the learner's answer or tag the mistake.")
    print(f"  * laya's low confidence here is honest - a healthy signal for the gate.")
    return 0


if __name__ == "__main__":
    sys.exit(main())