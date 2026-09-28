#!/usr/bin/env bash
# laya-control installer — roles: control (gateway host) | gpu (llama.cpp host)
set -euo pipefail

ROLE="${1:-}"
CONTROL_PORT="${SOC_CONTROL_PORT:-15108}"
UP_HOST="${SOC_UPSTREAM_HOST:-100.64.0.61}"   # GPU host (tailnet IP ok)
UP_PORT="${SOC_UPSTREAM_PORT:-21402}"
STATE_DIR="${SOC_STATE_DIR:-$HOME/.openclaw-soc}"
MODEL_GGUF="${SOC_MODEL_GGUF:-$HOME/models/gemma-4-31B-it-Q3_K_M.gguf}"
MODEL_ALIAS="${SOC_MODEL_ALIAS:-gemma-4-31b-it-q3km}"
LLAMA_SERVER="${SOC_LLAMA_SERVER:-$HOME/llama.cpp/build/bin/llama-server}"
CTX="${SOC_CTX:-131072}"

REPO="$(cd "$(dirname "$0")" && pwd)"
UNIT_DIR="${HOME}/.config/systemd/user"

usage() { echo "usage: $0 control|gpu" >&2; exit 2; }
[ "$ROLE" = "control" ] || [ "$ROLE" = "gpu" ] || usage

say() { printf '\033[1;32m==>\033[0m %s\n' "$*"; }

if [ "$ROLE" = "control" ]; then
  say "installing soc-control.service (panel + LLM proxy on :$CONTROL_PORT)"
  mkdir -p "$UNIT_DIR" "$STATE_DIR_HINT" 2>/dev/null || true
  mkdir -p "$(dirname "$STATE")"
  [ -f "$STATE" ] || printf 'on' > "$STATE"

  install -m 644 "$REPO/systemd/soc-control.service" "$UNIT_DIR/"
  install -m 755 "$REPO/server.py" /home/operator/.openclaw-soc/soc-control/server.py 2>/dev/null || {
    mkdir -p "$(dirname "$HOME")/operator/.openclaw-soc/soc-control" 2>/dev/null || true
    mkdir -p "$HOME/.openclaw-soc/soc-control"
    install -m 755 "$REPO/server.py" "$HOME/.openclaw-soc/soc-control/server.py"
  }
  install -m 755 "$REPO/watchdog.sh" "$HOME/.openclaw-soc/watchdog.sh"

  # keep a socat bridge from being started on the same port
  systemctl --user disable --now soc-llm-bridge.service 2>/dev/null || true

  systemctl --user daemon-reload
  systemctl --user enable --now soc-control.service
  sleep 1
  ss -tln | grep -q ":$CONTROL_PORT" && say "panel listening on :$CONTROL_PORT"
  echo "open http://$(hostname):$CONTROL_PORT/ for the power panel"

elif [ "$ROLE" = "gpu" ]; then
  say "installing soc-llama-31b.service (llama-server on :$UP_PORT)"
  command -v nvidia-smi >/dev/null || { echo "nvidia-smi not found — is the driver installed?" >&2; exit 1; }
  [ -x "$LLAMA_SERVER" ] || { echo "llama-server not found at $LLAMA_SERVER" >&2; exit 1; }
  [ -f "$MODEL_GGUF" ] || { echo "model GGUF not found at $MODEL_GGUF" >&2; exit 1; }

  mkdir -p "$UNIT_DIR"
  cat > "$UNIT_DIR/soc-llama-31b.service" <<UNIT
[Unit]
Description=llama-server for OpenClaw SOC (:$UP_PORT)
After=network-online.target

[Service]
ExecStart=$LLAMA_SERVER -m $MODEL_GGUF --alias $MODEL_ALIAS --host 0.0.0.0 --port $UP_PORT \\
  --ctx-size $CTX --parallel 1 --cache-type-k q4_0 --cache-type-v q4_0 \\
  -ngl 999 --flash-attn auto --jinja --metrics
Restart=always
RestartSec=5
Environment=HOME=$HOME

[Install]
WantedBy=default.target
EOF
  systemctl --user daemon-reload
  systemctl --user enable --now soc-llama-31b.service
  say "waiting for /health on :$UP_PORT"
  for _ in $(seq 1 36); do
    [ "$(curl -s -o /dev/null -w '%{http_code}' -m 3 "localhost:$UP_PORT/health" 2>/dev/null)" = "200" ] && { say "GPU READY (health 200)"; exit 0; }
    sleep 5
  done
  echo "llama-server did not become healthy in ~3 min — check: journalctl --user -u soc-llama-31b" >&2
  exit 1
fi

echo "note: for the llama.cpp unit to survive logouts on a headless host:"
echo "  sudo loginctl enable-linger \$USER"