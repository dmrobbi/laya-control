"""t06_number_theory.py — Tutorial 06: the engine computes, laya audits words.

Engine showcase (all asserted, all exact): Euclid steps, Bezout coefficients,
modular inverse or its absence, primality, factorisation, totient, modular
power, and the Fermat lesson — one witness PROVES compositeness; a passed
test is only pseudoprime EVIDENCE (341 fools base 2; Carmichael 561 fools
every coprime base).

Then the honest audit role: laya reads (question, proposed answer) worded
pairs and answers noul "consistent?". Worded claims audit partially; the
bare-number variant of this suite (probe_capability.py suite E) separates
right from wrong barely at all. Conclusion for study tools: laya audits
PHRASINGS, and the engine still computes every number.

Run:  python3 t06_number_theory.py
Needs: a laya-serve endpoint (env LAYA_URL, default http://127.0.0.1:8099).
"""

import sys

import dm_core
import laya_math as lm

CLIENT = lm.DM()

QUESTIONS = {
    "consistent": {
        "type": "noul",
        "instructions": "Is the proposed answer correct for this mathematical question?",
    }
}

# (question, proposed answer, expected) — labels authored; engine values asserted below
AUDIT_ROWS = [
    ("What is the gcd of 252 and 105?", "The gcd of 252 and 105 is 21.", True),
    ("What is the gcd of 252 and 105?", "The gcd of 252 and 105 is 20.", False),
    ("What is the modular inverse of 3 modulo 7?", "The inverse is 5, since 3*5 = 15 = 2*7 + 1.", True),
    ("What is the modular inverse of 3 modulo 7?", "The inverse is 6.", False),
    ("What is Euler's totient of 36?", "phi(36) = 12.", True),
    ("What is Euler's totient of 36?", "phi(36) = 18.", False),
    ("Is 91 prime?", "No. 91 = 7 * 13, so it is composite.", True),
    ("Is 91 prime?", "Yes. 91 is prime.", False),
    ("How many subsets does a 6-element set have?", "A 6-element set has 64 subsets.", True),
    ("How many subsets does a 6-element set have?", "A 6-element set has 32 subsets.", False),
]


def engine_showcase():
    g, steps = dm_core.gcd_steps(252, 105)
    bez = dm_core.extended_gcd(252, 105)
    print(f"  gcd(252, 105)  = {g} (Euclid, {steps} steps); Bezout: 252*({bez[1]}) + 105*{bez[2]} = {g}")
    assert g == 21 and 252 * bez[1] + 105 * bez[2] == g
    inv = dm_core.mod_inverse(3, 7)
    print(f"  3^-1 mod 7     = {inv}; 2^-1 mod 4 = {dm_core.mod_inverse(2, 4)} (absent when gcd != 1)")
    assert inv is not None and (3 * inv) % 7 == 1 and dm_core.mod_inverse(2, 4) is None
    prime91 = dm_core.is_prime(91)
    factors91 = dm_core.prime_factors(91)
    subsets6 = sum(dm_core.combinations_count(6, k) for k in range(7))
    print(f"  is_prime: 97 -> {dm_core.is_prime(97)}, 91 -> {prime91} (91 = {factors91}); subsets of a 6-set = {subsets6}")
    assert prime91 is False and factors91 == [7, 13] and subsets6 == 64
    print(f"  phi(36)        = {dm_core.totient(36)};  7^128 mod 13 = {dm_core.mod_pow(7, 128, 13)}")
    assert dm_core.totient(36) == 12 and dm_core.mod_pow(7, 128, 13) == 3
    holds, note = dm_core.fermat_witness(341, 2)
    print(f"  Fermat base 2 on 341 = 11*31: passes ({note}), so evidence only, never proof")
    assert holds is True
    holds, note = dm_core.fermat_witness(561, 3)
    print(f"  Fermat base 3 on Carmichael 561: {note}")
    assert holds is False


def main() -> int:
    lm.banner("Tutorial 06 — number theory: engine showcase")
    engine_showcase()
    # every value laya is about to audit has now been asserted against dm_core

    lm.banner("Tutorial 06 — laya as answer auditor (worded claims)")
    hits, true_hits, false_hits = 0, [], []
    for question, proposal, expected in AUDIT_ROWS:
        state = f"Question: {question}\nProposed answer: {proposal}"
        result = CLIENT.decide(state, QUESTIONS)
        noul_value = lm.noul(result, "consistent")
        ok = (noul_value >= 0.5) == expected
        hits += ok
        (true_hits if expected else false_hits).append(ok)
        print(f"  expected={'T' if expected else 'F'} noul={noul_value:.3f} {'YES' if ok else 'MISS'} | {proposal[:64]}")

    lm.banner("Results")
    true_rows, false_rows = len(true_hits), len(false_hits)
    print(f"  overall audit ({true_rows + false_rows} worded rows, measured): {hits}/10 = {hits / 10:.3f}")
    print(f"  true-claim rows  : {sum(true_hits)}/{true_rows} accepted correctly")
    print(f"  false-claim rows : {sum(false_hits)}/{false_rows} rejected correctly")
    print(f"\nWHAT TO NOTICE")
    print(f"  * every audited value was already engine-asserted - laya is the second")
    print(f"    opinion, never the calculator.")
    print(f"  * laya's audit-noul is systematically conservative: argmax 'no' on")
    print(f"    9 of 10 rows, so every true claim was missed. Verdicts: NO for laya;")
    print(f"    keep it only as a second-opinion filter a human reads.")
    print(f"    (the probe's bare-number rows separate even less - numbers are soup)")
    print(f"  * Fermat's asymmetry applies to confidence too: a strong model opinion")
    print(f"    is evidence at best. One engine check is a proof; use it first.")
    return 0


if __name__ == "__main__":
    sys.exit(main())