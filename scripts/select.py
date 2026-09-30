"""Sélection locale (0 crédit) avant enrichissement Apollo.
Règles : titres stricts, verticales brûlées exclues, 1 contact / entreprise,
dédoublonnage CONSEIL x TECH, plafond 5 000 au total."""
import csv, glob, json, re, os, unicodedata
from collections import Counter

BASE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(BASE, "raw")
TARGET_TOTAL = 100000  # pas de plafond ici : le plafond 5 000 est appliqué après enrichissement

def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", s).strip()

TITLE_OK = re.compile(r"\b(founder|co-?founder|cofounder|fondateur|co-?fondateur|ceo|chief executive|gerant|president|directeur general|dg|pdg|leader|business leader)\b")
TITLE_KO = re.compile(r"\b(project|community|marketing|account|sales|commercial|coo|cto|cfo|cmo|chro|operations|product manager|engineer manager|assistant|intern|stagiaire|advisor to|board member|investor|business angel|mentor|professor)\b")
# "Professor and CEO" : CEO présent -> on garde ; KO ne s'applique que si aucun titre de direction pur
ORG_KO = re.compile(r"(recrut|recruit|talent|staffing|interim|\brh\b|\bhr\b|human resources|chasseur|headhunt|marketing|agence|agency|\bseo\b|\bsea\b|\bads\b|adwords|growth hack|motion|communication|webmarketing|social media|influence|brand)")

def title_ok(t):
    n = norm(re.sub(r"(?i)\bc\.\s?e\.\s?o\.?", "CEO", t or ""))
    if not TITLE_OK.search(n):
        return False, "titre_hors_liste"
    # rejet si le titre contient un rôle opérationnel non-dirigeant sans CEO/Founder/DG/Président explicite
    strong = re.search(r"\b(founder|co-?founder|cofounder|fondateur|co-?fondateur|ceo|gerant|president|directeur general|pdg)\b", n)
    if TITLE_KO.search(n) and not strong:
        return False, "titre_operationnel"
    if re.search(r"\bcoo\b", n) and not re.search(r"\b(ceo|president|directeur general|gerant|pdg)\b", n):
        return False, "titre_coo"
    return True, ""

PRIO = [r"\b(ceo|pdg|president directeur general)\b", r"\b(fondateur|founder)\b", r"\b(directeur general|gerant|president)\b", r"co-?found|cofound|co-?fondateur"]
def score(t):
    n = norm(t)
    for i, p in enumerate(PRIO):
        if re.search(p, n):
            return i
    return 9

def load(seg):
    rows = []
    for f in sorted(glob.glob(os.path.join(RAW, f"{seg}_p*.jsonl"))):
        for line in open(f, encoding="utf-8"):
            line = line.strip()
            if line:
                r = json.loads(line); r["segment"] = seg; rows.append(r)
    return rows

stats = Counter()
all_rows = {s: load(s) for s in ("CONSEIL", "TECH")}
selected, rejected = {"CONSEIL": [], "TECH": []}, []
seen_ids, seen_orgs = set(), set()
for seg in ("CONSEIL", "TECH"):
    stats[f"{seg}_brut"] = len(all_rows[seg])
    # ordre Apollo (pertinence) conservé, mais on préfère CEO/Founder à l'intérieur d'une même boîte
    by_org = {}
    for r in all_rows[seg]:
        if not re.fullmatch(r"[a-f0-9]{24}", r.get("id", "")):
            stats[f"{seg}_id_invalide"] += 1; rejected.append({**r, "raison": "id_invalide"}); continue
        if r["id"] in seen_ids:
            stats[f"{seg}_doublon_id"] += 1; rejected.append({**r, "raison": "doublon_id"}); continue
        seen_ids.add(r["id"])
        ok, why = title_ok(r.get("title", ""))
        if not ok:
            stats[f"{seg}_{why}"] += 1; rejected.append({**r, "raison": why}); continue
        if ORG_KO.search(norm(r.get("org", ""))):
            stats[f"{seg}_verticale_brulee"] += 1; rejected.append({**r, "raison": "verticale_brulee"}); continue
        by_org.setdefault(norm(r.get("org", "")), []).append(r)
    for org, people in by_org.items():
        people.sort(key=lambda r: score(r.get("title", "")))
        keep, extra = people[0], people[1:]
        for e in extra:
            stats[f"{seg}_doublon_entreprise"] += 1; rejected.append({**e, "raison": "doublon_entreprise"})
        if org in seen_orgs:
            stats[f"{seg}_doublon_inter_segment"] += 1; rejected.append({**keep, "raison": "doublon_inter_segment"}); continue
        seen_orgs.add(org)
        selected[seg].append(keep)
    stats[f"{seg}_eligibles"] = len(selected[seg])

# Répartition 5 000 : moitié/moitié, le surplus d'un segment comble l'autre
c, t = selected["CONSEIL"], selected["TECH"]
half = TARGET_TOTAL // 2
nc = min(len(c), max(half, TARGET_TOTAL - len(t)))
nt = min(len(t), TARGET_TOTAL - nc)
final = {"CONSEIL": c[:nc], "TECH": t[:nt]}
for seg in final:
    stats[f"{seg}_a_enrichir"] = len(final[seg])
    for r in selected[seg][len(final[seg]):]:
        rejected.append({**r, "raison": "hors_quota_5000"})

cols = ["segment", "id", "first_name", "last_name_obf", "title", "org", "page"]
for seg, rows in final.items():
    with open(os.path.join(BASE, f"A_ENRICHIR_{seg}.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore"); w.writeheader(); w.writerows(rows)
with open(os.path.join(BASE, "REJETS_SELECTION.csv"), "w", newline="", encoding="utf-8") as fh:
    w = csv.DictWriter(fh, fieldnames=cols + ["raison"], extrasaction="ignore"); w.writeheader(); w.writerows(rejected)
json.dump(stats, open(os.path.join(BASE, "stats_selection.json"), "w"), indent=1)
for k in sorted(stats):
    print(f"{k:40s} {stats[k]}")
print("TOTAL_A_ENRICHIR", sum(len(v) for v in final.values()))
