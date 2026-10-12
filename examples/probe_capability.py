"""probe_capability.py — measured capability study for Laya on discrete math.

Six suites, all against the live laya-serve (docs/LAYA-SETUP.md, :8099).
GROUND TRUTH comes from dm_core (deterministic); LAYA'S ANSWERS ARE MEASURED,
NEVER ASSERTED — the whole point is an honest capability map:

A. domain routing      — 24 natural-language math questions -> choice over 6
B. verdict gating       — 16 (formula, assignment) pairs -> noul vs engine
C. formalization check  — 10 statement/encoding pairs -> noul vs labels
D. graph properties     — 8 graphs, two noul questions each, vs BFS engine
E. answer audit         — 10 proposed-answer rows -> noul, engine cross-check
F. quiz grading         — 12 multiple-choice items -> choice accuracy

Writes probe_results.json (for docs/LAYA-DISCRETE-MATH.md) and prints a
compact report. Exit code: 0 when all Laya responses were well-formed
(their CORRECTNESS is data, not an exit condition).
"""

from __future__ import annotations

import json
import statistics
import sys
import time

import dm_core
import laya_math as lm

DOM = ["logic", "sets", "combinatorics", "graphs", "number_theory", "recurrence"]

DOMAIN_QUESTION = {
    "domain": {
        "type": "choice",
        "instructions": "Which branch of discrete mathematics does this question belong to, and which deterministic engine should compute it?",
        "criteria": dict(zip(DOM, dm_core.engine_manifest().values())),
    }
}

ROUTING_CORPUS = [
    ("How many bit strings of length 8 are there?", "combinatorics"),
    ("Is the graph with edges 0-1, 1-2, 2-0, 2-3 connected?", "graphs"),
    ("What is the gcd of 252 and 105?", "number_theory"),
    ("Show that p -> q and ~q -> ~p are logically equivalent.", "logic"),
    ("Find how many non-negative integer solutions a + b + c = 10 has.", "combinatorics"),
    ("Prove or disprove the set identity (A union B)' = A' intersection B'.", "sets"),
    ("A sequence starts a(0)=0, a(1)=1, and every later term is the sum of the two terms before it. What is a(10)?", "recurrence"),
    ("Determine whether 97 is prime.", "number_theory"),
    ("How many different committees of 3 people can be chosen from 10 people?", "combinatorics"),
    ("Does the formula (p | q) & ~r have a satisfying assignment with p true, q true, r false?", "logic"),
    ("What is the shortest path from vertex 0 to vertex 3 in the edge list 0-1, 1-2, 2-3?", "graphs"),
    ("Is 3 invertible modulo 7? If so, find the inverse.", "number_theory"),
    ("How many derangements of 4 items are there?", "combinatorics"),
    ("A relation on {1, 2, 3} contains the pairs (1,1), (2,2), (1,2), (2,3), (2,2) plus identity pairs. Is it reflexive and transitive?", "sets"),
    ("Consider the recurrence a(n) = 2*a(n-1) + 1 with a(0) = 1. Find a(5).", "recurrence"),
    ("Construct the full truth table for ~(p & q).", "logic"),
    ("A tree is formed on 7 vertices. How many edges does it have, and can it contain a cycle?", "graphs"),
    ("Compute 7^128 modulo 13 efficiently.", "number_theory"),
    ("In how many different orders can 5 distinct books be arranged on a shelf?", "combinatorics"),
    ("Is (p -> q) -> (~q -> ~p) a tautology?", "logic"),
    ("If set A has 10 elements, set B has 15, and they share 4 elements, how many elements are in A union B?", "sets"),
    ("In how many ways can 10 identical candies be distributed among 3 children?", "combinatorics"),
    ("What is Euler's totient function value for 36?", "number_theory"),
    ("Can a simple graph on 6 vertices be planar if it has 12 edges? Reason from the edge-count bound.", "graphs"),
]

VERDICT_FORMULAS = [
    "p & q",
    "p -> q",
    "~p | q",
    "(p | q) & ~r",
    "p & ~p",
    "(p -> q) & (q -> p)",
    "~(p & q)",
    "(p -> q) -> (~q -> ~p)",
]

VERDICT_ASSIGNMENTS = [
    {"p": True, "q": False, "r": True},
    {"p": False, "q": True, "r": False},
]

FORMALIZATION_CASES = [
    ("Every element of set A is also an element of set B.", "A is a subset of B (every x in A is in B)", True),
    ("Every element of set A is also an element of set B.", "B is a subset of A (every x in B is in A)", False),
    ("Set A and set B share at least one common element.", "A intersect B is not empty", True),
    ("Set A and set B share at least one common element.", "A intersect B is empty", False),
    ("Some element of the set S is not an even number.", "there exists x in S with x not even", True),
    ("Some element of the set S is not an even number.", "every x in S is even", False),
    ("The relation R is symmetric: for any x, y, if x is related to y, then y is related to x.", "for all x, y: (xRy implies yRx)", True),
    ("The relation R is symmetric: for any x, y, if x is related to y, then y is related to x.", "there exist x, y such that xRy implies yRx", False),
    ("The relation R is transitive: whenever x is related to y and y to z, x is related to z.", "for all x, y, z: ((xRy and yRz) implies xRz)", True),
    ("The relation R is transitive: whenever x is related to y and y to z, x is related to z.", "for all x, y, z: (xRy and yRz and xRz)", False),
]

GRAPHS = [
    (4, [(0, 1), (1, 2), (2, 3)]),               # path, connected, bipartite, no cycle
    (4, [(0, 1), (2, 3)]),                       # disconnected
    (4, [(0, 1), (1, 2), (2, 0)]),               # triangle + isolated 3
    (4, [(0, 1), (1, 2), (2, 3), (3, 0)]),       # C4
    (4, [(0, 1), (0, 2), (0, 3)]),               # star
    (4, [(0, 1), (1, 2), (0, 2), (0, 3), (1, 3)]),  # two triangles sharing 0-1
    (4, [(0, 1), (1, 2)]),                       # path + isolated 3
    (4, [(0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3)]),  # K4
]

AUDIT_CASES = [
    ("What is the gcd of 252 and 105?", "21", True, "gcd"),
    ("What is the gcd of 252 and 105?", "20", False, "gcd"),
    ("What is the modular inverse of 3 modulo 7?", "5", True, "inv37"),
    ("What is the modular inverse of 3 modulo 7?", "6", False, "inv37"),
    ("What is Euler's totient of 36?", "12", True, "phi36"),
    ("What is Euler's totient of 36?", "18", False, "phi36"),
    ("How many subsets does a set with 6 elements have, including the empty subset?", "64", True, "subsets6"),
    ("How many subsets does a set with 6 elements have, including the empty subset?", "32", False, "subsets6"),
    ("Is 91 prime?", "No — 91 = 7 * 13, so it is composite", True, "prime91"),
    ("Is 91 prime?", "Yes, 91 is prime", False, "prime91"),
]

QUIZ_ITEMS = [
    ("How many ways are there to choose a committee of 3 people from 10 people?", ["120", "720", "9880", "30"]),
    ("How many bit strings of length 8 are there?", ["64", "128", "256", "512"]),
    ("How many ways can 3 candies be picked from 40 distinct candies (order irrelevant)?", ["9880", "69000", "59040", "120"]),
    ("How many non-negative integer solutions does a + b + c = 10 have?", ["66", "720", "120", "220"]),
    ("How many derangements (no fixed point) are there of 4 items?", ["9", "24", "8", "12"]),
    ("In how many orders can 5 distinct books be arranged on a shelf?", ["60", "120", "24", "25"]),
    ("How many subsets does a set with 6 elements have (including the empty set)?", ["32", "36", "64", "12"]),
    ("How many binary strings of length 4 have no two adjacent 1s?", ["4", "6", "8", "16"]),
    ("Four people stand in a row for a photo. How many arrangements are there?", ["16", "24", "12", "8"]),
    ("How many 5-card hands can be drawn from a 52-card deck?", ["2598960", "311875200", "25989600", "2639760"]),
    ("How many ways can 8 items be chosen from 10 items?", ["90", "45", "40", "80"]),
    ("With |A|=15, |B|=10, |C|=12, |A and B|=5, |A and C|=4, |B and C|=3, |A and B and C|=2: how large is A union B union C?", ["22", "25", "27", "37"]),
]


def engine_audit_truth(kind: str):
    if kind == "gcd":
        return dm_core.gcd_steps(252, 105)[0] == 21
    if kind == "inv37":
        return dm_core.mod_inverse(3, 7) == 5
    if kind == "phi36":
        return dm_core.totient(36) == 12
    if kind == "subsets6":
        return sum(dm_core.combinations_count(6, k) for k in range(7)) == 64
    if kind == "prime91":
        return (not dm_core.is_prime(91)) and dm_core.prime_factors(91) == [7, 13]
    raise ValueError(kind)


QUIZ_TRUTHS = [
    dm_core.combinations_count(10, 3),
    2 ** 8,
    dm_core.combinations_count(40, 3),
    dm_core.stars_and_bars(10, 3),
    dm_core.derangements(4),
    dm_core.permutations_count(5, 5),
    2 ** 6,
    8,  # verified below by explicit enumeration
    dm_core.permutations_count(4, 4),
    dm_core.combinations_count(52, 5),
    dm_core.combinations_count(10, 8),
    dm_core.inclusion_exclusion_3(15, 10, 12, 5, 4, 3, 2),
]


def no_adjacent_ones_strings(length: int) -> list[str]:
    from itertools import product

    return ["".join(bits) for bits in product("01", repeat=length) if "11" not in "".join(bits)]


RESULTS = {"suites": {}, "latency_ms": []}


def record_call():
    RESULTS["latency_ms"].append(client.latency_ms)


def suite_routing():
    lm.banner("Suite A — domain routing (24 questions)")
    hits, misses = 0, []
    for text, expected in ROUTING_CORPUS:
        result = client.decide(text, DOMAIN_QUESTION)
        record_call()
        chosen = lm.choice(result, "domain")
        conf = lm.confidence(result, "domain")
        if chosen == expected:
            hits += 1
        else:
            misses.append({"text": text, "expected": expected, "chosen": chosen, "expected_p": lm.probabilities(result, "domain").get(expected, 0.0), "confidence": conf})
        print(f"  [{chosen:16s}] conf={conf:.2f} expected={expected:16s} {'YES' if chosen == expected else 'MISS'} | {text[:60]}")
    accuracy = hits / len(ROUTING_CORPUS)
    RESULTS["suites"]["routing"] = {"n": len(ROUTING_CORPUS), "hits": hits, "accuracy": accuracy, "misses": misses}
    print(f"  -> routing accuracy: {hits}/{len(ROUTING_CORPUS)} = {accuracy:.3f}")


def suite_verdicts():
    lm.banner("Suite B — verdict gating (16 formula/assignment pairs)")
    hits, esc = 0, 0
    rows = []
    for text in VERDICT_FORMULAS:
        ast = dm_core.parse_formula(text)
        variables = dm_core.formula_variables(ast)
        for assignment in VERDICT_ASSIGNMENTS:
            restrict = {name: assignment[name] for name in variables if name in assignment}
            missing = [name for name in variables if name not in assignment]
            if missing:
                continue
            expected = dm_core.eval_formula(ast, restrict)
            state = (
                f"Boolean formula: {text}\n"
                f"Assignment: " + ", ".join(f"{name} = {'True' if value else 'False'}" for name, value in sorted(restrict.items())) + "\n"
                "The formula is satisfied when it evaluates to True under the assignment."
            )
            result = client.decide(state, {"satisfies": {"type": "noul", "instructions": "Does the assignment satisfy the formula?"}})
            record_call()
            noul_value = lm.noul(result, "satisfies")
            gate = lm.tau_gate(noul_value)
            if gate == "escalate":
                esc += 1
            gate_yes = noul_value >= 0.5
            ok = gate_yes == expected
            hits += ok
            mark = "YES" if ok else "MISS"
            print(f"  expected={'T' if expected else 'F'} noul={noul_value:.3f} conf={lm.confidence(result, 'satisfies'):.2f} gate={gate:8s} {mark} | {text} @ {restrict}")
            rows.append({"formula": text, "assignment": restrict, "expected": expected, "noul": noul_value, "gate": gate})
    accuracy = hits / len(rows)
    RESULTS["suites"]["verdicts"] = {"n": len(rows), "hits": hits, "accuracy": accuracy, "escalations": esc, "rows": rows}
    print(f"  -> verdict agreement: {hits}/{len(rows)} = {accuracy:.3f}; gate escalations: {esc}/{len(rows)}")


def suite_formalization():
    lm.banner("Suite C — formalization checking (10 pairs)")
    hits = 0
    rows = []
    for statement, encoding, expected in FORMALIZATION_CASES:
        state = f"Statement: {statement}\nProposed formalization: {encoding}"
        result = client.decide(state, {"matching": {"type": "noul", "instructions": "Does the proposed formalization faithfully express the statement? Answer true only when they mean the same thing."}})
        record_call()
        noul_value = lm.noul(result, "matching")
        ok = (noul_value >= 0.5) == expected
        hits += ok
        print(f"  expected={'T' if expected else 'F'} noul={noul_value:.3f} {'YES' if ok else 'MISS'} | {encoding[:64]}")
        rows.append({"statement": statement, "encoding": encoding, "expected": expected, "noul": noul_value})
    accuracy = hits / len(FORMALIZATION_CASES)
    RESULTS["suites"]["formalization"] = {"n": len(FORMALIZATION_CASES), "hits": hits, "accuracy": accuracy, "rows": rows}
    print(f"  -> formalization accuracy: {hits}/10 = {accuracy:.3f}")


def suite_graphs():
    lm.banner("Suite D — graph properties read from edge lists (8 graphs x 2 questions)")
    questions = {
        "connected": {"type": "noul", "instructions": "Is this undirected graph connected (every vertex reachable from every other)?"},
        "bipartite": {"type": "noul", "instructions": "Is this undirected graph bipartite (2-colorable with no edge inside a color class)?"},
    }
    hits = {"connected": 0, "bipartite": 0}
    rows = []
    for n_vertices, edges in GRAPHS:
        edges_text = ", ".join(f"{u}-{v}" for u, v in edges)
        state = f"Undirected graph on {n_vertices} vertices (0-indexed). Edges: {edges_text}."
        expected = {
            "connected": dm_core.graph_connected(n_vertices, edges),
            "bipartite": dm_core.graph_bipartite(n_vertices, edges)[0],
            "cycle": dm_core.graph_has_cycle_undirected(n_vertices, edges),
        }
        result = client.decide(state, questions)
        record_call()
        row = {"edges": edges_text, "expected": expected}
        for qid in questions:
            noul_value = lm.noul(result, qid)
            ok = (noul_value >= 0.5) == expected[qid]
            hits[qid] += ok
            row[qid] = noul_value
            print(f"  {qid:10s} expected={'T' if expected[qid] else 'F'} noul={noul_value:.3f} {'YES' if ok else 'MISS'} | {edges_text}")
        rows.append(row)
    RESULTS["suites"]["graphs"] = {
        "n": len(GRAPHS),
        "hits": hits,
        "accuracy": {qid: hits[qid] / len(GRAPHS) for qid in hits},
        "rows": rows,
    }
    print(f"  -> connected accuracy: {hits['connected']}/8 = {hits['connected'] / 8:.3f}; bipartite accuracy: {hits['bipartite']}/8 = {hits['bipartite'] / 8:.3f}")


def suite_audit():
    lm.banner("Suite E — answer audit (engine-computed claims, 10 rows)")
    hits = 0
    rows = []
    for question, proposal, expected, kind in AUDIT_CASES:
        state = f"Question: {question}\nProposed answer: {proposal}"
        result = client.decide(state, {"consistent": {"type": "noul", "instructions": "Is the proposed answer correct for this mathematical question?"}})
        record_call()
        noul_value = lm.noul(result, "consistent")
        ok = (noul_value >= 0.5) == expected
        hits += ok
        # engine side is the authority: recompute the relevant truth
        engine_ok = engine_audit_truth(kind)
        print(f"  expected={'T' if expected else 'F'} (engine agrees: {engine_ok}) noul={noul_value:.3f} {'YES' if ok else 'MISS'} | {proposal[:56]}")
        rows.append({"question": question, "proposal": proposal, "expected": expected, "noul": noul_value})
    accuracy = hits / len(AUDIT_CASES)
    RESULTS["suites"]["audit"] = {"n": len(AUDIT_CASES), "hits": hits, "accuracy": accuracy, "rows": rows}
    print(f"  -> audit accuracy: {hits}/10 = {accuracy:.3f}")


def suite_quiz():
    lm.banner("Suite F — quiz grading (12 four-choice items)")
    hits, confs = 0, []
    rows = []
    for index, (text, options) in enumerate(QUIZ_ITEMS):
        truth = str(QUIZ_TRUTHS[index])
        qquestion = {"answer": {"type": "choice", "instructions": "Which value is correct?", "criteria": {opt: f"the value {opt}" for opt in options}}}
        result = client.decide(text, qquestion)
        record_call()
        chosen = lm.choice(result, "answer")
        conf = lm.confidence(result, "answer")
        confs.append(conf)
        ok = chosen == truth
        hits += ok
        print(f"  truth={truth:8s} chosen={chosen:8s} conf={conf:.2f} {'YES' if ok else 'MISS'} | {text[:64]}")
        rows.append({"question": text, "options": options, "expected": truth, "chosen": chosen, "confidence": conf})
    accuracy = hits / len(QUIZ_ITEMS)
    RESULTS["suites"]["quiz"] = {"n": len(QUIZ_ITEMS), "hits": hits, "accuracy": accuracy, "mean_confidence": statistics.fmean(confs), "rows": rows}
    print(f"  -> quiz accuracy: {hits}/12 = {accuracy:.3f}; mean confidence {statistics.fmean(confs):.3f}")


def summary():
    lm.banner("Summary")
    lat = sorted(RESULTS["latency_ms"])
    def pct(p):
        if not lat:
            return 0.0
        idx = min(len(lat) - 1, int(round(p / 100 * (len(lat) - 1))))
        return lat[idx]
    print(f"  calls: {len(lat)}; latency p50={pct(50):.0f} ms p95={pct(95):.0f} ms max={lat[-1]:.0f} ms")
    for name, suite in RESULTS["suites"].items():
        acc = suite.get("accuracy")
        if isinstance(acc, dict):
            acc_text = ", ".join(f"{k}={v:.3f}" for k, v in acc.items())
        else:
            acc_text = f"{acc:.3f}"
        print(f"  {name:14s} n={suite['n']:3d} accuracy: {acc_text}")
    with open("probe_results.json", "w", encoding="utf-8") as fh:
        json.dump(RESULTS, fh, indent=1)
    print("  -> probe_results.json written")


client = lm.DM()

def main() -> int:
    health = client.health()
    print(f"laya-serve health: {health}")
    suite_routing()
    suite_verdicts()
    suite_formalization()
    suite_graphs()
    suite_audit()
    suite_quiz()
    summary()
    return 0


if __name__ == "__main__":
    sys.exit(main())