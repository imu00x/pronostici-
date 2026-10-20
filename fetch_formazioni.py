#!/usr/bin/env python3
"""Stima le formazioni: ultima formazione di ogni squadra meno gli infortunati (API-Football, piano gratuito).
Serve la chiave gratuita nella variabile d'ambiente API_FOOTBALL_KEY. Usa circa 60 richieste al giorno (limite: 100)."""
import json, os, sys, urllib.parse, urllib.request
from datetime import date, datetime, timedelta

API = "https://v3.football.api-sports.io/"
LG = {"I1": 135, "E0": 39, "SP1": 140, "D1": 78, "F1": 61}
PER_STARTER = 0.025
CAP = 0.15


def call(key, path, **p):
    req = urllib.request.Request(API + path + "?" + urllib.parse.urlencode(p), headers={"x-apisports-key": key})
    with urllib.request.urlopen(req, timeout=60) as r:
        j = json.load(r)
    if j.get("errors"):
        raise RuntimeError(str(j["errors"]))
    return j.get("response", [])


def main():
    key = os.environ.get("API_FOOTBALL_KEY")
    if not key:
        print("API_FOOTBALL_KEY assente: formazioni automatiche saltate")
        return
    today = date.today()
    try:
        old = json.load(open("data/formazioni_auto.json", encoding="utf-8"))
    except Exception:
        old = {}
    if old.get("data") == today.isoformat():
        print("formazioni già aggiornate oggi")
        return
    season = today.year if today.month >= 7 else today.year - 1
    squadre = {}
    for div, lid in LG.items():
        try:
            last = call(key, "fixtures", league=lid, season=season, last=10)
            inj = call(key, "injuries", league=lid, season=season)
            recent = datetime.fromisoformat((today - timedelta(days=2)).isoformat())
            ass = {}
            for i in inj:
                try:
                    if datetime.fromisoformat(i["fixture"]["date"][:10]) < recent:
                        continue
                except Exception:
                    continue
                tid, pid = i["team"]["id"], i["player"]["id"]
                peso = 0.5 if "quest" in (i["player"].get("type") or "").lower() else 1.0
                cur = ass.setdefault(tid, {}).get(pid)
                if not cur or peso > cur[1]:
                    ass[tid][pid] = (i["player"]["name"], peso)
            seen = set()
            for fx in sorted(last, key=lambda f: f["fixture"]["date"], reverse=True):
                tids = [fx["teams"]["home"]["id"], fx["teams"]["away"]["id"]]
                if all(t in seen for t in tids):
                    continue
                for ln in call(key, "fixtures/lineups", fixture=fx["fixture"]["id"]):
                    tid = ln["team"]["id"]
                    if tid in seen:
                        continue
                    seen.add(tid)
                    xi = [p["player"] for p in ln.get("startXI", [])]
                    inj_t = ass.get(tid, {})
                    out = [(p["name"], inj_t[p["id"]][1]) for p in xi if p["id"] in inj_t]
                    xi_ids = {p["id"] for p in xi}
                    altri = [v[0] for k, v in inj_t.items() if k not in xi_ids]
                    imp = -min(CAP, PER_STARTER * sum(w for _, w in out))
                    squadre[ln["team"]["name"]] = {
                        "div": div, "formazione": [p["name"] for p in xi],
                        "assenti": [n + (" (dubbio)" if w < 1 else "") for n, w in out],
                        "altri_assenti": altri[:8], "impatto": round(imp, 3)}
            print(f"ok {div}")
        except Exception as e:
            print(f"! {div}: {e}", file=sys.stderr)
    if squadre:
        with open("data/formazioni_auto.json", "w", encoding="utf-8") as f:
            json.dump({"data": today.isoformat(), "squadre": squadre}, f, ensure_ascii=False)


if __name__ == "__main__":
    main()