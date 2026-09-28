# laya-control — power panel + LLM proxy for OpenClaw SOC gateways

A dependency-free (python3 stdlib + systemd + ssh) service that:

1. **Owns one HTTP port** (default `:15108`) on the OpenClaw-gateway host and acts as a
   **transparent streaming proxy** in front of a remote `llama.cpp` server
   (`llama-server`) running on a GPU box — so your OpenClaw gateway just points at
   `http://127.0.0.1:15108/v1` like any OpenAI-compatible endpoint.
2. Serves a **power panel** at `/`: buttons to switch the *entire* SOC stack ON/OFF
   (llama.cpp server on the GPU host + the OpenClaw SOC gateway), with live status of
   every component.
3. Exposes **/status** (JSON) with live metrics — GPU power draw / utilization / VRAM,
   host CPU / RAM / disk, and llama.cpp token counters — consumed by the page and by
   an external watchdog (included).

Built for a **two-host split** like:

```
   SOC console / operators
        │
        ▼
openclaw-gateway-soc  (:18790, LAN)
        │  POST /v1/chat/completions   (openai-completions provider)
        ▼
soc-control  (this repo)  http://<gateway-host>:15108
        │  /            → power panel
        │  /power/on|off → systemctl + ssh actions
        │  /v1/*, /health, /metrics → proxied
        ▼
GPU host / GPU host:  llama-server :21402  (gemma-4-31B, 131k ctx, tool calls ✓)
```

Everything is stdlib-only — no pip installs.

## Files

| File | Installs on | Purpose |
|---|---|---|
| `server.py` | control/gateway host | HTTP control panel + streaming proxy to llama.cpp |
| `watchdog.sh` | control/gateway host | health checks; prints `ALERT` / `UNCHANGED` |
| `systemd/soc-control.service` | control/gateway host | runs `server.py`, restart=always |
| `systemd/soc-llama-31b.service` | GPU host | runs `llama-server` for the SOC model |
| `install.sh` | both | role-based installer (`control` / `gpu`) |
| `docs/WORKLOG.md` | — | field log from a real migration (minimax-m3 → llama.cpp), incl. every gotcha |

## Prerequisites

- **GPU host**: NVIDIA GPUs + CUDA build of llama.cpp (`~/llama.cpp/build/bin/llama-server`),
  a GGUF model that supports **tool calling** (verified before wiring — see
  *Gotchas*), `nvidia-smi`, and SSH key auth from the gateway host
  (`ssh <gpuhost> 'true'` must be passwordless).
- **Gateway/control host**: OpenClaw gateway running the SOC agents, python3 ≥ 3.10,
  `ss`, `systemd --user` with **lingering enabled** (`sudo loginctl enable-linger $USER`)
  on *both* hosts so everything survives reboots.
- Firewall: open the control port **only** to your internal/Tailscale ranges, e.g.

  ```bash
  sudo ufw allow from 10.0.0.0/8    to any port 15108
  sudo ufw allow from 100.64.0.0/10 to any port 15108
  sudo ufw allow from 192.168.0.0/16 to any port 15108
  ```

## Configure

All knobs live at the top of `server.py` / in `install.sh`:

| Knob | Default | Meaning |
|---|---|---|
| `UP_HOST` / `UP_PORT` | `100.64.0.61` / `21402` | GPU host + llama-server port |
| `SOC_CONTROL_PORT` | `15108` | the public panel/proxy port |
| `STATE` | `~/.openclaw-soc/soc-power` | ON/OFF state file (also read by watchdog) |
| model id | `gemma-4-31b-it-q3km` | must match the `--alias` your llama-server uses |
| watchdog paths | `/home/operator/.openclaw-soc/…` | state + power files |

## Install

### GPU host (runs llama.cpp)

```bash
sudo loginctl enable-linger "$USER"          # keep user services alive after logout
cp systemd/soc-llama-31b.service ~/.config/systemd/user/
# edit ExecStart -m path / --alias / --ctx-size to match your GGUF + hardware
systemctl --user daemon-reload
systemctl --user enable --now soc-llama-31b.service
curl -fsS localhost:21402/health && echo GPU-READY
```

### Gateway/control host (runs OpenClaw + this panel)

```bash
./install.sh control
curl -fsS localhost:15108/status
```

`install.sh control` installs `soc-control.service` + `watchdog.sh`. If you previously
used a raw `socat` bridge on the same port, disable it first — the control service owns
the port now:

```bash
systemctl --user disable --now soc-llm-bridge.service 2>/dev/null || true
```

## Point your OpenClaw SOC gateway at it

In the SOC gateway's `openclaw.json` (`OPENCLAW_STATE_DIR` instance):

```json
"models": {
  "providers": {
    "GPU host": {
      "baseUrl": "http://127.0.0.1:15108/v1",
      "apiKey": "anything-nonempty",
      "api": "openai-completions",
      "models": [{
        "id": "gemma-4-31b-it-q3km",
        "name": "gemma-4-31b-it-q3km",
        "input": ["text"],
        "cost": { "input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0 },
        "contextWindow": 131072,
        "maxTokens": 8192,
        "reasoning": true,
        "api": "openai-completions"
      }]
    }
  }
},
"agents": { "defaults": { "model": { "primary": "GPU host/gemma-4-31b-it-q3km" } } }
```

…and set each agent's `"model"` to `GPU host/gemma-4-31b-it-q3km` as well (agents with no
model field inherit the default). The gateway hot-reloads config — no restart needed
while it runs; if it's stopped, it picks the file up on next start.

> `"reasoning": true` is correct for thinking models (gemma-4-31B emits
> `reasoning_content` before the answer). Budget `maxTokens` for reasoning + content.

## The power panel

Open `http://<gateway-host>:15108/`:

- **⏻ TURN ON** — starts the llama.cpp unit on the GPU host over SSH, waits until
  `/health` returns 200 (≤2 min cold load), then starts the OpenClaw SOC gateway.
- **⏼ TURN OFF** — stops the SOC gateway first, then the llama.cpp unit. Running turns
  are cancelled; consoles go down with it. The panel itself stays up (it *is* the switch).
- `/status` — JSON: `power`, `llama_health`, `gateway`, `port_18790`,
  `GPU host{gpus:[{power_w,util_pct,vram_used_g,vram_total_g}], cpu_pct, ram, disk}`,
  `tokens{llamacpp:prompt_tokens_total, tokens_predicted_total, …}`, `control host{cpu_pct, mem, disk}`.
- Anything else (`/v1/*`, `/health`, `/metrics`, llama web UI) is proxied to the GPU
  host — SSE/streaming passes through (900 s upstream timeout, chunk-flushed).

## Watchdog (alerts when it's working / not working)

`watchdog.sh` checks: control port `/v1/models` + `/health`, the llama unit state on the
GPU host (tolerates `activating`), the SOC gateway service, port `18790`, and fresh
`status=5xx` lines in the SOC gateway journal (90 s window). It writes state to
`~/.openclaw-soc/watchdog-state` and prints exactly:

- `UNCHANGED` — steady (or intentionally powered off)
- `ALERT: SOC LLM … -> working|BROKEN…` — a transition

Run it from OpenClaw's scheduler so transitions reach you in chat:

```bash
openclaw cron add --name soc-llm-watchdog --every 10m \
  --session isolated --session-key "<your-main-session-key>" \
  --no-deliver --timeout-seconds 150 \
  --message 'Run: bash /home/operator/.openclaw-soc/watchdog.sh
If the output is exactly UNCHANGED, reply with only: NO_REPLY
Otherwise reply with the output plus one line naming the broken/recovered check.'
```

(The session key must be a session whose channel you actually read — e.g. your main
webchat/TUI session. `--no-deliver` lets the reply route through the session itself;
`NO_REPLY` is stripped, so it's silent while everything is healthy.)

Intentional power-downs are **silent**: the watchdog reads the same
`~/.openclaw-soc/soc-power` file the panel writes, so clicking TURN OFF never pages you.

## Field-tested gotchas (from a real migration)

See `docs/WORKLOG.md` for the full story. Short version:

- **Tool calling is a model property, not a server property.** A llama3-8B finetune
  returned `500 … does not match the expected peg-native format` on any
  `tools=[…]` request; gemma-4-31B passed. Verify with a live call — `/v1/models`
  `capabilities:["completion"]` is not authoritative (it lied while tool calls worked).
- **Thinking models** (`reasoning_content`) eat `max_tokens` before any `content` —
  tiny budgets look like "empty replies".
- **Never health-check by completing a chat** from an external watchdog: with a single
  llama.cpp slot it queues behind real turns (minutes at 75k-token contexts) and its
  timeout **cancels the real turn**. Use `/health` + `/metrics` + journal scan instead.
- llama.cpp returns **503** while loading; prompt cache (LCP/LRU slot reuse) makes
  later turns ~16 s instead of minutes.
- Metric names are `llamacpp:*` (colons), e.g. `llamacpp:prompt_tokens_total`.

## Security posture

- llama.cpp binds `0.0.0.0` but the panel+proxy is the only published path; the control
  service should be firewall-restricted to internal ranges (see above). The API is
  unauthenticated by design — do *not* open 15108 to "Anywhere".
- The panel's ON/OFF performs systemctl/ssh actions as your user — keep the port off
  the public internet.
> **Note on anonymization:** internal hostnames are referred to by role (control
> host / edge host / GPU host), real IP addresses have been replaced with
> documentation ranges (RFC 5737 TEST-NET, RFC 6598 CGNAT, last octet preserved),
> and alert-sample IPs/domains are anonymized. Nothing here needs credentials.
