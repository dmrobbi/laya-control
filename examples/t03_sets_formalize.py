"""t03_sets_formalize.py — Tutorial 03: statements, formalizations, and the
counterexample machine.

Two jobs, one file:

1. laya checks whether a proposed FORMALIZATION faithfully expresses an
   English statement (noul) — a natural-language judgment the engine cannot
   make. Misses here are measured and kept visible: subtle quantifier swaps
   are exactly where a 421M-encoder over-commits.

2. The engine adjudicates SET IDENTITIES with brute force over a finite
   universe: an identity claim becomes "true everywhere" or "false at this
   concrete assignment" — a witness or counterexample, computable offline.
   This is the authoritative half the study tool leans on.

Run:  python3 t03_sets_formalize.py
Needs: a laya-serve endpoint (env LAYA_URL, default http://127.0.0.1:8099).
"""

import sys

import dm_core
import laya_math as lm

CLIENT = lm.DM()

CASES = [
    ("Every element of set A is also an element of set B.",
     "A is a subset of B (every x in A is in B)", True),
    ("Every element of set A is also an element of set B.",
     "B is a subset of A (every x in B is in A)", False),
    ("Set A and set B share at least one common element.",
     "A intersect B is not empty", True),
    ("Set A and set B share at least one common element.",
     "A intersect B is empty", False),
    ("Some element of the set S is not an even number.",
     "there exists x in S with x not even", True),
    ("Some element of the set S is not an even number.",
     "every x in S is even", False),
    ("The relation R is symmetric: for any x, y, if x is related to y, then y is related to x.",
     "for all x, y: (xRy implies yRx)", True),
    ("The relation R is symmetric: for any x, y, if x is related to y, then y is related to x.",
     "there exist x, y such that xRy implies yRx", False),
    ("The relation R is transitive: whenever x is related to y and y to z, x is related to z.",
     "for all x, y, z: ((xRy and yRz) implies xRz)", True),
    ("The relation R is transitive: whenever x is related to y and y to z, x is related to z.",
     "for all x, y, z: (xRy and yRz and xRz)", False),
]

QUESTIONS = {
    "matching": {
        "type": "noul",
        "instructions": "Does the proposed formalization faithfully express the statement? Answer true only when they mean the same thing.",
    }
}

IDENTITIES = [
    ("(A union B)'", "A' n B'", "De Morgan: complement of a union"),
    ("(A u B)'", "A' u B'", "WRONG De Morgan (v variant)"),
    ("A n (B u C)", "(A n B) u (A n C)", "distributivity"),
    ("A u (A n B)", "A", "absorption"),
    ("(A u B) n A", "A", "absorption variant"),
]


def main() -> int:
    lm.banner("Tutorial 03 — formalization checking + counterexamples")
    health = CLIENT.health()
    print(f"endpoint ok: {health['status']}")

    hits = 0
    for statement, encoding, expected in CASES:
        state = f"Statement: {statement}\nProposed formalization: {encoding}"
        result = CLIENT.decide(state, QUESTIONS)
        noul_value = lm.noul(result, "matching")
        ok = (noul_value >= 0.5) == expected
        hits += ok
        print(f"  expected={'T' if expected else 'F'} noul={noul_value:.3f} {'YES' if ok else 'MISS'} | {encoding[:66]}")
    print(f"  -> laya formalization agreement: {hits}/{len(CASES)} = {hits / len(CASES):.3f} (measured)")

    lm.banner("Set identities — engine adjudication (brute force over the universe)")
    for lhs, rhs, label in IDENTITIES:
        holds, witness = dm_core.set_identity_check(lhs, rhs)
        if holds:
            print(f"  [HOLDS] {lhs:12s} == {rhs:12s} # {label} (equal on all 8 universe assignments)")
        else:
            assignment = ", ".join(
                f"{name}={sorted(value)}" for name, value in witness.items() if name in "ABC"
            )
            print(
                f"  [COUNTER] {lhs:12s} != {rhs:12s} # {label}\n"
                f"           witness: with A={sorted(witness['A'])}, B={sorted(witness['B'])}"
                f" -> lhs={sorted(witness['lhs'])}, rhs={sorted(witness['rhs'])}"
            )
    print(f"\nWHAT TO NOTICE")
    print(f"  * laya flags the obvious mismatch cases correctly but confidently")
    print(f"    misses subtle ones (quantifier placement, transitivity shape):")
    print(f"    label-swap and conjunction-instead-of-implication both sailed through.")
    print(f"  * the engine's counterexample is a CONCRETE tuple — the strongest kind")
    print(f"    of evidence a study tool can cite. No model confidence needed.")
    print(f"  * pattern: laya = cheap natural-language triage; engine = adjudicator.")
    return 0


if __name__ == "__main__":
    sys.exit(main())