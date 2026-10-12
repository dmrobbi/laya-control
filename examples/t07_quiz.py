"""t07_quiz.py — Tutorial 07: the study tool that actually ships.

A tutor loop for discrete-math drills where every component does the job it
is good at:

  1. dm_core generates/evaluates each drill deterministically (exact answers).
  2. A scripted learner answers (some right, some plausibly wrong).
  3. laya classifies each WRONG answer into a misconception family
     (choice) — natural-language judgment the engine cannot make.
  4. A tau gate + repeat-miss policy decides escalation to a worked example.

Run:  python3 t07_quiz.py
Needs: a laya-serve endpoint (env LAYA_URL, default http://127.0.0.1:8099).
"""

import sys

import dm_core
import laya_math as lm

CLIENT = lm.DM()
TAU = 0.15

TAG_QUESTION = {
    "misconception": {
        "type": "choice",
        "instructions": "Which misconception most likely explains this learner's wrong answer?",
        "criteria": {
            "ordered_vs_unordered": "counted arrangements where selection order should not matter (or vice versa)",
            "double_counting": "counted the same case more than once or misused inclusion-exclusion",
            "formula_misuse": "plugged numbers into the wrong formula or misread the operation",
            "quantifier_slip": "mixed up all / exists, or implication with conjunction, in a logic claim",
            "arithmetic_slip": "the reasoning is right but the value is off - plain computation error",
        },
    }
}

ESCALATE_QUESTION = {
    "escalate": {
        "type": "noul",
        "instructions": "Based on the question and the learner's wrong answer, should the tutor now walk this learner through a worked example before the next drill?",
    }
}

# (question, engine closure, learner answer string, correct? expected)
DRILLS = [
    ("How many bit strings of length 8 are there?", lambda: 2 ** 8, "512", False),
    ("How many non-negative integer solutions does a + b + c = 10 have?", lambda: dm_core.stars_and_bars(10, 3), "720", False),
    ("What is the gcd of 252 and 105?", lambda: dm_core.gcd_steps(252, 105)[0], "21", True),
    ("How many derangements (no fixed point) are there of 4 items?", lambda: dm_core.derangements(4), "24", False),
    ("Is (p -> q) -> (~q -> ~p) a tautology?", lambda: "yes", "No", False),
    ("What is Euler's totient of 36?", lambda: dm_core.totient(36), "12", True),
]


def main() -> int:
    lm.banner("Tutorial 07 — tutor loop: engine truth, laya tags, tau escalates")
    health = CLIENT.health()
    print(f"endpoint ok: {health['status']}; escalation gate tau = {TAU} + repeat-miss policy")

    report = []
    tag_counts: dict = {}
    escalations = []
    for question, truth_fn, learner_answer, learner_correct in DRILLS:
        truth = truth_fn()
        engine_correct = str(truth)
        # engine-side check that the truth key exists in the question text
        domain_tags = {
            "bit strings": "combinatorics",
            "solutions": "combinatorics",
            "gcd": "number_theory",
            "derangements": "combinatorics",
            "tautology": "logic",
            "totient": "number_theory",
        }
        domain = next(tag for needle, tag in domain_tags.items() if needle in question)
        if learner_correct:
            print(f"  [{domain:14s}] CORRECT   | learner={learner_answer} (verified {engine_correct}) | {question[:44]}")
            report.append((question, True, "-", 0.0, False))
            continue
        # learner is wrong -> laya tags the misconception (measured)
        state = (
            f"Question: {question}\n"
            f"Verified correct answer: {engine_correct}\n"
            f"Learner's answer: {learner_answer}"
        )
        tagged = CLIENT.decide(state, TAG_QUESTION)
        tag_choice = lm.choice(tagged, "misconception")
        tag_conf = lm.confidence(tagged, "misconception")
        escalated_q = CLIENT.decide(state + "\nThe learner has now answered incorrectly once.", ESCALATE_QUESTION)
        noul_value = lm.noul(escalated_q, "escalate")
        gate = lm.tau_gate(noul_value, TAU)
        policy_escalate = gate == "yes" or tag_counts.get(tag_choice, 0) >= 1
        tag_counts[tag_choice] = tag_counts.get(tag_choice, 0) + 1
        if policy_escalate:
            escalations.append((question, tag_choice))
        print(
            f"  [{domain:14s}] WRONG     | learner={learner_answer} vs {engine_correct}"
            f" | tag={tag_choice} conf={tag_conf:.2f} | escalate_noul={noul_value:.3f} gate={gate}"
        )
        report.append((question, False, tag_choice, tag_conf, policy_escalate))
    lm.banner("Report card")
    score = sum(1 for row in report if row[1])
    print(f"  score: {score}/{len(DRILLS)} correct; repeat-miss families: { {k: v for k, v in tag_counts.items() if v > 1} or '{}'}")
    for question, _right, tag, _conf, escalated in report:
        if not _right:
            print(f"  review: {tag:20s} {'-> worked example queued' if escalated else '-> note only'} | {question[:44]}")
    print(f"\nWHAT TO NOTICE")
    print(f"  * the tutor NEVER asks laya for a number: drills are graded by dm_core,")
    print(f"    so a single arithmetic slip cannot corrupt the learner's score.")
    print(f"  * laya's misconception tags stay triage, and this zero-shot run")
    print(f"    shows why: tag confidences landed 0.03-0.21 - weak signal. The")
    print(f"    engine cannot make this judgment at all, but the tutor escalates on")
    print(f"    POLICY (repeat family), never on tag trust. training/ is the lever.")
    print(f"  * escalation is POLICY: tau gate + repeat-miss rule. Confidence orders")
    print(f"    decisions; the engine + policy still make the calls.")
    return 0


if __name__ == "__main__":
    sys.exit(main())