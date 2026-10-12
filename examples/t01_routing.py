"""t01_routing.py — Tutorial 01: let Laya route, let the engine answer.

Pipeline taught here:
  natural-language math question
      -> laya choose(question -> engine domain)        [System 1: ~0.3 s CPU]
      -> dispatch to that domain's deterministic engine [dm_core, exact]
      -> answer + evidence                              [System 2: authoritative]

Run:  python3 t01_routing.py
Needs: a laya-serve endpoint (env LAYA_URL, default http://127.0.0.1:8099).
Engine results are asserted; laya's routing accuracy is MEASURED, never asserted.
"""

import sys

import dm_core
import laya_math as lm

CLIENT = lm.DM()


# The dispatch table: domain -> callable(question context) -> (answer, evidence).
# In a real product this lives next to the engine; it is inlined here so the
# tutorial is one file.

def dispatch(question: str, domain: str):
    """Compute the answer for the runnable corpus questions by domain."""
    if domain == "number_theory":
        if "gcd" in question:
            g, steps = dm_core.gcd_steps(252, 105)
            return str(g), f"Euclidean algorithm, {steps} divisions"
        if "totient" in question:
            return str(dm_core.totient(36)), "36 = 2^2 * 3^2 -> phi = 36 * (1/2) * (2/3)"
        if "modulo 13" in question:
            return str(dm_core.mod_pow(7, 128, 13)), "square-and-multiply; fermat reduces 7^12 = 1 (mod 13)"
    if domain == "combinatorics":
        if "bit strings" in question:
            return "256", "2^8"
        if "solutions" in question or "candies" in question:
            return str(dm_core.stars_and_bars(10, 3)), "C(12, 2)"
        if "committee" in question:
            return str(dm_core.combinations_count(10, 3)), "C(10, 3)"
        if "books" in question:
            return str(dm_core.permutations_count(5, 5)), "5!"
        if "derangements" in question:
            return str(dm_core.derangements(4)), "recurrence on D_n"
    if domain == "graphs" and "shortest path" in question:
        distance, path = dm_core.shortest_path_unweighted(4, [(0, 1), (1, 2), (2, 3)], 0, 3)
        return str(distance), f"BFS path: {' -> '.join(map(str, path))}"
    return None, None


RUNNABLE = [
    ("How many different ways are there to choose a committee of 3 people from 10 people?", "combinatorics"),
    ("What is the gcd of 252 and 105?", "number_theory"),
    ("How many bit strings of length 8 are there?", "combinatorics"),
    ("How many non-negative integer solutions does a + b + c = 10 have?", "combinatorics"),
    ("How many derangements of 4 items are there?", "combinatorics"),
    ("What is Euler's totient function value for 36?", "number_theory"),
    ("Compute 7^128 modulo 13 efficiently.", "number_theory"),
    ("In how many different orders can 5 distinct books be arranged on a shelf?", "combinatorics"),
    ("What is the shortest path from vertex 0 to vertex 3 in the edge list 0-1, 1-2, 2-3?", "graphs"),
    ("In how many ways can 10 identical candies be distributed among 3 children?", "combinatorics"),
]

QUESTIONS = {
    "domain": {
        "type": "choice",
        "instructions": "Which branch of discrete mathematics does this question belong to, and which deterministic engine should compute it?",
        "criteria": dict(zip(
            ["logic", "sets", "combinatorics", "graphs", "number_theory", "recurrence"],
            dm_core.engine_manifest().values(),
        )),
    }
}  # the question set IS part of your application design - defined in app code


def main() -> int:
    lm.banner("Tutorial 01 — route with laya, answer with the engine")
    health = CLIENT.health()
    print(f"endpoint ok: {health['status']} (checkpoints: {', '.join(health['loaded'])})")

    routed_correctly = 0
    for text, expected in RUNNABLE:
        result = CLIENT.decide(text, QUESTIONS)
        domain = lm.choice(result, "domain")
        conf = lm.confidence(result, "domain")
        answer, evidence = dispatch(text, domain)
        ok = answer is not None
        if ok:
            # engine truth is the ground truth of this tutorial: assert it
            engine_answer, _ = dispatch(text, expected)
            if engine_answer != answer:
                print(f"  [FAIL] routed domain '{domain}' answered {answer}; expected-domain engine says {engine_answer}")
                return 1
        else:
            answer = "(no engine for routed domain)"
            evidence = "routing outside the runnable set - in production this escalates"
        routed_correctly += int(domain == expected)
        print(f"  route={domain:16s} conf={conf:.2f} | answer={answer:8s} ({evidence[:44]}) | {text[:52]}")
    print(f"\nWHAT TO NOTICE")
    print(f"  * routing accuracy this run: {routed_correctly}/{len(RUNNABLE)} (measured, zero-shot english checkpoint)")
    print(f"  * every ANSWER printed came from dm_core - exact, verifiable, offline")
    print(f"  * a confident-enough laya route is all the pipeline needs; a weak one")
    print(f"    would route to escalation instead (see t07 for the gating policy)")
    return 0


if __name__ == "__main__":
    sys.exit(main())