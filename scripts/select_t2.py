"""Sélection 2e niveau (mots-clés sans NAICS) : mêmes filtres que select.py,
en excluant tout id / entreprise déjà présent au 1er niveau. Produit des lots R3_*.json.
Usage : python3 select_t2.py <nb_max_a_enrichir>"""
import csv, glob, json, os, re, sys, unicodedata
BASE = "/tmp/claude-0/-home-user-prospects/b7675362-c672-5335-bd2c-4d9d4f063fef/scratchpad"
src = open(os.path.join(BASE, "select.py"), encoding="utf-8").read()
exec(src[src.index("def norm"):src.index("def load")])  # norm, title_ok, score, ORG_KO

LIMIT = int(sys.argv[1]) if len(sys.argv) > 1 else 10**9
from collections import Counter
stats = Counter()

t1_ids, t1_orgs = set(), set()
for f in glob.glob(os.path.join(BASE, "raw", "*.jsonl")):
    for l in open(f, encoding="utf-8"):
        r = json.loads(l); t1_ids.add(r["id"])
for seg in ("CONSEIL", "TECH"):
    for r in csv.DictReader(open(os.path.join(BASE, f"A_ENRICHIR_{seg}.csv"), encoding="utf-8")):
        t1_orgs.add(norm(r["org"]))
queued = set()
for f in glob.glob(os.path.join(BASE, "batches", "*.json")):
    for r in json.load(open(f)): queued.add(r["id"])

cands, seen_ids, seen_orgs = {"CONSEIL": [], "TECH": []}, set(), set()
for seg in ("CONSEIL", "TECH"):
    by_org = {}
    for f in sorted(glob.glob(os.path.join(BASE, "raw2", f"{seg}_p*.jsonl"))):
        for l in open(f, encoding="utf-8"):
            r = json.loads(l); r["segment"] = seg
            stats[f"{seg}_brut"] += 1
            if not re.fullmatch(r"[a-f0-9]{24}", r.get("id") or ""): stats[f"{seg}_id_invalide"] += 1; continue
            if r["id"] in seen_ids: stats[f"{seg}_doublon_id"] += 1; continue
            seen_ids.add(r["id"])
            if r["id"] in t1_ids or r["id"] in queued: stats[f"{seg}_deja_niveau1"] += 1; continue
            ok, why = title_ok(r.get("title", ""))
            if not ok: stats[f"{seg}_{why}"] += 1; continue
            if ORG_KO.search(norm(r.get("org", ""))): stats[f"{seg}_verticale_brulee"] += 1; continue
            o = norm(r.get("org", ""))
            if o in t1_orgs: stats[f"{seg}_entreprise_deja_niveau1"] += 1; continue
            by_org.setdefault(o, []).append(r)
    for o, people in by_org.items():
        people.sort(key=lambda r: score(r.get("title", "")))
        stats[f"{seg}_doublon_entreprise"] += len(people) - 1
        if o in seen_orgs: stats[f"{seg}_doublon_inter_segment"] += 1; continue
        seen_orgs.add(o); cands[seg].append(people[0])
    stats[f"{seg}_eligibles_niveau2"] = len(cands[seg])

# alternance CONSEIL / TECH pour équilibrer si on plafonne
rows, i = [], 0
while len(rows) < LIMIT and (i < len(cands["CONSEIL"]) or i < len(cands["TECH"])):
    for seg in ("CONSEIL", "TECH"):
        if i < len(cands[seg]) and len(rows) < LIMIT: rows.append(cands[seg][i])
    i += 1
for f in glob.glob(os.path.join(BASE, "batches", "R3_*.json")): os.remove(f)
B = 250
for k in range(0, len(rows), B):
    json.dump([{"id": r["id"], "segment": r["segment"]} for r in rows[k:k+B]],
              open(os.path.join(BASE, "batches", f"R3_{k//B+1:02d}.json"), "w"))
for k in sorted(stats): print(f"{k:40s} {stats[k]}")
print("A_ENRICHIR_NIVEAU2", len(rows), "| lots", (len(rows) + B - 1) // B)
