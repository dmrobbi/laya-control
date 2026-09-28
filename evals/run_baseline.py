#!/usr/bin/env python3
"""Score Laya checkpoints over SOC eval datasets (Phase 0.3 baseline).

Upstream `laya-evals` exists only on GitHub main (not PyPI 0.3.20), so this
runner implements the same core metrics directly via Router.predict. Dataset
format is upstream-compatible ({state, questions, expected, tags}) — swappable
to `laya-evals run` when a release ships it.

Metrics: choice_accuracy, noul_accuracy (P>=0.5), mean answer_confidence,
latency p50/p95, majority-class baseline per question. No ECE here (n is
small; 15-bin calibration noise) — upstream harness gets that later.
"""
import argparse
import json
import os
import statistics
import time
from collections import Counter, defaultdict
from pathlib import Path

os.environ.setdefault("HF_HOME", str(Path.home() / "laya" / "hf-cache"))
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("LAYA_THREADS", "8")


def pctl(xs, p):
    xs = sorted(xs)
    if not xs:
        return 0
    i = min(len(xs) - 1, int(round(p / 100 * (len(xs) - 1))))
    return xs[i]


def majority_baseline(rows):
    base = {}
    per_q = defaultdict(list)
    for r in rows:
        for q, exp in r["expected"].items():
            per_q[q].append(exp)
    for q, vals in per_q.items():
        c = Counter(str(v) for v in vals)
        base[q] = {"majority": vals[0] if not isinstance(vals[0], bool) else vals[0],
                   "majority_share": Counter(bool(v) if isinstance(vals[0], bool) else str(v) for v in vals).most_common(1)[0][1] / len(vals)}
    return base


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default=str(Path(__file__).resolve().parent / "soc-triage-v0.jsonl"))
    ap.add_argument("--models", default="english,typed-decisions")
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent / "results"))
    args = ap.parse_args()
    rows = [json.loads(l) for l in open(args.dataset) if l.strip()]
    Path(args.out).mkdir(parents=True, exist_ok=True)
    print(f"dataset: {args.dataset} ({len(rows)} rows)\n")

    from laya import Router
    for model in [m.strip() for m in args.models.split(",") if m.strip()]:
        router = Router(preload=False)
        res, lat = defaultdict(lambda: {"ok": 0, "n": 0, "conf": []}), []
        confusions = defaultdict(lambda: defaultdict(int))
        for r in rows:
            t0 = time.perf_counter()
            out = router.predict(r["state"], r["questions"], model=model)
            lat.append((time.perf_counter() - t0) * 1000)
            for q, exp in r["expected"].items():
                a = out["answers"][q]
                m = r["questions"][q]["type"]
                d = res[q] = res.get(q) or res[q]  # defaultdict handles
                if m == "choice":
                    pred = a["choice"]
                    d["n"] += 1
                    d["ok"] += int(pred == exp)
                    confusions[q][f"{exp} -> {pred}"] += 1
                else:  # noul
                    pred = a["noul"] >= 0.5
                    d["n"] += 1
                    d["ok"] += int(pred == exp)
                d["conf"].append(a.get("answer_confidence"))
        report = {"model": model, "dataset": Path(args.dataset).name, "n_rows": len(rows),
                  "latency_ms": {"p50": round(pctl(lat, 50)), "p95": round(pctl(lat, 95)), "mean": round(statistics.mean(lat))},
                  "questions": {}, "majority_baseline": majority_baseline(rows), "confusions": {}}
        for q, d in sorted(res.items()):
            report["questions"][q] = {
                "accuracy": round(d["ok"] / d["n"], 3),
                "n": d["n"],
                "mean_confidence": round(statistics.mean(d["conf"]), 3) if d["conf"] else None,
            }
        for q, cm in confusions.items():
            report["confusions"][q] = dict(sorted(cm.items(), key=lambda x: -x[1]))
        path = Path(args.out) / f"baseline-{model}.json"
        path.write_text(json.dumps(report, indent=2))
        print(f"== {model} == ({len(rows)} rows, latency p50 {report['latency_ms']['p50']} ms / p95 {report['latency_ms']['p95']} ms)")
        for q, m in report["questions"].items():
            print(f"  {q:14s} acc {m['accuracy']:.3f}  mean_conf {m['mean_confidence']}")
        print(f"  wrote {path}\n")


if __name__ == "__main__":
    main()