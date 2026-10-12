"""t05_graphs_edge_list.py — Tutorial 05: graph properties from text, honestly.

The measured trap: hand laya an edge list as TEXT and ask the property. It
does not reliably count reachability from tokens — connectivity came out
mediocre and bipartiteness near-chance in the capability probe. BFS from
dm_core is exact in microseconds. Teaching point: an encoder is not a
graph algorithm; structure belongs to the engine.

Run:  python3 t05_graphs_edge_list.py
Needs: a laya-serve endpoint (env LAYA_URL, default http://127.0.0.1:8099).
"""

import sys

import dm_core
import laya_math as lm

CLIENT = lm.DM()

GRAPHS = [
    (4, [(0, 1), (1, 2), (2, 3)]),               # path
    (4, [(0, 1), (2, 3)]),                       # disconnected
    (4, [(0, 1), (1, 2), (2, 0)]),               # triangle + isolated 3
    (4, [(0, 1), (1, 2), (2, 3), (3, 0)]),       # C4
    (4, [(0, 1), (0, 2), (0, 3)]),               # star K1,3
    (4, [(0, 1), (1, 2), (0, 2), (0, 3), (1, 3)]),  # two triangles sharing 0-1
    (4, [(0, 1), (1, 2)]),                       # path + isolated 3
    (4, [(0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3)]),  # K4
]

QUESTIONS = {
    "connected": {"type": "noul", "instructions": "Is this undirected graph connected (every vertex reachable from every other)?"},
    "bipartite": {"type": "noul", "instructions": "Is this undirected graph bipartite (2-colorable with no edge inside a color class)?"},
}


def main() -> int:
    lm.banner("Tutorial 05 — graph properties: laya triage vs engine truth")
    hits = {"connected": 0, "bipartite": 0}
    for n_vertices, edges in GRAPHS:
        edges_text = ", ".join(f"{u}-{v}" for u, v in edges)
        state = f"Undirected graph on {n_vertices} vertices (0-indexed). Edges: {edges_text}."
        expected = {
            "connected": dm_core.graph_connected(n_vertices, edges),
            "bipartite": dm_core.graph_bipartite(n_vertices, edges)[0],
        }
        result = CLIENT.decide(state, QUESTIONS)
        for qid in hits:
            laya_yes = lm.noul(result, qid) >= 0.5
            hits[qid] += laya_yes == expected[qid]
        verdicts = [f"{qid}: engine={'T' if expected[qid] else 'F'} laya_noul={lm.noul(result, qid):.3f}" for qid in hits]
        print(f"  edges={edges_text:32s} {'; '.join(verdicts)}")
    lm.banner("Results")
    for qid in hits:
        print(f"  {qid:10s} laya {hits[qid]}/{len(GRAPHS)} = {hits[qid] / len(GRAPHS):.3f}   engine {len(GRAPHS)}/{len(GRAPHS)} = 1.000 (BFS / 2-coloring)")
    print(f"\nWHAT TO NOTICE")
    print(f"  * connectivity: laya's yes/no from text is mediocre and asymmetric -")
    print(f"    a star K1,3 reads as disconnected while a path reads as connected.")
    print(f"  * bipartiteness: near-chance, and confidently wrong on an odd cycle.")
    print(f"  * never let the model be the graph algorithm: BFS runs in microseconds,")
    print(f"    offline, and is citable evidence. laya can triage which PROPERTY to compute.")
    return 0


if __name__ == "__main__":
    sys.exit(main())