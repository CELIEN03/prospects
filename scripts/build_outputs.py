"""Construit les CSV de sortie à partir des réponses Apollo bulk_match.
Sorties (dans OUT) :
  CAMPAGNE-NOV-<SEG>-POUR-MV.csv              -> à uploader dans MillionVerifier
  CAMPAGNE-NOV-<SEG>-REPECHAGE-FULLENRICH.csv -> sans email vérifié, parqué
  APOLLO-EXPORT-NOV-<SEG>.csv                 -> format export Apollo, pour pipeline_prospects.py clean
  CAMPAGNE-NOV-REJETS-POST-ENRICHISSEMENT.csv -> tout ce qui a été retiré, avec la raison
  RECAP-NOV.csv                               -> compteurs
"""
import csv, glob, json, os, re, sys, unicodedata
from collections import Counter

BASE = "/tmp/claude-0/-home-user-prospects/b7675362-c672-5335-bd2c-4d9d4f063fef/scratchpad"
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(BASE, "out")
TARGET_TOTAL = 5000
os.makedirs(OUT, exist_ok=True)

def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", s).strip()

ROMANDE = {"geneva", "geneve", "lausanne", "neuchatel", "fribourg", "freiburg"}
ROMANDE_CANTONS = {"geneva", "geneve", "vaud", "neuchatel", "fribourg", "freiburg"}
OK_COUNTRIES = {"france", "belgium", "luxembourg"}
DOMAIN_KO = re.compile(r"(recrut|recruit|talent|executive-?search|staffing|interim|headhunt|chasseur|marketing|agence|agency|seo|adwords|growth|motion|social|influence|communication)")
ORG_KO = re.compile(r"(recrut|recruit|talent|staffing|interim|\brh\b|\bhr\b|human resources|chasseur|headhunt|executive search|marketing|agence|agency|\bseo\b|\bsea\b|\bads\b|adwords|growth hack|motion|communication|webmarketing|social media|influence)")

INDUSTRY_OK = {
    "CONSEIL": {"management consulting", "information technology & services", "computer software", "internet",
                "outsourcing/offshoring", "program development"},
    "TECH": {"information technology & services", "computer software", "internet", "computer & network security",
             "computer networking", "telecommunications", "computer hardware", "management consulting",
             "outsourcing/offshoring", "program development"},
}

LEGAL = r"(s\.?a\.?s\.?u?|s\.?a\.?r\.?l\.?|sàrl|sarl|eurl|sasu|sas|sa|srl|sprl|bv|bvba|nv|gmbh|ag|ltd|limited|inc|llc|scop|sci|group|groupe)"
EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿️​‌‍⁠﻿]")
def clean_company(name):
    n = EMOJI.sub("", name or "").strip()
    # baseline : tout ce qui suit un séparateur
    n = re.split(r"\s+[|–—\-:•·]\s+|\s*\|\s*|,\s+", n)[0].strip()
    n = re.sub(r"\s*\(.*?\)\s*", " ", n).strip()
    # suffixes juridiques (répétés)
    for _ in range(2):
        n = re.sub(rf"[\s,.-]+{LEGAL}\.?$", "", n, flags=re.I).strip()
    # ALL-CAPS -> Title case ; on garde les sigles (mot seul <=4 lettres, ou mots <=3 lettres)
    letters = re.sub(r"[^A-Za-zÀ-ÿ]", "", n)
    words = n.split()
    if letters.isupper() and not (len(words) == 1 and len(letters) <= 4):
        def fix(w):
            wl = re.sub(r"[^A-Za-zÀ-ÿ]", "", w)
            if len(wl) <= 3 and len(words) > 1:
                return w
            return "-".join(p[:1].upper() + p[1:].lower() for p in w.split("-"))
        n = " ".join(fix(w) for w in words)
    n = re.sub(r"\s{2,}", " ", n).strip(" -,.&")
    return n or (name or "").strip()

def title_case_name(s):
    s = (s or "").strip()
    if s.isupper() or s.islower():
        return "-".join(" ".join(w[:1].upper() + w[1:].lower() for w in p.split(" ")) for p in s.split("-"))
    return s

# ------------------------------------------------------------------ chargement
seg_of = {}
for f in glob.glob(os.path.join(BASE, "batches", "*.json")):
    for r in json.load(open(f)):
        seg_of[r["id"]] = r["segment"]
for seg in ("CONSEIL", "TECH"):
    p = os.path.join(BASE, f"A_ENRICHIR_{seg}.csv")
    if os.path.exists(p):
        for r in csv.DictReader(open(p, encoding="utf-8")):
            seg_of.setdefault(r["id"], seg)

stats = Counter()
people, seen = [], set()
for f in sorted(glob.glob(os.path.join(BASE, "enriched", "*.json"))):
    d = json.load(open(f))
    if isinstance(d, list):  # enveloppe MCP [{"type":"text","text":"{...}"}]
        d = json.loads("".join(x.get("text", "") for x in d if isinstance(x, dict)))
    stats["credits_consommes_enrichissement"] += int(d.get("credits_consumed") or 0)
    for m in d.get("matches") or []:
        if not m or m.get("id") in seen:
            continue
        seen.add(m["id"]); people.append(m)
stats["fiches_enrichies"] = len(people)

rej, repechage, keep = [], {"CONSEIL": [], "TECH": []}, {"CONSEIL": [], "TECH": []}
emails, orgs = set(), set()
for m in people:
    seg = seg_of.get(m["id"], "CONSEIL")
    o = m.get("organization") or {}
    country, city = norm(m.get("country")), norm(m.get("city"))
    email = (m.get("email") or "").strip().lower()
    website = o.get("website_url") or ""
    dom = norm(o.get("primary_domain") or re.sub(r"^https?://(www\.)?", "", website))
    row = {
        "segment": seg, "apollo_id": m["id"], "email": email,
        "first_name": title_case_name(m.get("first_name")), "last_name": title_case_name(m.get("last_name")),
        "company_name": clean_company(o.get("name") or ""), "company_name_apollo": o.get("name") or "",
        "website": website, "linkedin_url": m.get("linkedin_url") or "", "title": m.get("title") or "",
        "city": m.get("city") or "", "country": m.get("country") or "", "email_status": m.get("email_status") or "",
        "employees": o.get("estimated_num_employees") or "", "industry": o.get("industry") or "", "org_id": o.get("id") or m.get("organization_id") or "",
    }
    def reject(why):
        stats[f"{seg}_retire_{why}"] += 1; rej.append({**row, "raison": why})
    if "canada" in country or "quebec" in norm(m.get("state")):
        reject("canada"); continue
    if country == "switzerland":
        if not (norm(m.get("state")) in ROMANDE_CANTONS or any(c in city for c in ROMANDE)):
            reject("suisse_hors_romandie"); continue
    elif country not in OK_COUNTRIES:
        reject("hors_zone"); continue
    ind = (o.get("industry") or "").strip().lower()
    if ind and ind not in INDUSTRY_OK[seg]:
        reject("secteur_hors_cible"); continue
    if ORG_KO.search(norm(o.get("name"))) or DOMAIN_KO.search(dom):
        reject("verticale_brulee"); continue
    if re.search(r"(marketing|contact|info|admin|team|sales|support|hello|direction)", norm(row["first_name"])) or not row["first_name"]:
        reject("prenom_invalide"); continue
    if not email or row["email_status"] != "verified":
        stats[f"{seg}_sans_email_verifie"] += 1; repechage[seg].append(row); continue
    okey = row["org_id"] or norm(row["company_name"])
    if okey in orgs:
        reject("doublon_entreprise"); continue
    if email in emails:
        reject("doublon_email"); continue
    orgs.add(okey); emails.add(email)
    keep[seg].append(row)

# plafond 5 000 (moitié/moitié, le surplus d'un segment comble l'autre)
c, t = keep["CONSEIL"], keep["TECH"]
nc = min(len(c), max(TARGET_TOTAL // 2, TARGET_TOTAL - len(t)))
nt = min(len(t), TARGET_TOTAL - nc)
for seg, n in (("CONSEIL", nc), ("TECH", nt)):
    for r in keep[seg][n:]:
        rej.append({**r, "raison": "hors_quota_5000"}); stats[f"{seg}_retire_hors_quota_5000"] += 1
    keep[seg] = keep[seg][:n]

MV_COLS = ["email", "first_name", "last_name", "company_name", "website", "linkedin_url", "title", "city", "country"]
APOLLO_COLS = ["First Name", "Last Name", "Title", "Company", "Company Name for Emails", "Email", "Email Status",
               "Person Linkedin Url", "Website", "City", "Country", "# Employees", "Apollo Contact Id"]
def w(path, cols, rows, mapper=None):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        wr = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore"); wr.writeheader()
        for r in rows:
            wr.writerow(mapper(r) if mapper else r)
to_apollo = lambda r: {"First Name": r["first_name"], "Last Name": r["last_name"], "Title": r["title"],
    "Company": r["company_name_apollo"], "Company Name for Emails": r["company_name"], "Email": r["email"],
    "Email Status": r["email_status"], "Person Linkedin Url": r["linkedin_url"], "Website": r["website"],
    "City": r["city"], "Country": r["country"], "# Employees": r["employees"], "Apollo Contact Id": r["apollo_id"]}
for seg in ("CONSEIL", "TECH"):
    stats[f"{seg}_POUR_MV"] = len(keep[seg]); stats[f"{seg}_REPECHAGE"] = len(repechage[seg])
    w(os.path.join(OUT, f"CAMPAGNE-NOV-{seg}-POUR-MV.csv"), MV_COLS, keep[seg])
    w(os.path.join(OUT, f"CAMPAGNE-NOV-{seg}-REPECHAGE-FULLENRICH.csv"), MV_COLS + ["email_status"], repechage[seg])
    w(os.path.join(OUT, f"APOLLO-EXPORT-NOV-{seg}.csv"), APOLLO_COLS, keep[seg] + repechage[seg], to_apollo)
w(os.path.join(OUT, "CAMPAGNE-NOV-REJETS-POST-ENRICHISSEMENT.csv"),
  ["segment", "raison"] + MV_COLS + ["company_name_apollo", "email_status", "apollo_id"], rej)
stats["TOTAL_POUR_MV"] = stats["CONSEIL_POUR_MV"] + stats["TECH_POUR_MV"]
with open(os.path.join(OUT, "RECAP-NOV.csv"), "w", newline="", encoding="utf-8") as fh:
    wr = csv.writer(fh); wr.writerow(["indicateur", "valeur"])
    for k in sorted(stats): wr.writerow([k, stats[k]])
for k in sorted(stats):
    print(f"{k:45s} {stats[k]}")
