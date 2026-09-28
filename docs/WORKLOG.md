# WORKLOG — minimax-m3 → llama.cpp (gemma-4-31B) migration + power panel

Field log of the session that produced this repo, kept so the next operator
doesn't rediscover the same gotchas. Environment: two-host split — OpenClaw
SOC gateway on `control host` (LAN :18790, `OPENCLAW_STATE_DIR=/home/operator/.openclaw-soc`),
llama.cpp on `GPU host` (2×16 GB NVIDIA, 125 GB RAM, CUDA llama.cpp).

## 1. Alert: minimax-m3 burning the Ollama cloud account

Operator saw `minimax-m3` usage on his Ollama dashboard. Investigation chain:

1. **Cron jobs (historical offender).** Two OpenClaw cron jobs
   (`healthcheck:security-audit` daily 08:00, `healthcheck:update-status` Sun 09:00)
   ran isolated agent turns inheriting the then-default `ollama/minimax-m3:cloud`
   — ~18–19k input tokens per run, daily through Aug 18. Dead already (disabled
   Aug 21–22 after Telegram delivery 404s to a gone chat + `model_not_found`).
   → removed, and the `minimax-m3:*` model defs stripped from the gateway config.
2. **Live culprit: a second OpenClaw gateway.** Two `openclaw … gateway` node
   processes existed — the real one (:18789) and `openclaw-gateway-soc.service`
   (:18790, `--bind lan`, 7 days uptime, 7 h 40 min CPU). Its *own* config
   (`~/.openclaw-soc/openclaw.json`) had `"primary": "ollama/minimax-m3:cloud"`.
   Caught the client red-handed: `ss -tnp` → ESTABLISHED connection to
   `127.0.0.1:11434` owned by the SOC gateway node; SOC session files contained
   fresh `model-snapshot` events with `"model":"ollama/minimax-m3:cloud"` written
   minutes earlier. Ollama journal showed the retry cadence: 401 storms + `/api/me`
   re-auth every ~11 s.
3. **Lockdown.** `systemctl --user stop/disable openclaw-gateway-soc.service`
   (wanted-link removed so it can't respawn at boot). Ollama itself was already
   `127.0.0.1`-bound — the calls were all local.

## 2. Workload measurement (why the next model had to fit *this*)

From `~/.openclaw-soc/agents/*/sessions/*.jsonl` (181 sessions, 3,908 turns):
avg **~120k input tokens/turn**, max ~510k, avg **~164 output tokens/turn**,
~470M input tokens total, ~1,680 turns `"trigger":"user"` (operator console — not
cron-driven), 10 sessions active in the last 24 h. Conclusion: prompt processing
dominates, generation is trivial, context window ≥131k matters.

## 3. Model selection on the GPU host (`GPU host`)

2×16 GB NVIDIA, 125 GB RAM, CUDA llama.cpp build, GGUFs already on disk.

- `llama3-8b` finetune (`:21401`, already serving): **fails native tool calls** —
  llama.cpp returned `500 … does not match the expected peg-native format` on any
  `tools=[…]` request. The finetune breaks llama3's tool-call grammar, and OpenClaw's
  agent loop *needs* native tool calls. → unusable for SOC agents.
- `gemma-4-31b-it Q3_K_M` (new server on `:21402`): tool calls verified live
  (`get_severity` returned a proper `tool_calls` payload). → chosen.
- Learned: llama.cpp `/v1/models` advertises `capabilities:["completion"]` even when
  tool calls work. **Don't trust the metadata — fire a live tools request.**
- Learned: a plain-chat health probe with `max_tokens: 8` returns empty
  `content` — gemma-4-31B emits `reasoning_content` (thinking) first and tiny
  budgets die in the reasoning phase.

## 4. Cutover

- Replaced `socat` bridge with `soc-control.service` (this repo) on `control host:15108`
  — same `/v1` contract for the OpenClaw gateway, plus the power panel.
- `~/.openclaw-soc/openclaw.json` (backup kept):
  added provider `GPU host` (`baseUrl http://127.0.0.1:15108/v1`, `api
  openai-completions`, model `gemma-4-31b-it-q3km`, ctx 131072, maxTokens 8192),
  repointed `agents.defaults.model.primary` + every agent, stripped `minimax-m3:cloud`
  and `minimax-m2.7:cloud`.
- `openclaw-gateway-soc.service` re-enabled/started; gateway journal shows real
  model-fetches `status=200` (first at `elapsedMs=501`), and later full SOC turns at
  74–79k ctx completing (16.1 s with prompt-cache hit; 77.7 s cold-ish; decode
  ~10.8 tok/s).

## 5. The power panel + watchdog

- Power state file: `~/.openclaw-soc/soc-power` (`on` / `off`).
- OFF = stop `openclaw-gateway-soc` (gateway first), then stop
  `soc-llama-31b.service` on GPU host over SSH. ON = start llama unit, wait
  `/health`=200 (≤2 min), then start the gateway. The panel itself is never
  stopped — it is the switch.
- Watchdog v1 lesson: **health-checking by completing a chat is harmful**. With a
  single llama.cpp slot the probe queues behind real turns (minutes at 75k ctx) and
  its timeout *cancels the real turn* (seen in llama.cpp logs: `stop: cancel task`).
  v3 checks `/v1/models` + `/health` (instant), the llama unit state over SSH, the
  gateway service, port `18790`, and fresh `status=5xx` lines in the SOC gateway
  journal (90 s window) — no slot disturbance.
- Watchdog is power-state aware: `off` (operator action) is silent; transitions
  to `working` / `BROKEN` alert. Cron: every 10 m, isolated turn routed to the
  operator's session, replying exactly `NO_REPLY` when unchanged.

## 6. Incidents along the way (all resolved)

- Port clash at cutover: the pre-existing `nohup` llama-server still held :21402 →
  `soc-llama-31b.service` restart-looped 4× until the old PID was killed.
  Lesson: kill/verify the old listener *before* `enable --now`, or expect
  `NRestarts` churn.
- 17 stale `status=503` model-fetches alerted once — all inside the 4 s
  model-loading window at cutover; watchdog lookback was tightened 11 m → 90 s.
- Telegram cron delivery 404s: the old healthcheck jobs pointed at a dead Telegram
  chat (`…8318706992`); the jobs were removed rather than rewired.

## Rollback

`~/.openclaw-soc/openclaw.json.bak-pre-GPU host-20260925` (+ `.bak` chain) restores the
minimax-m3 config; `systemctl --user disable --now soc-control.service` frees :15108
for a socat bridge again.

## Laya Phase 2 executed (2026-09-27 ~23:2x UTC — operator said go)

- **Gated flip live**: `LAYA_MODE=shadow -> gated` in `/etc/default/realtime-soc-server`
  + `/etc/default/imap-watcher` (sudo sed + restart). V8 drill first: off -> restart ->
  POST -> no shadow row (count 757) -> gated -> POST -> row with `mode:gated` (758).
- **soc_decision laya path** (soc-openclaw `4ced0025`, Dawn-authored): deterministic
  severity + typed laya questions (`tau_kp=0.65`, `tau_resp=0.70`, auto_remediate
  additionally at the 0.85 threshold); gemma fallback only below the gate (~3% of
  soak traffic). Audit rows: `input_kind=laya_gated_decision`,
  `model=laya-typed-decisions`, `outcome=ok`, real duration.
- **laya-bridge**: docker-bridge-only TCP forwarder `172.19.0.1:8099 -> 127.0.0.1:8099`
  (`scripts/laya_bridge.py` + `systemd/laya-bridge.service`, system unit on edge host;
  resolves the compose gateway at start, Restart=on-failure). Container-side callers
  reach loopback-only laya-serve without LAN exposure.
- **Container env**: LAYA keys appended to the compose env_file
  (`reports-example-soc-mailbox.env`) + the runtime mailbox file
  (`reports-bedimsecurity-mailbox.env`); the wazuh manager was RECREATED
  (`docker compose up -d wazuh.manager` from /home/operator/wazuh-stack) so the daemon-level
  env carries them — every integration/cron process inherits the keys.
- **Verified**: the real wrapper->agentic-soc-send->decide path served laya
  (997-1050 ms decisions, audit `outcome=ok`); ingest shadow rows continue
  with `mode:gated`; rollback = `LAYA_MODE=off` (one env var).
- **Pre-flip gemma state (audit log)**: 65% of decisions 90 s-timeout, ok-rows p50
  21 s degenerate `email@0.90` — the laya path is a quality fix, not only a power one.
- **Open**: organic-traffic soak (overnight quiet — verify at the next burst);
  pre-existing tickets-MCP connection-refused + dispatch `_decision` serialization
  TypeError; the escalate gate-conf >=0.85 bucket (25 soak rows, 0% agreement vs the
  deterministic rule) needs a direction check before primary mode.