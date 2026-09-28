#!/bin/bash
ST=/home/operator/.openclaw-soc/watchdog-state
PWR=$(cat /home/operator/.openclaw-soc/soc-power 2>/dev/null || echo on)

if [ "$PWR" = "off" ]; then
  last=$(cat "$ST" 2>/dev/null || echo unknown)
  if [ "$last" = "off (operator)" ]; then
    echo "UNCHANGED"
  else
    echo "off (operator)" > "$ST"
    echo "UNCHANGED"   # intentional operator power-down: page already confirmed it
  fi
  exit 0
fi

ok=1; why=""
m=$(curl -s -o /dev/null -w '%{http_code}' -m 10 http://127.0.0.1:15108/v1/models 2>/dev/null)
[ "$m" = "200" ] || { ok=0; why="$why llama-endpoint($m)"; }
h=$(curl -s -o /dev/null -w '%{http_code}' -m 10 http://127.0.0.1:15108/health 2>/dev/null)
lu=$(ssh -o BatchMode=yes -o ConnectTimeout=8 GPU host 'systemctl --user is-active soc-llama-31b.service' 2>/dev/null)
if [ "$h" = "200" ]; then
  :
elif [ "$lu" = "active" ] || [ "$lu" = "activating" ]; then
  :  # model (re)loading — not broken
else
  ok=0; why="$why llama-model-health($h/unit=$lu)"
fi
systemctl --user is-active --quiet openclaw-gateway-soc.service 2>/dev/null || { ok=0; why="$why soc-gateway-inactive"; }
ss -tln 2>/dev/null | grep -q ':18790' || { ok=0; why="$why soc-port-18790-closed"; }
fails=$(journalctl --user -u openclaw-gateway-soc.service --since "-90 sec" --no-pager 2>/dev/null | grep -c 'model-fetch.*status=5')
[ "$fails" = "0" ] || { ok=0; why="$why $fails-failed-soc-fetches"; }

# --- laya-serve (SOC decision servers, independent of soc-power) ---
lm=$(curl -s -o /dev/null -w '%{http_code}' -m 8 http://127.0.0.1:8099/health 2>/dev/null)
[ "$lm" = "200" ] || { ok=0; why="$why laya-control host($lm)"; }
lt=$(ssh -o BatchMode=yes -o ConnectTimeout=8 edge host 'curl -s -o /dev/null -w %{http_code} -m 8 http://127.0.0.1:8099/health' 2>/dev/null)
[ "$lt" = "200" ] || { ok=0; why="$why laya-edge host($lt)"; }
# laya shadow freshness — the ingest stream feeds ~1 row/3min; a stale log
# means the shadow hook or laya-serve on edge host stopped recording.
sm=$(ssh -o BatchMode=yes -o ConnectTimeout=8 edge host 'stat -c %Y /opt/soc-openclaw/data/laya-shadow.jsonl 2>/dev/null' 2>/dev/null)
now=$(date +%s)
if [ -n "$sm" ] && [ "$sm" -gt 0 ] 2>/dev/null && [ $((now - sm)) -gt 21600 ]; then
  ok=0; why="$why laya-shadow-stale($(( (now - sm) / 3600 ))h)"
fi

if [ "$ok" = "1" ]; then new="working"; else new="BROKEN:$why"; fi
last=$(cat "$ST" 2>/dev/null || echo unknown)
printf '%s' "$new" > "$ST"
if [ "$new" = "$last" ]; then
  echo "UNCHANGED"
else
  echo "ALERT: SOC LLM (gemma-4-31b on GPU host via control host:15108) -> $new (was: $last). $why"
fi
