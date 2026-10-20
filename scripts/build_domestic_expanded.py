#!/usr/bin/env python3
"""Build supplemental domestic-season team stats from public 2026/27 match results.
Data provenance: https://github.com/oladeeayo/open-matchday
Only completed domestic league results; missing HT/xG remain null. No invented values.
"""
import csv, io, json, re, unicodedata, urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

BASE="https://raw.githubusercontent.com/oladeeayo/open-matchday/HEAD/"
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"data"/"domestic-expanded.json"
INDEX="LEAGUE_INDEX.md"
SEASON="2627"
def get(path):
    req=urllib.request.Request(BASE+path,headers={"User-Agent":"DocsSoccerWarRoom/1.0"})
    with urllib.request.urlopen(req,timeout=30) as response:
        return response.read().decode("utf-8-sig")
def key(s):
    s=unicodedata.normalize("NFKD",str(s)).encode("ascii","ignore").decode().lower()
    return re.sub(r"[^a-z0-9]","",re.sub(r"\\b(fc|afc|cf|sc)\\b","",s))
def number(v):
    try:return int(v)
    except (ValueError,TypeError):return None
def rate(rows,fn):
    return round(sum(1 for r in rows if fn(r))/len(rows),4) if rows else None
def avg(rows,k):
    vals=[r[k] for r in rows if r.get(k) is not None]
    return round(sum(vals)/len(vals),4) if vals else None
def summary(rows):
    if not rows:return None
    return {"n":len(rows),"scored_05":rate(rows,lambda x:x["gf"]>=1),
        "scored_15":rate(rows,lambda x:x["gf"]>=2),
        "conceded_05":rate(rows,lambda x:x["ga"]>=1),
        "first_half_scored":rate([x for x in rows if x["htgf"] is not None],lambda x:x["htgf"]>=1),
        "goals_for":avg(rows,"gf"),"goals_against":avg(rows,"ga"),
        "xg_for":None,"xg_against":None,"shots_on_target":avg(rows,"sot")}
def main():
    index=get(INDEX)
    folders=re.findall(r"^\\| \\x60([^\\x60]+)\\x60 \\|",index,re.M)
    folders=[x for x in folders if re.match(r"^[A-Z]{2,4}_\\d+_",x) and not x.startswith("UEFA_")]
    result=[]; errors=[]; covered=0
    for folder in folders:
        path=f"data/{folder}/results_{SEASON}.csv"
        try:
            raw=get(path)
            rows=list(csv.DictReader(io.StringIO(raw)))
        except Exception as exc:
            errors.append({"league":folder,"error":str(exc)[:130]})
            continue
        teams=defaultdict(list)
        for r in rows:
            gf,ga=number(r.get("ft_home")),number(r.get("ft_away"))
            if gf is None or ga is None or not r.get("date"):continue
            hh,ha=number(r.get("ht_home")),number(r.get("ht_away"))
            sh,sa=number(r.get("home_target")),number(r.get("away_target"))
            for name,venue,f,a,h,s,opp in [(r["home"],"home",gf,ga,hh,sh,r["away"]),(r["away"],"away",ga,gf,ha,sa,r["home"])]:
                teams[name].append({"date":r["date"],"opponent":opp,"venue":venue,"gf":f,"ga":a,"htgf":h,"sot":s,
                    "scored_05":f>=1,"scored_15":f>=2,"conceded_05":a>=1,
                    "first_half_scored":h>=1 if h is not None else None,
                    "xgf":None,"xga":None})
        if not teams:continue
        covered+=1
        for name,logs in teams.items():
            logs.sort(key=lambda x:x["date"],reverse=True)
            result.append({"name":name,"league":folder,"source":"open-matchday","season":summary(logs),
                "last5":summary(logs[:5]),"last10":summary(logs[:10]),
                "home":summary([x for x in logs if x["venue"]=="home"]),
                "away":summary([x for x in logs if x["venue"]=="away"]),
                "games":logs})
    if covered<10 or len(result)<150:
        raise RuntimeError(f"Insufficient source coverage: {covered} leagues, {len(result)} teams; refusing overwrite")
    OUT.parent.mkdir(parents=True,exist_ok=True)
    payload={"generated_utc":datetime.now(timezone.utc).isoformat(),"season":"2026/27",
        "source":"https://github.com/oladeeayo/open-matchday",
        "coverage_leagues":covered,"coverage_teams":len(result),
        "source_errors":errors,"teams":result,
        "limitations":"Domestic league only. Missing half-time, shots and xG are null. Source names require verified matching."}
    OUT.write_text(json.dumps(payload,ensure_ascii=False,separators=(",",":")),encoding="utf-8")
    print(f"Wrote {len(result)} teams across {covered} domestic leagues; {len(errors)} source files unavailable")
if __name__=="__main__":main()
