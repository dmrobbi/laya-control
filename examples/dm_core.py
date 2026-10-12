"""dm_core.py — deterministic discrete-math engine for the Laya workspace.

Every function here is pure Python (stdlib only) and deterministic: the same
inputs always produce the same ground-truth answer. These functions are the
System-2 side of the architecture documented in docs/LAYA-DISCRETE-MATH.md —
they compute; Laya (the System-1 decision model) routes, checks, and grades.

Domains covered:
  * propositional logic      — parse, truth tables, tautology/satisfiability,
                               equivalence of two formulas
  * set algebra              — counterexample search for set identities
  * number theory            — gcd/extended gcd, modular inverse, primality,
                               prime factors, Euler totient, modular powers
  * combinatorics            — permutations, combinations, stars & bars,
                               derangements, inclusion-exclusion, Catalan
  * graph theory             — BFS connectivity, cycle detection, bipartite
                               2-coloring, degree sequences, shortest paths
  * recurrences              — linear-recurrence evaluation and closed-form
                               verification for a range of n

Design rule: a function that answers a question returns (answer, evidence)
where evidence is a human-readable string (a witness, a counterexample, or a
short derivation) that a study tool or an analyst can cite directly.
"""

from __future__ import annotations

import math

# ---------------------------------------------------------------- propositional logic

_TOKEN_OPS = (
    ("<=>", "iff"),
    ("<->", "iff"),
    ("->", "impl"),
    ("&&", "and"),
    ("||", "or"),
)


def _tokenize(text: str):
    """Tokenize a propositional formula into ('var'|'op'|'lp'|'rp'|'const')."""
    tokens = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch.isspace():
            i += 1
            continue
        if ch == "(":
            tokens.append(("lp", ch))
            i += 1
        elif ch == ")":
            tokens.append(("rp", ch))
            i += 1
        elif ch.isalnum() or ch == "_":
            j = i
            while j < n and (text[j].isalnum() or text[j] == "_"):
                j += 1
            word = text[i:j]
            if word in ("TRUE", "T", "true"):
                tokens.append(("const", True))
            elif word in ("FALSE", "F", "false"):
                tokens.append(("const", False))
            else:
                tokens.append(("var", word))
            i = j
        else:
            # operators: unicode and ascii spellings normalised to names
            if ch in "¬~!":
                tokens.append(("op", "not"))
                i += 1
            elif ch in "∧&^":
                tokens.append(("op", "and"))
                i += 1
            elif ch in "∨|":
                tokens.append(("op", "or"))
                i += 1
            elif ch == "→":
                tokens.append(("op", "impl"))
                i += 1
            elif ch == "↔":
                tokens.append(("op", "iff"))
                i += 1
            else:
                matched = False
                for spelling, name in _TOKEN_OPS:
                    if text.startswith(spelling, i):
                        tokens.append(("op", name))
                        i += len(spelling)
                        matched = True
                        break
                if not matched:
                    raise ValueError(f"unexpected character {ch!r} at position {i}")
    return tokens


class _Parser:
    """Recursive-descent parser. Precedence: not > and > or > implies > iff.
    implies and iff are right-associative."""

    def __init__(self, tokens):
        self.toks = tokens
        self.pos = 0

    def peek(self):
        return self.toks[self.pos] if self.pos < len(self.toks) else (None, None)

    def take(self):
        tok = self.peek()
        self.pos += 1
        return tok

    def parse(self):
        node = self.parse_iff()
        if self.pos != len(self.toks):
            raise ValueError("trailing tokens after end of formula")
        return node

    def parse_iff(self):
        left = self.parse_impl()
        kind, value = self.peek()
        if kind == "op" and value == "iff":
            self.take()
            right = self.parse_iff()
            return ("iff", left, right)
        return left

    def parse_impl(self):
        left = self.parse_or()
        kind, value = self.peek()
        if kind == "op" and value == "impl":
            self.take()
            right = self.parse_impl()
            return ("impl", left, right)
        return left

    def parse_or(self):
        left = self.parse_and()
        while self.peek() == ("op", "or"):
            self.take()
            right = self.parse_and()
            left = ("or", left, right)
        return left

    def parse_and(self):
        left = self.parse_unary()
        while self.peek() == ("op", "and"):
            self.take()
            right = self.parse_unary()
            left = ("and", left, right)
        return left

    def parse_unary(self):
        kind, value = self.peek()
        if kind == "op" and value == "not":
            self.take()
            return ("not", self.parse_unary())
        if kind == "lp":
            self.take()
            node = self.parse_iff()
            rkind, _ = self.take()
            if rkind != "rp":
                raise ValueError("missing closing parenthesis")
            return node
        if kind in ("var", "const"):
            self.take()
            return ("lit", value)
        raise ValueError(f"unexpected token {value!r}")


def parse_formula(text: str):
    """Parse a propositional formula. Returns the AST.

    Accepted spellings: p q r ... (identifiers), TRUE/FALSE, ~ ! ¬ (not),
    & ∧ ^ (and), | ∨ (or), -> → (implies), <=> <-> ↔ (iff), parentheses.
    """
    return _Parser(_tokenize(text)).parse()


def formula_variables(ast) -> list[str]:
    """Sorted list of variable names used by the formula."""
    kind = ast[0]
    if kind == "lit":
        return [ast[1]] if isinstance(ast[1], str) else []
    if kind == "not":
        return formula_variables(ast[1])
    if kind in ("and", "or", "impl", "iff"):
        return sorted(set(formula_variables(ast[1])) | set(formula_variables(ast[2])))
    raise ValueError(f"bad AST node {ast!r}")


def eval_formula(ast, assignment) -> bool:
    """Evaluate the formula under a {variable: bool} assignment."""
    kind = ast[0]
    if kind == "lit":
        return True if not isinstance(ast[1], str) else bool(assignment[ast[1]])
    if kind == "not":
        return not eval_formula(ast[1], assignment)
    if kind == "and":
        return eval_formula(ast[1], assignment) and eval_formula(ast[2], assignment)
    if kind == "or":
        return eval_formula(ast[1], assignment) or eval_formula(ast[2], assignment)
    if kind == "impl":
        return (not eval_formula(ast[1], assignment)) or eval_formula(ast[2], assignment)
    if kind == "iff":
        return eval_formula(ast[1], assignment) == eval_formula(ast[2], assignment)
    raise ValueError(f"bad AST node {ast!r}")


def truth_assignments(variables) -> list[dict]:
    """All 2**n assignments over the given variables (big-endian: first var is MSB)."""
    n = len(variables)
    rows = []
    for value in range(1 << n):
        assignment = {}
        for index, name in enumerate(variables):
            bit = (value >> (n - 1 - index)) & 1
            assignment[name] = bool(bit)
        rows.append(assignment)
    return rows


def truth_table(text: str) -> list[tuple[tuple, bool]]:
    """Full truth table as [(assignment-tuple, value), ...] in canonical order."""
    ast = parse_formula(text)
    variables = formula_variables(ast)
    rows = []
    for assignment in truth_assignments(variables):
        key = tuple(assignment[name] for name in variables)
        rows.append((key, eval_formula(ast, assignment)))
    return rows


def is_satisfied(text: str, assignment: dict) -> bool:
    """Does the given partial-or-total assignment satisfy the formula?

    Variables not present in the assignment are treated as False only if the
    formula never references them; a missing referenced variable is an error.
    """
    ast = parse_formula(text)
    for name in formula_variables(ast):
        if name not in assignment:
            raise KeyError(f"assignment is missing variable {name!r}")
    return eval_formula(ast, assignment)


def is_tautology(text: str) -> bool:
    rows = truth_table(text)
    return all(value for _, value in rows)


def is_contradiction(text: str) -> bool:
    rows = truth_table(text)
    return not any(value for _, value in rows)


def satisfiable(text: str) -> bool:
    rows = truth_table(text)
    return any(value for _, value in rows)


def satisfying_assignment(text: str, want_satisfying: bool = True):
    """First (canonical) satisfying assignment, or None. Evidence-friendly."""
    variables = formula_variables(parse_formula(text))
    for assignment in truth_assignments(variables):
        if eval_formula(parse_formula(text), assignment) == want_satisfying:
            return {name: assignment[name] for name in variables}
    return None


def formulas_equivalent(text_a: str, text_b: str) -> bool:
    """Do two formulas agree on every assignment over their union of variables?"""
    ast_a, ast_b = parse_formula(text_a), parse_formula(text_b)
    variables = sorted(set(formula_variables(ast_a)) | set(formula_variables(ast_b)))
    for assignment in truth_assignments(variables):
        if eval_formula(ast_a, assignment) != eval_formula(ast_b, assignment):
            return False
    return True


def formula_classify(text: str) -> str:
    """Tautology / contradiction / contingent, with the row count as evidence."""
    rows = truth_table(text)
    values = [value for _, value in rows]
    if all(values):
        return f"tautology ({len(rows)} rows all true)"
    if not any(values):
        return f"contradiction ({len(rows)} rows all false)"
    ones = sum(values)
    return f"contingent ({ones} of {len(rows)} rows true)"


# ---------------------------------------------------------------- set algebra


def _set_tokens(text: str):
    # word spellings first, so "union" does not collide with the single-char
    # spellings u (union) and n (intersection)
    text = text.replace("diff", "\\").replace("union", "\u222a").replace("inter", "\u2229")
    tokens = []
    i, n = 0, len(text)
    names = "ABC"
    while i < n:
        ch = text[i]
        if ch.isspace():
            i += 1
            continue
        if ch == "(":
            tokens.append(("lp", ch))
            i += 1
        elif ch == ")":
            tokens.append(("rp", ch))
            i += 1
        elif ch in names:
            tokens.append(("var", ch))
            i += 1
        elif ch == "'":
            tokens.append(("op", "compl"))
            i += 1
        elif ch in "∪uU":
            tokens.append(("op", "union"))
            i += 1
        elif ch in "∩nN":
            tokens.append(("op", "inter"))
            i += 1
        elif ch == "\\":
            tokens.append(("op", "diff"))
            i += 1
        else:
            raise ValueError(f"unexpected character {ch!r} in set expression")
    return tokens


def _set_parse(tokens):
    """Grammar: expr ::= term (('union'|'diff') term)*; term ::= atom (inter atom)*;
    atom ::= var | atom' | '(' expr ')'."""
    pos = [0]

    def peek():
        return tokens[pos[0]] if pos[0] < len(tokens) else (None, None)

    def take():
        tok = tokens[pos[0]]
        pos[0] += 1
        return tok

    def atom():
        kind, value = peek()
        if kind == "var":
            take()
            node = ("var", value)
            while peek() == ("op", "compl"):
                take()
                node = ("compl", node)
            return node
        if kind == "lp":
            take()
            node = expr()
            if take()[0] != "rp":
                raise ValueError("missing ')' in set expression")
            while peek() == ("op", "compl"):
                take()
                node = ("compl", node)
            return node
        raise ValueError(f"unexpected set token {value!r}")

    def term():
        node = atom()
        while peek() == ("op", "inter"):
            take()
            node = ("inter", node, atom())
        return node

    def expr():
        node = term()
        while peek() in (("op", "union"), ("op", "diff")):
            op = take()[1]
            node = (op, node, term())
        return node

    node = expr()
    if pos[0] != len(tokens):
        raise ValueError("trailing tokens in set expression")
    return node


def _set_eval(ast, universe, assignment):
    if ast[0] == "var":
        return assignment[ast[1]]
    if ast[0] == "compl":
        return universe - _set_eval(ast[1], universe, assignment)
    left = _set_eval(ast[1], universe, assignment)
    right = _set_eval(ast[2], universe, assignment)
    if ast[0] == "union":
        return left | right
    if ast[0] == "inter":
        return left & right
    if ast[0] == "diff":
        return left - right
    raise ValueError(f"bad set AST {ast!r}")


def set_identity_check(lhs_text: str, rhs_text: str, universe_size: int = 3):
    """Brute-force check of a set identity over every subset of a finite universe.

    Returns (holds, counterexample-or-None). A counterexample is a full value
    assignment witnessing lhs != rhs — the evidence a study tool cites.
    """
    universe = frozenset(range(universe_size))
    lhs_ast = _set_parse(_set_tokens(lhs_text))
    rhs_ast = _set_parse(_set_tokens(rhs_text))
    used = []

    def collect(ast):
        if ast[0] == "var" and ast[1] not in used:
            used.append(ast[1])
        elif ast[0] != "var":
            collect(ast[1])
            if len(ast) == 3:
                collect(ast[2])

    collect(lhs_ast)
    collect(rhs_ast)
    names = sorted(used)
    for value in range(1 << len(names)):
        assignment = {name: frozenset(x for x in universe if (value >> x) & 1) for name in names}
        left = _set_eval(lhs_ast, universe, assignment)
        right = _set_eval(rhs_ast, universe, assignment)
        if left != right:
            return False, dict(assignment) | {"lhs": set(left), "rhs": set(right)}
    return True, None


# ---------------------------------------------------------------- number theory


def gcd_steps(a: int, b: int):
    """Euclidean algorithm returning (gcd, step count), evidence-friendly."""
    a, b = abs(a), abs(b)
    steps = 0
    while b:
        a, b = b, a % b
        steps += 1
    return a, steps


def extended_gcd(a: int, b: int):
    """Return (g, x, y) with a*x + b*y == g == gcd(a, b)."""
    old_r, r = a, b
    old_s, s = 1, 0
    old_t, t = 0, 1
    while r:
        q = old_r // r
        old_r, r = r, old_r - q * r
        old_s, s = s, old_s - q * s
        old_t, t = t, old_t - q * t
    return old_r, old_s, old_t


def mod_inverse(a: int, m: int):
    """Modular inverse of a mod m, or None when gcd(a, m) != 1."""
    g, x, _ = extended_gcd(a % m, m)
    if g != 1:
        return None
    return x % m


def is_prime(n: int) -> bool:
    """Deterministic trial division (6k±1 walk) — exact for teaching sizes."""
    if n < 2:
        return False
    if n in (2, 3):
        return True
    if n % 2 == 0 or n % 3 == 0:
        return False
    i = 5
    while i * i <= n:
        if n % i == 0 or n % (i + 2) == 0:
            return False
        i += 6
    return True


def prime_factors(n: int) -> list[int]:
    """Prime factorisation as a sorted list (with multiplicity)."""
    factors = []
    while n % 2 == 0:
        factors.append(2)
        n //= 2
    p = 3
    while p * p <= n:
        while n % p == 0:
            factors.append(p)
            n //= p
        p += 2
    if n > 1:
        factors.append(n)
    return factors


def totient(n: int) -> int:
    """Euler's phi via the product formula over the prime factorisation."""
    result = n
    for p in sorted(set(prime_factors(n))):
        result -= result // p
    return result


def is_coprime(a: int, b: int) -> bool:
    return gcd_steps(a, b)[0] == 1


def mod_pow(base: int, exponent: int, modulus: int) -> int:
    """Fast modular exponentiation (square-and-multiply)."""
    if modulus == 1:
        return 0
    result = 1
    base %= modulus
    while exponent:
        if exponent & 1:
            result = result * base % modulus
        base = base * base % modulus
        exponent >>= 1
    return result


def fermat_witness(n: int, base: int = 2):
    """Fermat check: returns (holds, note). holds == False is a *proof* of
    compositeness; holds == True is only evidence, never a proof."""
    n = abs(n)
    if n < 2 or is_prime(n):
        return False, "n is not a composite candidate"
    value = mod_pow(base, n - 1, n)
    note = f"{base}^({n}-1) mod {n} == {value}"
    if value == 1:
        return True, note + " (pseudoprime evidence only, not a proof)"
    return False, note + " != 1 -> proof of compositeness"


# ---------------------------------------------------------------- combinatorics


def permutations_count(n: int, k: int) -> int:
    """P(n, k) = n! / (n-k)!."""
    if not (0 <= k <= n):
        return 0
    result = 1
    for value in range(n, n - k, -1):
        result *= value
    return result


def combinations_count(n: int, k: int) -> int:
    """C(n, k) — exact integer Pascal computation, no float rounding."""
    if not (0 <= k <= n):
        return 0
    k = min(k, n - k)
    result = 1
    for step in range(k):
        result = result * (n - step) // (step + 1)
    return result


def stars_and_bars(n_items: int, boxes: int) -> int:
    """Non-negative integer solutions of x1+...+xk == n -> C(n+k-1, k-1)."""
    if boxes <= 0:
        return 1 if n_items == 0 else 0
    return combinations_count(n_items + boxes - 1, boxes - 1)


def derangements(n: int) -> int:
    """!n — permutations of n items with no fixed point (recurrence form)."""
    if n == 0:
        return 1
    if n == 1:
        return 0
    d_prev, d_curr = 1, 0
    for k in range(2, n + 1):
        d_prev, d_curr = d_curr, (k - 1) * (d_curr + d_prev)
    return d_curr


def derangements_fast(n: int) -> int:
    """Explicit inclusion-exclusion form: sum_{k=0}^{n} (-1)^k * n! / k!."""
    total = 0
    factorial = 1
    for k in range(n + 1):
        if k:
            factorial *= k
        total += (-1) ** k * (math.factorial(n) // factorial)
    return total


def inclusion_exclusion_3(a: int, b: int, c: int, ab: int, ac: int, bc: int, abc: int) -> int:
    """|A ∪ B ∪ C| from pairwise and triple intersections."""
    return a + b + c - ab - ac - bc + abc


def catalan(n: int) -> int:
    """Catalan(n) = C(2n, n) / (n+1) — exact via Pascal arithmetic."""
    return combinations_count(2 * n, n) // (n + 1)


# ---------------------------------------------------------------- graph theory


def build_adjacency(n_vertices: int, edges) -> dict[int, list[int]]:
    """Undirected adjacency from an edge list of (u, v) pairs (0-indexed)."""
    adjacency = {vertex: [] for vertex in range(n_vertices)}
    for u, v in edges:
        for a, b in ((u, v), (v, u)):
            if not (0 <= a < n_vertices and 0 <= b < n_vertices):
                raise ValueError(f"edge ({u}, {v}) out of range for {n_vertices} vertices")
            adjacency[a].append(b)
    return adjacency


def graph_connected(n_vertices: int, edges) -> bool:
    """BFS reachability from vertex 0 (undirected). Single vertex = connected."""
    if n_vertices <= 1:
        return True
    adjacency = build_adjacency(n_vertices, edges)
    seen = {0}
    frontier = [0]
    while frontier:
        vertex = frontier.pop()
        for neighbour in adjacency[vertex]:
            if neighbour not in seen:
                seen.add(neighbour)
                frontier.append(neighbour)
    return len(seen) == n_vertices


def graph_has_cycle_undirected(n_vertices: int, edges) -> bool:
    """Union-find cycle detection (undirected)."""
    parent = list(range(n_vertices))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for u, v in edges:
        ru, rv = find(u), find(v)
        if ru == rv:
            return True
        parent[ru] = rv
    return False


def graph_bipartite(n_vertices: int, edges):
    """2-coloring check. Returns (bipartite, {vertex: color} or None)."""
    adjacency = build_adjacency(n_vertices, edges)
    color = {}
    for start in range(n_vertices):
        if start in color:
            continue
        color[start] = 0
        frontier = [start]
        while frontier:
            vertex = frontier.pop()
            for neighbour in adjacency[vertex]:
                if neighbour not in color:
                    color[neighbour] = color[vertex] ^ 1
                    frontier.append(neighbour)
                elif color[neighbour] == color[vertex]:
                    return False, None
    return True, color


def degree_sequence(n_vertices: int, edges) -> list[int]:
    """Out degree = total degree for undirected edges; sorted descending."""
    degrees = [0] * n_vertices
    for u, v in edges:
        degrees[u] += 1
        degrees[v] += 1
    return sorted(degrees, reverse=True)


def euler_path_possible(n_vertices: int, edges):
    """Euler path/circuit feasibility: connected + 0 or 2 odd-degree vertices."""
    if not graph_connected(n_vertices, edges):
        return False, "not connected"
    degree_list = [0] * n_vertices
    for u, v in edges:
        degree_list[u] += 1
        degree_list[v] += 1
    odd_count = sum(1 for d in degree_list if d % 2)
    if odd_count == 0:
        return True, "euler circuit (0 odd-degree vertices)"
    if odd_count == 2:
        return True, "euler path (exactly 2 odd-degree vertices)"
    return False, f"{odd_count} odd-degree vertices (need 0 or 2)"


def shortest_path_unweighted(n_vertices: int, edges, source: int, target: int):
    """BFS shortest path. Returns (distance, path) or (None, None)."""
    adjacency = build_adjacency(n_vertices, edges)
    if source == target:
        return 0, [source]
    parent = {source: None}
    frontier = [source]
    while frontier:
        next_frontier = []
        for vertex in frontier:
            for neighbour in adjacency[vertex]:
                if neighbour not in parent:
                    parent[neighbour] = vertex
                    if neighbour == target:
                        path = [target]
                        while parent[path[-1]] is not None:
                            path.append(parent[path[-1]])
                        return len(path) - 1, list(reversed(path))
                    next_frontier.append(neighbour)
        frontier = next_frontier
    return None, None


# ---------------------------------------------------------------- recurrences


def linear_recurrence(coeffs: list[int], initial: list[int], n_th: int, plus: int = 0) -> int:
    """Evaluate a linear recurrence a(n) = c1*a(n-1) + ... + ck*a(n-k) + plus.

    `initial` must carry the first k values a(0)..a(k-1). Indices are
    0-based; n_th must be >= 0. `plus` supports the classic
    non-homogeneous case (towers of Hanoi: a(n) = 2*a(n-1) + 1).
    """
    k = len(coeffs)
    if len(initial) < k:
        raise ValueError("initial needs k terms")
    if n_th < 0:
        raise ValueError("n_th must be >= 0")
    if n_th < k:
        return initial[n_th]
    window = list(initial[:k])
    for _ in range(k, n_th + 1):
        nxt = sum(c * a for c, a in zip(coeffs, reversed(window))) + plus
        window = window[1:] + [nxt]
    return window[-1]


def verify_closed_form(
    coeffs: list[int], initial: list[int], closed_form, up_to: int = 20, plus: int = 0
):
    """Verify a claimed closed form against the recurrence for n in [0, up_to].

    Returns (all_equal, first_mismatch) where first_mismatch is
    (n, recurrence_value, closed_value) or None.
    """
    for n in range(up_to + 1):
        recurrence_value = linear_recurrence(coeffs, initial, n, plus=plus)
        closed_value = closed_form(n)
        if recurrence_value != closed_value:
            return False, (n, recurrence_value, closed_value)
    return True, None


def arithmetic_sum(n_terms: int, first: int, step: int) -> int:
    """Sum of the first n_terms of an arithmetic sequence."""
    if n_terms <= 0:
        return 0
    last = first + (n_terms - 1) * step
    return n_terms * (first + last) // 2


def geometric_sum(n_terms: int, base: int) -> int:
    """1 + base + base^2 + ... + base^(n_terms-1) — exact integer arithmetic."""
    if n_terms <= 0:
        return 0
    if base == 1:
        return n_terms
    return (base**n_terms - 1) // (base - 1)


# ---------------------------------------------------------------- convenience


DOMAIN_ENGINES = {
    "logic": "truth tables, satisfiability, equivalence",
    "sets": "set-identity counterexample search",
    "combinatorics": "exact counting (P, C, stars&bars, derangements)",
    "graphs": "connectivity, cycles, bipartite, shortest paths",
    "number_theory": "gcd, inverse, primality, totient",
    "recurrence": "linear recurrences + closed-form verification",
}


def engine_manifest() -> dict:
    """The dispatch table the routing tutorials teach: domain -> capabilities."""
    return dict(DOMAIN_ENGINES)