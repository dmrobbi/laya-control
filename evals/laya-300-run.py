#!/usr/bin/env python3
"""laya-300-run.py — run N alert states through a laya-serve endpoint.

Mirrors the Laya 300 gate methodology (REPORT-LAYA-300-POWER-20260927):
compact build_alert_state() states, model=typed-decisions, POST
/v1/systemone. Records per-decision latency, answers, routing, input
tokens, deterministic-severity expected label, and package-energy /
CPU-util / temperature samples (RAPL powercap, best-effort).

Usage: laya-300-run.py ENDPOINT STATES_JSONL OUT_PREFIX [N] [MODEL]
"""
import json, sys, time, urllib.request, statistics, collections, re

ep = sys.argv[1]
states_file = sys.argv[2]
out_prefix = sys.argv[3]
n = int(sys.argv[4]) if len(sys.argv) > 4 else 300
model = sys.argv[5] if len(sys.argv) > 5 else "typed-decisions"

QSET = {
    "severity": {"type": "choice",
                 "instructions": ("Severity class for this Wazuh alert per the SOC contract: "
                                  "informational (rule level 0-2), low (3-7), medium (8-11), "
                                  "high (12-13), critical (14+). Judge from the alert content."),
                 "criteria": {"informational": "rule level 0-2; no action; record only",
                              "low": "rule level 3-7; minor; batch review",
                              "medium": "rule level 8-11; noteworthy; routine analyst review",
                              "high": "rule level 12-13; serious; needs prompt attention",
                              "critical": "rule level 14+; immediate response"}},
    "known_pattern": {"type": "noul",
                      "instructions": "Is this a known, recurring event pattern (seen before, expected in this environment)?"},
    "response": {"type": "choice",
                 "instructions": "Which immediate response does this alert warrant?",
                 "criteria": {"note_only": "log a note only",
                              "digest_only": "include in the periodic digest",
                              "email": "email the analyst now",
                              "page": "notify the analyst immediately (call/pager)",
                              "auto_remediate": "apply the known-safe automated remediation"}},
}

SEV_FLOORS = [(14, "critical"), (12, "high"), (8, "medium"), (3, "low"), (0, "informational")]

def expected_severity(level):
    lv = level if isinstance(level, int) else 0
    for floor, s in SEV_FLOORS:
        if lv >= floor:
            return s
    return "informational"

def build_state(r):
    """Compact SOC state from the realtime row (full_alert nested preferred)."""
    a = r.get("full_alert") or r
    rule = a.get("rule") or {}
    desc = ""
    if isinstance(rule, dict):
        desc = str(rule.get("description") or "")[:220]
    if not desc:
        desc = str(r.get("rule_description") or "")[:220]
    agent = r.get("agent_name") or "unknown-agent"
    if isinstance(a.get("agent"), dict):
        agent = (a["agent"].get("name") or agent)
    dec = a.get("decoder")
    dec = dec.get("name") if isinstance(dec, dict) else dec
    data = a.get("data") or {}
    srcip = data.get("srcip") or data.get("src_ip") or data.get("source_ip") or r.get("src_ip")
    parts = [f"Wazuh alert rule {rule.get('id') or r.get('rule_id')} severity level {rule.get('level') or r.get('level')} on agent {agent}."]
    if desc:
        parts.append(f"Rule: {desc}.")
    if dec:
        parts.append(f"Decoder: {dec}.")
    if srcip:
        parts.append(f"Source IP: {srcip}.")
    if a.get("location"):
        parts.append(f"Location: {a['location']}.")
    return " ".join(parts)


def rapl_uj():
    for p in ("/sys/class/powercap/intel-rapl:0/energy_uj",):
        try:
            return int(open(p).read().strip())
        except Exception:
            pass
    try:
        import subprocess
        out = subprocess.run(["sudo", "-n", "cat", "/sys/class/powercap/intel-rapl:0/energy_uj"],
                             capture_output=True, text=True, timeout=5)
        if out.returncode == 0:
            return int(out.stdout.strip())
    except Exception:
        pass
    return None


def cpu_times():
    with open("/proc/stat") as f:
        p = f.readline().split()[1:]
    vals = [int(x) for x in p]
    idle = vals[3] + (vals[4] if len(vals) > 4 else 0)
    return sum(vals), idle


def cpu_pct(dtv):
    t2, i2 = cpu_times()
    if cpu_pct.total is None:
        cpu_pct.total = (t2, i2)
        return None
    dt = t2 - cpu_pct.total[0]
    di = i2 - cpu_pct.total[1]
    cpu_pct.total = (t2, i2)
    return round(100.0 * (dt - di) / dt, 1) if dt else None

cpu_pct.total = None


def temps():
    out = {}
    try:
        for p in sorted(__import__("glob").glob("/sys/class/hwmon/hwmon*/temp*_input")):
            name = ""
            try: name = open(os.path.join(os.path.dirname(p), "name")).read().strip()
            except Exception: pass
            try: out[name + "/" + os.path.basename(p).split("_")[0]] = int(open(p).read().strip()) / 1000
            except Exception: pass
    except Exception:
        pass
    try:
        out["gpu_temp"] = float(__import__("subprocess").run(
            ["nvidia-smi", "--query-gpu=temperature.gpu", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=8).stdout.strip().splitlines()[0])
        out["gpu_w"] = float(__import__("subprocess").run(
            ["nvidia-smi", "--query-gpu=power.draw", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=8).stdout.strip().splitlines()[0].replace(" W", "").replace("[", "").replace("N/A", "0"))
    except Exception:
        pass
    return out


def pctl(xs, p):
    xs = sorted(xs)
    if not xs:
        return None
    return xs[min(len(xs) - 1, int(round(p / 100 * (len(xs) - 1))))]


rows = [json.loads(l) for l in open(states_file) if l.strip()][:n]
print(f"endpoint: {ep} | states: {len(rows)} | model: {model}", flush=True)

# idle power baseline (laya-serve loaded + idle)
idle0, idle1 = None, None
e_idle0, e_idle1 = None, None
try:
    idle0 = rapl_uj(); t_idle0 = time.time()
    time.sleep(15)
    idle1 = rapl_uj(); t_idle1 = time.time()
except Exception:
    pass
idle_w = None
try:
    if idle0 is not None and idle1 is not None and (t_idle1 - t_idle0) > 0:
        idle_w = round((idle1 - idle0) / 1e6 / (t_idle1 - t_idle0), 2)
except Exception:
    pass
print(f"idle package power: {idle_w} W", flush=True)

results, lat = [], []
fails = 0
e0, t_wall0 = rapl_uj(), time.time()
c0 = cpu_times()

for i, r in enumerate(rows):
    state = build_state(r)
    exp = expected_severity(r.get("level"))
    t0 = time.perf_counter()
    try:
        req = urllib.request.Request(
            ep + "/v1/systemone",
            data=json.dumps({"state": state, "questions": QSET, "model": model}).encode("utf-8"),
            headers={"content-type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=30) as resp:
            d = json.load(resp)
        lat_ms = round((time.perf_counter() - t0) * 1000, 1)
        ans = d.get("answers") or {}
        rec = {"i": i, "ok": 1, "latency_ms": lat_ms,
               "routing_model": (d.get("routing") or {}).get("model"),
               "input_tokens": (d.get("usage") or {}).get("input_tokens"),
               "severity_answer": (ans.get("severity") or {}).get("choice"),
               "known_noul": (ans.get("known_pattern") or {}).get("noul"),
               "response_answer": (ans.get("response") or {}).get("choice"),
               "answer_confidence": (ans.get("severity") or {}).get("answer_confidence"),
               "expected_severity": exp}
        lat.append(lat_ms)
    except Exception as e:
        lat_ms = round((time.perf_counter() - t0) * 1000, 1)
        fails += 1
        rec = {"i": i, "ok": 0, "latency_ms": lat_ms, "error": repr(e)[:200], "expected_severity": exp}
    results.append(rec)
    if (i + 1) % 50 == 0:
        okl = sorted(x["latency_ms"] for x in results if x.get("ok"))
        print(f"  {i+1}/{len(rows)}  p50 {okl[len(okl)//2] if okl else '-'} ms  fails {fails}", flush=True)

e1, t_wall1 = rapl_uj(), time.time()
wall = round(t_wall1 - t_wall0, 1)
ok_results = [x for x in results if x.get("ok")]
ok_lat = [x["latency_ms"] for x in ok_results]
agree = [x for x in ok_results if x.get("severity_answer") == x.get("expected_severity")]

energy = {}
try:
    if e0 is not None and e1 is not None:
        joules = (e1 - e0) / 1e6
        energy = {"package_j": round(joules, 1),
                  "avg_pkg_w": round(joules / wall, 2) if wall else None,
                  "wh_per_300_decisions": round(joules / 1e6 / 3.6, 3),
                  "wall_s": wall,
                  "idle_pkg_w": idle_w}
except Exception:
    pass

summary = {"endpoint": ep, "model": model, "n_states": len(rows), "n_ok": len(ok_results), "n_fail": fails,
           "latency_ms": {"p50": pctl(lat, 50), "p95": pctl(lat, 95),
                          "mean": round(statistics.mean(lat), 1) if lat else None},
           "severity_agreement_vs_contract_pct": round(100.0 * len(agree) / max(1, len(ok_results)), 1),
           "response_classes": dict(sorted(collections.Counter(x.get("response_answer") for x in ok_results).items(), key=lambda kv: -kv[1])),
           "routing_models": dict(collections.Counter(x.get("routing_model") for x in ok_results)),
           "input_tokens_total": sum(x.get("input_tokens") or 0 for x in ok_results),
           "energy": energy}
json.dump(summary, open(out_prefix + "-summary.json", "w"), indent=2)
with open(out_prefix + "-rows.jsonl", "w") as f:
    for r in results:
        f.write(json.dumps(r, default=str) + "\n")
print(json.dumps(summary, indent=2), flush=True)
print("RUN COMPLETE", flush=True)