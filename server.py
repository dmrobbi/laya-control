#!/usr/bin/env python3
"""SOC control + LLM proxy: owns control host:15108.
- /            -> power control page (ON/OFF whole SOC stack) + usage metrics
- /power/on    -> GPU host llama 31B up + soc gateway up
- /power/off   -> soc gateway down + GPU host llama 31B down
- /status      -> JSON component + usage status
- everything else -> transparent proxy to GPU host llama-server :21402 (SSE-streaming safe)
"""
import http.server, socketserver, http.client, json, subprocess, os, threading, time

UP_HOST, UP_PORT = "100.64.0.61", 21402
STATE = "/home/operator/.openclaw-soc/soc-power"
HOP = {"connection", "keep-alive", "transfer-encoding", "upgrade",
       "proxy-authenticate", "proxy-authorization", "te", "trailer"}

_sh_lock = threading.Lock()

def sh(cmd, timeout=90):
    with _sh_lock:
        return subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)

def GPU host(script, timeout=30):
    r = sh('ssh -o BatchMode=yes -o ConnectTimeout=8 GPU host "%s"' % script.replace('"', '\\"'), timeout)
    return r.stdout

def power():
    try:
        return open(STATE).read().strip() or "on"
    except Exception:
        return "on"

def llama_health():
    try:
        c = http.client.HTTPConnection(UP_HOST, UP_PORT, timeout=6)
        c.request("GET", "/health")
        r = c.getresponse()
        r.read()
        c.close()
        return r.status
    except Exception:
        return 0

def gateway():
    return sh("systemctl --user is-active openclaw-gateway-soc.service").stdout.strip()

def port_18790():
    return "active" if "18790" in sh("ss -tln").stdout else "down"

def llama_up():
    if llama_health() == 200:
        return "up"
    r = sh('ssh -o BatchMode=yes -o ConnectTimeout=8 GPU host "systemctl --user is-active soc-llama-31b.service"')
    return "starting" if r.stdout.strip() in ("activating", "active") else "down"

def do_on():
    r1 = sh('ssh -o BatchMode=yes -o ConnectTimeout=8 GPU host "systemctl --user start soc-llama-31b.service"', timeout=60)
    for _ in range(24):
        if llama_health() == 200:
            break
        time.sleep(5)
    # reset-failed first: a prior clean stop that timed out in systemd leaves the
    # unit in 'failed' (exit-code), and 'start' would no-op on a failed unit
    sh("systemctl --user reset-failed openclaw-gateway-soc.service", timeout=10)
    r2 = sh("systemctl --user start openclaw-gateway-soc.service", timeout=60)
    return {"llama": llama_health(), "gateway": gateway(), "gateway_start_err": (r2.stderr or "")[:200], "ssh_err": (r1.stderr or "")[:200]}

def do_off():
    r2 = sh("systemctl --user stop openclaw-gateway-soc.service", timeout=60)
    # NOTE: llama stop ssh CAN time out (llama.cpp stop takes long); state is
    # written by the caller either way — /status reports true llama health.
    r1 = sh('ssh -o BatchMode=yes -o ConnectTimeout=8 GPU host "systemctl --user stop soc-llama-31b.service"', timeout=60)
    return {"gateway": gateway(), "llama": llama_health(), "ssh_err": (r1.stderr or "")[:200]}

def cpu_pct(host_script):
    # two /proc/stat samples, idle-delta
    out = GPU host(host_script)
    try:
        vals = [l for l in out.strip().splitlines() if l.startswith("CPUSAMPLE ")]
        a = vals[0].split()[1:]
        b = vals[1].split()[1:]
        ia = sum(int(x) for x in a)
        ib = sum(int(x) for x in b)
        idlea = int(a[3]) + int(a[4]) if len(a) > 3 else int(a[3])
        idleb = int(b[3]) + int(b[4]) if len(b) > 4 else int(b[3])
        tot = ib - ia
        idl = idleb - idlea
        return round(100 * (1 - idl / tot), 1) if tot > 0 else None
    except Exception:
        return None

def ram_of(free_out):
    try:
        for line in free_out_lines:
            pass
    except Exception:
        pass

def parse_free(text):
    # free -b: line 'Mem:' -> total used free ... available
    mem = None
    for line in text.splitlines():
        if line.startswith("Mem:"):
            parts = line.split()
            mem = {"total_g": round(int(parts[1]) / 1e9, 1),
                   "used_g": round(int(parts[2]) / 1e9, 1),
                   "avail_g": round(int(parts[6]) / 1e9, 1)}
    return mem

def parse_df(text, mount):
    for line in text.splitlines():
        p = line.split()
        if len(p) >= 6 and p[5] == mount:
            return {"used_g": round(int(p[2]) / 1e9, 1),
                    "total_g": round(int(p[1]) / 1e9, 1),
                    "pct": p[4]}
    return None

GPU HOST_SCRIPT = r'''
nvidia-smi --query-gpu=power.draw,utilization.gpu,memory.used,memory.total --format=csv,noheader,nounits | sed "s/^/GPU /"
echo CPU_A $(awk '{print $2,$3,$4,$5,$6,$7,$8}' /proc/stat | head -1)
sleep 0.4
echo CPU_B $(awk '{print $2,$3,$4,$5,$6,$7,$8}' /proc/stat | head -1)
free -b | head -2
df -B1 / | tail -1
echo TOKENS_START
curl -s -m 5 localhost:21402/metrics | grep -E '^llamacpp:(prompt_tokens_total|tokens_predicted_total|prompt_seconds_total|tokens_predicted_seconds_total)' | head -8
'''

def llama_metrics():
    out = GPU host(GPU HOST_SCRIPT)
    gpus, tokens, ram, disk, cpup = [], {}, None, None, None
    mode = None
    for line in out.splitlines():
        if line.startswith("GPU "):
            p = [x.strip() for x in line[4:].split(",")]
            if len(p) == 4:
                gpus.append({"power_w": p[0], "util_pct": p[1],
                             "vram_used_g": round(float(p[2]) / 1024, 1),
                             "vram_total_g": round(float(p[3]) / 1024, 1)})
        elif line.startswith("CPU_A "):
            cpu_a = line[6:]
        elif line.startswith("CPU_B "):
            cpu_b = line[6:]
        elif line.startswith("TOKENS_START"):
            mode = "tok"
        elif mode == "tok" and line.startswith("llamacpp:"):
            p = line.split()
            if len(p) >= 2:
                tokens[p[0].split(":", 1)[1]] = p[1]
        elif line.startswith("Mem:"):
            p = line.split()
            mem = {"total_g": round(int(p[1]) / 1e9, 1),
                   "used_g": round(int(p[2]) / 1e9, 1),
                   "avail_g": round(int(p[6]) / 1e9, 1)}
        elif "/" in line and line.split()[-1] == "/":
            g = line.split()
            if len(g) >= 6:
                disk = {"used_g": round(int(g[2]) / 1e9, 1),
                        "total_g": round(int(g[1]) / 1e9, 1), "pct": g[4]}
    try:
        a = [int(x) for x in cpu_a.split()]
        b = [int(x) for x in cpu_b.split()]
        tot = sum(b) - sum(a)
        idl = (b[3] + (b[4] if len(b) > 4 else 0)) - (a[3] + (a[4] if len(a) > 4 else 0))
        cpu = round(100 * (1 - idl / tot), 1) if tot > 0 else None
    except Exception:
        cpu = None
    return {"gpus": gpus, "cpu_pct": cpu, "ram": mem, "disk": disk, "tokens": tokens}

def local_cpu_pct():
    a = open("/proc/stat").readline().split()[1:]
    time.sleep(0.4)
    b = open("/proc/stat").readline().split()[1:]
    try:
        va, vb = [int(x) for x in a], [int(x) for x in b]
        tot = sum(vb) - sum(va)
        idl = (vb[3] + (vb[4] if len(vb) > 4 else 0)) - (va[3] + (va[4] if len(va) > 4 else 0))
        return round(100 * (1 - idl / tot), 1) if tot > 0 else None
    except Exception:
        return None

def status():
    g = llama_metrics()
    return {
        "power": power(),
        "llama_health": llama_health(),
        "gateway": gateway(),
        "port_18790": port_18790(),
        "GPU host": {"gpus": g.get("gpus"), "cpu_pct": g.get("cpu_pct"),
                 "ram": g.get("ram"), "disk": g.get("disk")},
        "tokens": g.get("tokens"),
        "control host": {
            "cpu_pct": local_cpu_pct(),
            "mem": parse_free(sh("free -b | head -2").stdout),
            "disk": parse_df(sh("df -B1 /").stdout, "/"),
        },
    }

PAGE = """<!doctype html><html><head><meta charset=utf-8><title>SOC power</title>
<style>body{font-family:system-ui;background:#111;color:#ddd;max-width:760px;margin:34px auto;padding:0 16px;font-size:14px}
button{font-size:17px;padding:11px 28px;margin:6px 6px 12px 0;border-radius:10px;border:0;cursor:pointer}
.on{background:#1b7f37;color:#fff}.off{background:#a32424;color:#fff}
h3{margin:16px 0 6px;color:#8fc7ff;font-size:14px;text-transform:uppercase;letter-spacing:.5px}
table{width:100%%;border-collapse:collapse}td,th{padding:4px 8px;border-bottom:1px solid #262626;text-align:left}
td.v{font-family:ui-monospace,monospace;color:#9fd89f}pre{background:#1b1b1b;padding:12px;border-radius:8px;white-space:pre-wrap;font-size:12px;max-height:260px;overflow:auto}
.dot{display:inline-block;width:9px;height:9px;border-radius:50%%;margin-right:6px}
.g{background:#2ecc5e}.r{background:#e74c3c}.y{background:#f1c40f}</style></head>
<body><h2>🦞 SOC stack power</h2>
<p style="color:#888;margin:4px 0">llama.cpp GPU host:21402 (gemma-4-31b) · bridge/proxy · openclaw-gateway-soc :18790</p>
<button class="on" onclick="act('on')">⏻ TURN ON</button>
<button class="off" onclick="act('off')">⏼ TURN OFF</button>
<div id="p">…</div>
<h3>status</h3><pre id="s">loading…</pre>
<script>
function dot(v,good){return '<span class="dot '+((v==200||v=='active'||v=='on'||v=='up')?'g':'r')+'"></span>'}
async function act(v){var el=document.getElementById('s');el.textContent='working… (cold load can take up to ~1 min)';
try{var r=await fetch('/power/'+v,{method:'POST'});el.textContent=await r.text();load();}catch(e){el.textContent=''+e;}}
async function load(msg){
try{var r=await fetch('/status');var j=await r.json();
var h=function(s){return (s==200||s=='active'||s=='up')?'<span class="dot g"></span>':'<span class="dot r"></span>'};
var el=document.getElementById('p');
var rows='';
rows+='<table>';
rows+='<tr><th>component</th><th>state</th></tr>';
rows+='<tr><td>power</td><td class="v">'+(j.power||'-')+'</td></tr>';
rows+='<tr><td>llama GPU host:21402 (gemma-4-31b)</td><td class="v">'+h(j.llama_health)+' health '+j.llama_health+'</td></tr>';
rows+='<tr><td>soc gateway :18790</td><td class="v">'+h(j.gateway)+' '+j.gateway+'</td></tr>';
rows+='</table>';
var g=(j.GPU host&&j.GPU host.gpus)||[];
if(g.length){rows+='<h3>gpu (GPU host)</h3><table>';
g.forEach(function(x,i){rows+='<tr><td>GPU'+i+'</td><td class="v">power '+x.power_w+' W · util '+x.util_pct+'%% · vram '+x.vram_used_g+' / '+x.vram_total_g+' GB</td></tr>';});
rows+='</table>';}
if(j.tokens){var t=j.tokens;rows+='<h3>tokens (llama.cpp, since server start)</h3><table>';
for(var k in t){rows+='<tr><td>'+k.replace(/llama_/g,'').replace(/_/g,' ')+'</td><td class="v">'+t[k]+'</td></tr>';}
rows+='</table>';}
var t2=(j.control host||{});var g2=(j.GPU host||{});
rows+='<h3>host usage</h3><table>';
if(g2.cpu_pct!==undefined&&g2.cpu_pct!==null)rows+='<tr><td>GPU host cpu</td><td class="v">'+g2.cpu_pct+'%%</td></tr>';
if(g2.ram)rows+='<tr><td>GPU host ram</td><td class="v">'+g2.ram.used_g+' / '+g2.ram.total_g+' GB (avail '+g2.ram.avail_g+')</td></tr>';
if(g2.disk)rows+='<tr><td>GPU host disk /</td><td class="v">'+g2.disk.used_g+' / '+g2.disk.total_g+' GB ('+g2.disk.pct+')</td></tr>';
if(t2.cpu_pct!==undefined&&t2.cpu_pct!==null)rows+='<tr><td>control host cpu</td><td class="v">'+t2.cpu_pct+'%%</td></tr>';
if(t2.mem)rows+='<tr><td>control host ram</td><td class="v">'+t2.mem.used_g+' / '+t2.mem.total_g+' GB (avail '+t2.mem.avail_g+')</td></tr>';
if(t2.disk)rows+='<tr><td>control host disk /</td><td class="v">'+t2.disk.used_g+' / '+t2.disk.total_g+' GB ('+t2.disk.pct+')</td></tr>';
rows+='</table>';
el.innerHTML=rows+(msg?'<p>'+msg+'</p>':'');
}catch(e){document.getElementById('p').textContent=''+e;}}
load();setInterval(()=>load(),8000);
</script></body></html>"""

class H(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="text/html; charset=utf-8"):
        data = body if isinstance(body, bytes) else body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(data)
            self.wfile.flush()
        except Exception:
            pass

    def do_GET(self):
        if self.path.startswith("/power"):
            self._send(405, "use POST")
        elif self.path == "/":
            self._send(200, PAGE)
        elif self.path == "/status":
            try:
                self._send(200, json.dumps(status()), "application/json")
            except Exception as e:
                self._send(500, json.dumps({"error": str(e)}), "application/json")
        else:
            self._proxy()

    def do_POST(self):
        if self.path == "/power/on":
            with open(STATE, "w") as f:
                f.write("on")
            res = do_on()
            self._send(200, "POWER ON result:\n" + json.dumps(res, indent=2))
        elif self.path == "/power/off":
            res = do_off()
            with open(STATE, "w") as f:
                f.write("off")
            self._send(200, "POWER OFF result:\n" + json.dumps(res, indent=2))
        else:
            self._proxy()

    def do_PUT(self): self._proxy()
    def do_OPTIONS(self): self._proxy()
    def do_PATCH(self): self._proxy()

    def do_HEAD(self):
        self._send(200, "")

    def _proxy(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        body = self.rfile.read(length) if length else None
        try:
            c = http.client.HTTPConnection(UP_HOST, UP_PORT, timeout=900)
            hdrs = {k: v for k, v in self.headers.items() if k.lower() not in HOP}
            c.request(self.command, self.path, body=body, headers=hdrs)
            r = c.getresponse()
            self.send_response(r.status)
            for k, v in r.getheaders():
                if k.lower() in HOP or k.lower() == "content-length":
                    continue
                self.send_header(k, v)
            self.send_header("Connection", "close")
            self.end_headers()
            while True:
                chunk = r.read(8192)
                if not chunk:
                    break
                self.wfile.write(chunk)
                self.wfile.flush()
            c.close()
        except Exception as e:
            self._send(502, json.dumps({"error": "soc llama upstream: %s" % e}), "application/json")

class TS(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True

if __name__ == "__main__":
    with open(STATE, "a+") as f:
        pass
    if not open(STATE).read().strip():
        with open(STATE, "w") as f:
            f.write("on")
    TS(("0.0.0.0", 15108), H).serve_forever()