"""t02_logic_gate.py — Tutorial 02: Laya as the verdict gate over formulas.

Pattern taught here: the deterministic engine evaluates the formula exactly;
laya is asked the SAME question (noul: "does this assignment satisfy it?") and
acts as a cheap second opinion with calibrated confidence. A tau gate splits
its answer into accept / reject / ESCALATE, and escalation always lands on the
engine.

The honest lesson this tutorial measures: the gate catches INDECISION —
it cannot catch confident error. laya's wrong-but-confident rows still leak;
they are printed so you can see exactly what a gated system accepts.

Run:  python3 t02_logic_gate.py
Needs: a laya-serve endpoint (env LAYA_URL, default http://127.0.0.1:8099).
"""

import sys

import dm_core
import laya_math as lm

CLIENT = lm.DM()
TAU = 0.20

FORMULAS = [
    "p & q",
    "p -> q",
    "~p | q",
    "(p | q) & ~r",
    "p & ~p",
    "(p -> q) & (q -> p)",
    "~(p & q)",
    "(p -> q) -> (~q -> ~p)",
]

ASSIGNMENTS = [
    {"p": True, "q": False, "r": True},
    {"p": False, "q": True, "r": False},
]

QUESTIONS = {
    "satisfies": {
        "type": "noul",
        "instructions": "Does the assignment satisfy the formula?",
    }
}


def assignment_label(restrict) -> str:
    return ", ".join(f"{name}={'T' if value else 'F'}" for name, value in sorted(restrict.items()))


def main() -> int:
    lm.banner("Tutorial 02 — verdict gating with a tau threshold")
    health = CLIENT.health()
    print(f"endpoint ok: {health['status']}; gate policy: escalate when |noul - 0.5| < {TAU}")

    direct_hits, escalations = 0, 0
    laya_misses = []  # wrong AND accepted by the gate (not escalated)
    total = 0
    for text in FORMULAS:
        ast = dm_core.parse_formula(text)
        variables = dm_core.formula_variables(ast)
        for assignment in ASSIGNMENTS:
            if any(name not in assignment for name in variables):
                continue
            restrict = {name: assignment[name] for name in variables}
            expected = dm_core.eval_formula(ast, restrict)  # engine = authority
            state = (
                f"Boolean formula: {text}\nAssignment: "
                + ", ".join(f"{n} = {'True' if v else 'False'}" for n, v in sorted(restrict.items()))
            )
            result = CLIENT.decide(state, QUESTIONS)
            noul_value = lm.noul(result, "satisfies")
            gate = lm.tau_gate(noul_value, TAU)
            total += 1
            if gate == "escalate":
                escalations += 1
                verdict = "engine (escalated)"
            else:
                laya_yes = noul_value >= 0.5
                verdict = "yes" if laya_yes else "no"
                if laya_yes == expected:
                    direct_hits += 1
                else:
                    laya_misses.append((text, assignment_label(restrict), noul_value))
            print(
                f"  {text:28s} @ {assignment_label(restrict):18s}"
                f" | engine={'T' if expected else 'F'} laya_noul={noul_value:.3f} gate={gate:8s} verdict={verdict}"
            )

    lm.banner("Results")
    system_correct = direct_hits + escalations  # escalations are engine-resolved, exact
    print(f"  laya-direct correct : {direct_hits}/{total}")
    print(f"  escalated -> engine : {escalations}/{total} (engine resolves exactly)")
    print(f"  laya wrong+accepted : {len(laya_misses)} of {total} -> {laya_misses if laya_misses else 'none this run'}")
    print(f"  SYSTEM accuracy     : {system_correct}/{total} = {system_correct / total:.3f}  <- laya right OR humble; engine otherwise")
    print(f"\nWHAT TO NOTICE")
    print(f"  * laya reads formula/assignment text: direct agreement measured above")
    print(f"    ({direct_hits}/{total}) - useful triage, never authority.")
    print(f"  * the tau gate catches INDECISION ('I'm not sure' -> engine), which is")
    print(f"    why escalations are always right. It CANNOT catch confident error:")
    print(f"    the wrong+accepted rows above are laya's misses that leaked through.")
    print(f"  * production policy therefore comes from a measured eval baseline")
    print(f"    per question type (docs/laya-baseline.md) - not from hope.")
    return 0


if __name__ == "__main__":
    sys.exit(main())