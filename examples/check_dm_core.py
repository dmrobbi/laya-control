"""check_dm_core.py — self-test for the deterministic engine.

Run:  python3 check_dm_core.py
Every check is a hard assert with a known-true value from the literature;
the script prints [ok] per group and exits non-zero on any failure.
Engine truth is what the Laya tutorials gate against, so this file is the
trust anchor for everything else in examples/.
"""

import sys

import dm_core


def check(group: str, condition: bool, detail: str = ""):
    if not condition:
        print(f"[FAIL] {group}: {detail}")
        sys.exit(1)
    print(f"[ok] {group}{': ' + detail if detail else ''}")


# ---- propositional logic -------------------------------------------------
check("logic parse", dm_core.formula_variables(dm_core.parse_formula("(p -> q) & ~q -> ~p")) == ["p", "q"])
check("logic tautology", dm_core.is_tautology("(p -> q) & ~q -> ~p"), "modus tollens")
check("logic contingent", dm_core.formula_classify("p | q").startswith("contingent"))
check("logic contradiction", dm_core.is_contradiction("p & ~p"))
check("logic satisfiable", dm_core.satisfiable("p & (q | ~r)"))
check(
    "logic satisfies",
    dm_core.is_satisfied("(p | q) & ~r", {"p": False, "q": True, "r": False}),
    "T/F/T",
)
check(
    "logic not-satisfied",
    not dm_core.is_satisfied("p -> q", {"p": True, "q": False}),
    "T->F must be false",
)
check("logic equivalence", dm_core.formulas_equivalent("~(p & q)", "~p | ~q"), "De Morgan")
check("logic equivalence false", not dm_core.formulas_equivalent("p | q", "p & q"))
check("logic first-sat", dm_core.satisfying_assignment("p & q") == {"p": True, "q": True})

# table order sanity: ascending value space, first variable is MSB ->
# (p,q) rows come out (F,F),(F,T),(T,F),(T,T)
check(
    "logic table order",
    dm_core.truth_table("p & q") == [((False, False), False), ((False, True), False), ((True, False), False), ((True, True), True)],
)

# ---- set algebra ---------------------------------------------------------
check("sets demorgan", dm_core.set_identity_check("(A union B)'", "A' n B'")[0], "De Morgan over 3-universe")
check("sets morgan fails", not dm_core.set_identity_check("A u B'", "A n B'")[0], "must find a counterexample")
bad = dm_core.set_identity_check("A u B'", "A n B'")
check("sets counterexample shape", bad[1] is not None and "lhs" in bad[1] and "rhs" in bad[1])
check("sets distributive", dm_core.set_identity_check("A n (B u C)", "(A n B) u (A n C)")[0])
check("sets absorption", dm_core.set_identity_check("A u (A n B)", "A")[0])

# ---- number theory -------------------------------------------------------
check("nt gcd", dm_core.gcd_steps(252, 105)[0] == 21 and dm_core.gcd_steps(252, 105)[1] == 3, "3 steps")
check("nt extended", dm_core.extended_gcd(30, 4)[0] == 2 and 30 * dm_core.extended_gcd(30, 4)[1] + 4 * dm_core.extended_gcd(30, 4)[2] == 2)
check("nt inverse", dm_core.mod_inverse(3, 7) == 5, "3*5=15 =2*7+1")
check("nt no inverse", dm_core.mod_inverse(2, 4) is None)
check("nt primes", dm_core.is_prime(97) and not dm_core.is_prime(91), "91=7*13")
check("nt factors", dm_core.prime_factors(360) == [2, 2, 2, 3, 3, 5])
check("nt totient", dm_core.totient(36) == 12)
check("nt coprime", dm_core.is_coprime(8, 15) and not dm_core.is_coprime(6, 9))
check("nt modpow", dm_core.mod_pow(7, 128, 13) == pow(7, 128, 13) == 3, "Fermat: 7^12=1")
check("nt fermat proof", dm_core.fermat_witness(561, 3)[0] is False, "base 3 shares gcd(3,561)=3 -> 3^560 mod 561 is divisible by 3, != 1")
check("nt pseudoprime", dm_core.fermat_witness(341, 2)[0] is True, "341 = 11*31 fools base 2: evidence only, never a proof")

# ---- combinatorics -------------------------------------------------------
check("comb P", dm_core.permutations_count(7, 3) == 210)
check("comb C", dm_core.combinations_count(40, 3) == 9880)
check("comb C symmetry", dm_core.combinations_count(10, 8) == dm_core.combinations_count(10, 2))
check("comb stars", dm_core.stars_and_bars(10, 3) == 66, "solutions of a+b+c=10")
check("comb derange", dm_core.derangements(4) == 9 and dm_core.derangements_fast(6) == 265)
check("comb derange cross", all(dm_core.derangements(n) == dm_core.derangements_fast(n) for n in range(9)))
check("comb ie3", dm_core.inclusion_exclusion_3(15, 10, 12, 5, 4, 3, 2) == 27, "37 - 12 + 2")
check("comb catalan", [dm_core.catalan(k) for k in range(5)] == [1, 1, 2, 5, 14])

# ---- graphs --------------------------------------------------------------
EDGES_TRIANGLE = [(0, 1), (1, 2), (2, 0)]
EDGES_PATH = [(0, 1), (1, 2), (2, 3)]
EDGES_DISCONNECTED = [(0, 1), (2, 3)]
EDGES_STAR = [(0, 1), (0, 2), (0, 3)]

check("graphs connected", dm_core.graph_connected(3, EDGES_TRIANGLE) and dm_core.graph_connected(4, EDGES_PATH))
check("graphs disconnected", not dm_core.graph_connected(4, EDGES_DISCONNECTED))
check("graphs cycle", dm_core.graph_has_cycle_undirected(3, EDGES_TRIANGLE) is True and dm_core.graph_has_cycle_undirected(4, EDGES_PATH) is False)
bip, _ = dm_core.graph_bipartite(4, EDGES_STAR)
check("graphs bipartite", bip is True, "star K1,3")
bip_false, _ = dm_core.graph_bipartite(3, EDGES_TRIANGLE)
check("graphs odd cycle", bip_false is False)
check("graphs degrees", dm_core.degree_sequence(4, EDGES_STAR) == [3, 1, 1, 1])
check("graphs euler circuit", dm_core.euler_path_possible(4, [(0, 1), (1, 2), (2, 3), (3, 0)])[0], "C4: all degree 2")
check("graphs euler K4 no", not dm_core.euler_path_possible(4, [(0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3)])[0], "K4: 4 odd-degree vertices")
check("graphs euler disconnected", not dm_core.euler_path_possible(4, EDGES_TRIANGLE)[0], "vertex 3 isolated -> not connected")
dist, path = dm_core.shortest_path_unweighted(4, EDGES_PATH, 0, 3)
check("graphs shortest", dist == 3 and path == [0, 1, 2, 3])

# ---- recurrences ---------------------------------------------------------
check("rec fib", dm_core.linear_recurrence([1, 1], [0, 1], 10) == 55, "F(10)=55")
check("rec hanoi", dm_core.linear_recurrence([2], [1], 5, plus=1) == 63, "a(n)=2a(n-1)+1, a(0)=1")
ok, mismatch = dm_core.verify_closed_form([2], [1], lambda n: 2 ** (n + 1) - 1, plus=1)
check("rec closed ok", ok)
ok2, mismatch2 = dm_core.verify_closed_form([1, 1], [0, 1], lambda n: n * n, up_to=12)
check("rec closed reject", not ok2 and mismatch2[0] >= 2, "fib != n^2 past n=2")
check("rec arith", dm_core.arithmetic_sum(100, 1, 1) == 5050)
check("rec geom", dm_core.geometric_sum(8, 2) == 255 and dm_core.geometric_sum(4, 5) == 156)

print("ENGINE OK — all deterministic checks passed")