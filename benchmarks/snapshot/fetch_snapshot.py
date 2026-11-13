"""Fetch every Snapshot proposal (id, created, space, flagged) from the public hub.
Endpoint: https://hub.snapshot.org/graphql (no API key, rate limit 100 req/60s).
Pagination: keyset on `created` (created_gte last seen, dedupe by id)."""
import json, time, urllib.request, sys
URL="https://hub.snapshot.org/graphql"
Q='''query($t:Int!){ proposals(first:1000, orderBy:"created", orderDirection:asc, where:{created_gte:$t}) { id created flagged space { id } } }'''
def post(t):
    body=json.dumps({"query":Q,"variables":{"t":t}}).encode()
    for a in range(8):
        try:
            r=urllib.request.Request(URL,body,{"content-type":"application/json","user-agent":"void-benchmark"})
            d=json.load(urllib.request.urlopen(r,timeout=60))
            if "errors" in d: raise Exception(d["errors"])
            return d["data"]["proposals"]
        except Exception as e:
            print("retry",a,e,file=sys.stderr); time.sleep(10*(a+1))
    raise SystemExit("failed")
import os
OUT=os.path.join(os.path.dirname(os.path.abspath(__file__)),"snapshot_proposals.jsonl")
seen=set(); t=0; n=0
if os.path.exists(OUT):  # resume
    for l in open(OUT):
        r=json.loads(l); seen.add(r["id"]); t=max(t,r["created"])
out=open(OUT,"a")
while True:
    ps=post(t); new=[p for p in ps if p["id"] not in seen]
    for p in new:
        seen.add(p["id"]); out.write(json.dumps({"id":p["id"],"created":p["created"],"flagged":p.get("flagged"),"space":(p["space"] or {}).get("id")})+"\n")
    n+=1
    if n%20==0: print(n,len(seen),t,flush=True)
    if not ps or not new: break  # stop only when a page brings nothing new
    t=max(p["created"] for p in ps)
    time.sleep(0.65)
out.close(); print("done",len(seen))
