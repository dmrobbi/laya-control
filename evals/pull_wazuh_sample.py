#!/usr/bin/env python3
"""Pull a stratified Wazuh alert sample from the edge host indexer (Phase 1).

Run ON edge host:  python3 pull_wazuh_sample.py [per_level=60] [out=/tmp/wazuh-sample.json]
Reads creds from /home/operator/.openclaw/soc/secrets/wazuh-indexer.env (no output of secrets).
"""
import base64
import collections
import json
import ssl
import sys
import urllib.request

URL = "https://127.0.0.1:9200/wazuh-alerts-*/_search"
PER_LEVEL = int(sys.argv[1]) if len(sys.argv) > 1 else 60
OUT = sys.argv[2] if len(sys.argv) > 2 else "/tmp/wazuh-sample.json"

env = {}
for line in open("/home/operator/.openclaw/soc/secrets/wazuh-indexer.env"):
    k, _, v = line.strip().partition("=")
    if k:
        env[k] = v
auth = "Basic " + base64.b64encode(("admin:" + env["WAZUH_INDEXER_PASSWORD"]).encode()).decode()
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

def q(body):
    req = urllib.request.Request(URL, data=json.dumps(body).encode(),
                                 headers={"content-type": "application/json", "Authorization": auth},
                                 method="POST")
    return json.load(urllib.request.urlopen(req, timeout=30, context=ctx))

dist = q({"size": 0, "aggs": {"levels": {"terms": {"field": "rule.level", "size": 20}}}})
print("level distribution:", [(b["key"], b["doc_count"]) for b in dist["aggregations"]["levels"]["buckets"]])
out = []
for b in dist["aggregations"]["levels"]["buckets"]:
    lvl = b["key"]
    if lvl < 3:
        continue
    r = q({"size": PER_LEVEL, "sort": [{"@timestamp": "desc"}], "query": {"term": {"rule.level": lvl}},
           "_source": ["@timestamp", "rule.level", "rule.id", "rule.description", "agent.name",
                       "data.srcip", "data.src_ip", "decoder.name", "location"]})
    hits = r["hits"]["hits"]
    out.extend(h["_source"] for h in hits)
    print("level", lvl, "pulled", len(hits))
json.dump(out, open(OUT, "w"))
print("total:", len(out), "->", OUT)