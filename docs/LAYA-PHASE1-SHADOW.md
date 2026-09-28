# Laya Phase 1 — Shadow Mode Deployment (2026-09-26)

*Continues `docs/LAYA-SETUP.md` (Phase 0) and `docs/laya-baseline.md` (Phase 0.3).
Everything here is **log-only**: the LLM verdict still wins; revert = set
`LAYA_MODE=off` (or delete the hook).*

## What decision points exist (extraction, Phase 1.1)

Source of truth: `soc-agents/soc-triage/IDENTITY.md` + `realtime_ingest.py`:

- **soc-triage output contract:** `severity_class` ∈ informational|low|medium|high|critical
  (maps from rule level: 0-2/3-7/8-11/12-13/14+), `is_known_pattern` bool,
  `recommended_response` ∈ note_only|digest_only|email|page|auto_remediate,
  `confidence` 0-1 (system flips `low_confidence=true` below 0.4), reasoning must
  cite rule id + host.
- **realtime-ingest fallback:** severity from rule level first
  (>=12 critical, >=10 high, >=7 medium, else low), then LLM regex override;
  incident opens when sev ∈ {critical, high} or "escalate" in triage text.
- **v0 eval gaps found and fixed:** question sets now include `critical` +
  `auto_remediate` (`evals/laya_questions.yaml` v1; mirrored in
  `laya-shadow/laya_shadow.py:TRIAGE_QUESTIONS`).

Key consequence: the rule-level → severity mapping is the **objective ground
truth** for severity — no LLM-judge needed for that question.

## Wazuh label supplement (the ≥200/label fix)

Pulled stratified sample (60/level, levels 3-13) from the edge host indexer
(908,790 alerts at L≥3): **616 alerts** → `evals/data/wazuh-sample.json`
(159 KB, gitignored). Distribution reality: L5 417k, L3 405k, L7 35k,
L10 29k, L13 3.3k, L12 1.7k, L9 369, L8 113, L11 16.
Extraction tool: `evals/pull_wazuh_sample.py` (reads
`/home/operator/.openclaw/soc/secrets/wazuh-indexer.env` on edge host; never prints creds).

## Rich-state eval (objective severity labels)

`evals/rich_state_eval.py` — states are now compact alert text
(`build_alert_state`, ~50-150 tokens, well under the 512 ctx), not 30-char
summaries:

| Checkpoint | severity acc (objective) | p50 latency |
|---|---|---|
| typed-decisions | 0.269 | 914 ms |
| english | 0.198 | 947 ms |

vs **trivial baseline: level→severity mapping applied directly = 1.00**.

Read: on full alert states, **zero-shot Laya is much WORSE than the
deterministic level mapping for severity** (typed-decisions mostly over-predicts
"high": low→high 217). Confirmed: the SOC contract already encodes severity
deterministically from rule level — a Laya *choice* question is the wrong tool
for severity. **Severity decisions do not need any model**; keep them
deterministic (that also means the historical "LLM decided severity" was
unnecessary work). Laya's useful questions are the ones with no deterministic
answer: `known_pattern`, `response` (page/email/digest vs automation),
`escalate`. Those have no objective labels yet → shadow mode is exactly how we
get them.

## Shadow deployment (Phase 1.2 + 1.3)

**Artifact:** `laya-shadow/laya_shadow.py` → deployed to
`edge host:/opt/soc-openclaw/lib/laya_shadow.py` (stdlib-only; contains
`TRIAGE_QUESTIONS` v1 + `build_alert_state` + `LayaShadow` client).

- Modes via `LAYA_MODE` env: `off` (default, no-op) | `shadow` (predict + log,
  result ignored) | `gated` (Phase 2 stub). NEVER raises; log write failures go
  to stderr only.
- Log: `/opt/soc-openclaw/data/laya-shadow.jsonl` (JSONL: ts, state_hash,
  answers+confidences, routing, latency_ms, context{alert_id, level,
  ingest_severity, triage_ok}).
- **Hook:** `realtime_ingest.py` `ingest_wazuh_alert()` — after the alert record
  is built, before escalate logic. Diff is 2 guarded blocks (~20 lines);
  backup: `realtime_ingest.py.bak-laya-20260926`. `py_compile` verified,
  service restarted, `/healthz` ok (7,629 alerts logged before restart).
- **Enabled:** `LAYA_MODE=shadow` in `/etc/default/realtime-soc-server`
  (file created; code default remains off — one-line revert to off).
- **laya-serve on edge host:** `/home/operator/laya` rsynced from control host (same
  absolute paths, python 3.12.3 both), `laya-serve.service` user unit enabled,
  127.0.0.1:8099, LAYA_THREADS=6 (12-core host), 4.7 GB RAM, linger=yes.
- **Verified end-to-end:** selftest row + one real ingest POST
  (`ALERT-20260926-000001`, L5 web 400) → shadow row: severity=informational,
  1.9 s. Latency on edge host ≈ **0.9-1.9 s/predict** (4 questions, CPU, cold-ish)
  — fine vs LLM turn times; fine for ingest rates here.

## Known quirks hit this phase

1. scp/ssh heredoc + f-string quoting mangles — ship scripts, don't inline.
2. laya-serve on edge host needed the checkpoint cache; venv rsynced whole
   (`~/.openclaw/soc/secrets` perms pattern not needed — no secrets in laya dir).
3. `systemctl --user` restarts of *system* services need sudo on edge host
   (realtime-soc-server is a system unit; laya-serve is a user unit — mixed).

## Phase 1 completion (2026-09-26 15:2x)

- **imap-watcher shadow live**: `EMAIL_QUESTIONS` (reply_worthy noul, priority
  score, automated_noise noul) + `build_email_state` in `laya_shadow.py`; hook in
  `_process_one` (log-only; backup `.bak-laya-20260926`); `LAYA_MODE=shadow` in
  `/etc/default/imap-watcher`. Verified with a self-test email: Laya scored
  automated_noise 0.876 / reply_worthy 0.26 (correct — it WAS a bot
  notification); mail routing unchanged (review_later, no reply sent).
- **scanner excluded**: `soc_stig_classifier` is a deterministic dict lookup
  ("the mapping is data, not code"); `soc_scanner` is OpenSCAP parse/merge. No
  LLM decision exists there to shadow.
- **Agreement job live**: `/opt/soc-openclaw/lib/laya_agreement.py`, cron
  `55 5 * * *` (edge host, operator). Joins `laya-shadow.jsonl` × `realtime_soc.jsonl`
  on alert_id; reports severity (vs ingest AND vs objective level mapping),
  response vs LLM regex, known_pattern, escalate-vs-incident-rule →
  `/opt/soc-openclaw/data/laya-agreement-latest.json`.
- **HTTP API has no `max_len`** (v0.3.20): the multilingual checkpoint's 8192
  context is not reachable over HTTP. HTTP consumers keep states ≤ ~1024 tokens
  (compact builders). SDK-side long-doc calls remain possible
  (`Router.predict(..., model="multilingual", max_len=8192)`).
- **control host pre-step shadow: superseded** — the edge host hooks shadow the same
  decisions at the source (before `call_llm`); a gateway-side tailer would
  double-count. Revisit only if agents trigger from outside edge host.

**Shadow coverage now:** realtime-ingest (severity/known_pattern/response/
escalate) + imap-watcher (reply_worthy/priority/automated_noise), both
log-only, `LAYA_MODE`-controlled, one-line revert per service.

## Next (Phase 1 remainder)

- Let shadow collect ≥1 week / ≥300 decisions; then agreement analysis
  (Laya vs ingest sev + LLM triage) → per-question thresholds → Phase 2 gating.
- Extend shadow to `imap-watcher` + `scanner` (screen false_positive noul).
- control host-side soc-triage pre-step shadow (gateway agents) — after edge host proves stable.
- Fine-tune data: shadow rows + corrected labels = Phase 4 training set.
---

## Phase 2 start (2026-09-26 19:5x) — option B executed

operator picked option B: **realtime_ingest no longer makes a gemma turn per alert**
(edge host soc-openclaw `e639ba1`; backups `.bak-phase2B-20260926`).

- Why: the edge host `soc-triage` agent carries ~400 MB of session history →
  each turn injects ~100–150k tokens → multi-minute turns on the single-slot
  llama server. Unusable in the ingest's 25 s budget even after the 401 fix
  (the 401 was fixed first: edge host local openclaw provider repointed to
  `GPU host → http://192.0.2.70:15108/v1`, backup `openclaw.json.bak-laya-20260926`).
- Now: severity deterministic (contract mapping, Option B) + laya shadow
  (log-only) for known_pattern/response/escalate. **Ingest turn: 1.65 s
  (was 4.3–4.7 s), zero gemma usage.**
- `triage_ok` in ingest records is now always False **by design** ("no LLM
  turn"); the LLM remains on generation paths (narrator/email) via the same
  local openclaw — note those agents may carry the same bloat; narrator turns
  observed at 2–12 s (fast) so far.
- Shadow question-set note: `severity` is now redundant in the shadow set
  (deterministic) — candidate to drop at the next shadow release; the
  agreement job's `severity_vs_ingest` becomes a pure shadow-vs-fallback check.

## Addendum — wazuh decision-path improvement (2026-09-26 20:2x)

**Finding:** the agentic-soc-send decision path (soc_decision.decide, ~41/h) ran
at **1.3% success today** (3,786 attempts / 50 ok). Causes, stacked:
1. The wazuh OpenClaw instance (`~/.openclaw-wazuh`, bind-mounted into the
   wazuh.manager container, user-mapped to dnsmasq) still pointed its soc-*
   agents at **dead `ollama/minimax-m3:cloud`** — missed by the Sep 25 purge.
2. `soc_decision.decide()` default **timeout 30s** vs measured gemma decision
   turns of ~15 s when the slot is free, 45 s+ under single-slot contention
   (the llama slot runs ~100% utilized at the observed alert rate).
3. Failures cascade: CLI timeout → EMBEDDED FALLBACK (no providers in the
   container config) → double failure, audit row error.

**Fixes applied:**
- `~/.openclaw-wazuh/openclaw.json`: soc-narrator/replier/triage/incident-reviewer
  agent models repointed dead-minimax → `GPU host/gemma-4-31b-it-q3km`, and a
  `models.providers.GPU host` entry added (`http://192.0.2.70:15108/v1`) so the
  embedded fallback has a working provider too. Backup:
  `openclaw.json.bak-laya-20260926`. Ownership restored to the container uid.
- `soc_decision.py` default `timeout` 30 → **90 s** (bind-mounted live; takes
  effect next alert; measured turns 15–18 s free / up to ~45 s contended).

**Measured post-fix:** 7/7 decisions ok (100%), p50 18.2 s, p90 18.4 s, zero
errors — vs 1.3% success pre-fix. Continue monitoring via the audit log;
the nightly agreement job now has a live LLM verdict stream to compare the
laya shadow against.

**Still open (the real ceiling):** the llama slot is ~100% utilized by
decision turns alone (~41/h × ~15–18 s) — any second consumer (narrator,
emails, my test turns) queues it. Structural fixes in order of ambition:
(a) the laya decision path (deterministic severity + 3 typed questions,
~0.9 s, no gemma) behind an env flag for soc_decision; (b) llama `--parallel`
(or a second small model) after a VRAM check; (c) trimming the control host
soc-triage agent context if it proves bloated like edge host's. Not done tonight.

## Cleanup + GPU host-direct + parallel (2026-09-26 20:3x-20:4x)

**Providers repointed — every LLM endpoint now hits GPU host directly:**
- control host SOC gateway: `127.0.0.1:15108/v1` → **`http://100.64.0.61:21402/v1`**
- edge host main openclaw: same repoint (was via control host proxy)
- wazuh instance: same (was via control host proxy)
- The soc-control proxy (:15108) remains ONLY for the power panel/watchdog/health
  — it is no longer in the LLM data path. Backups: `*.bak-gpudirect-20260926`.

**llama --parallel 2:** GPU host unit edited (`--parallel 1` → `2`; total ctx
unchanged 131072 → **65,536/slot**; KV cost unchanged). Verified: `n_slots = 2,
n_ctx_slot = 65536`, health ok, VRAM 15.62+15.58 / 16.31 GB. Also cleared the
stuck single-slot request that had been pinning llama for hours. Backup unit:
`soc-llama-31b.service.bak-parallel-20260926`.

**Agent session cleanup (backups in `/home/operator/backups/laya-cleanup-20260926/`):**
- edge host `soc-triage` agent: **400 MB dead state removed** (unused since option
  B; archived 108 MB tar) + edge host gateway restarted.
- control host SOC gateway: `soc-narrator` (222 MB) + `soc-triage` (142 MB) agent
  state archived + reset with the gateway stopped; agents recreated fresh
  (244 KB / 540 KB). Workspaces/IDENTITY files untouched.
- edge host `~/.openclaw-soc/agents/soc-triage` (another 142 MB stale copy) also
  archived before the control host work.

**Post-reset state:** decisions resumed (1 ok at 20:42 after a cold-cache error
at 20:40). First turns run ~64 s (cold LCP cache after the llama restart — the
old agent's warm prefix cache reset too); expect acceleration as the cache
re-warms. Alert stream paused ~20:39–20:45 (fleet quiet — bursty by design).
Watchdog: UNCHANGED. Decision/ingest paths verified alive end-to-end.
