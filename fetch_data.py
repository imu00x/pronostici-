#!/usr/bin/env python3
"""Scarica dati gratuiti (football-data.co.uk) e genera data.json con pronostici, classifiche e serie."""
import csv, difflib, io, json, math, re, sys, unicodedata, urllib.request
from datetime import datetime, date, timedelta, timezone
from collections import defaultdict

LEAGUES = {"I1": "Serie A", "E0": "Premier League", "SP1": "La Liga", "D1": "Bundesliga", "F1": "Ligue 1"}
BASE = "https://www.football-data.co.uk/"
HALF_LIFE = 200.0
MAXG = 8

STREAKS = [
    ("Segna", None, lambda f, a: f > 0),
    ("Segna in casa", "casa", lambda f, a: f > 0),
    ("Segna in trasferta", "trasferta", lambda f, a: f > 0),
    ("Imbattuta", None, lambda f, a: f >= a),
    ("Imbattuta in casa", "casa", lambda f, a: f >= a),
    ("Imbattuta in trasferta", "trasferta", lambda f, a: f >= a),
    ("Vince", None, lambda f, a: f > a),
    ("Vince in casa", "casa", lambda f, a: f > a),
    ("Vince in trasferta", "trasferta", lambda f, a: f > a),
    ("Senza vittorie", None, lambda f, a: f <= a),
    ("Perde", None, lambda f, a: f < a),
    ("Porta inviolata", None, lambda f, a: a == 0),
    ("Subisce gol", None, lambda f, a: a > 0),
    ("Over 2.5", None, lambda f, a: f + a > 2),
    ("Under 2.5", None, lambda f, a: f + a < 3),
    ("Gol-Gol", None, lambda f, a: f > 0 and a > 0),
]


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8-sig", errors="replace")


def pdate(s):
    for f in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(s.strip(), f).date()
        except Exception:
            pass
    return None


def season_codes(today):
    y = today.year if today.month >= 7 else today.year - 1
    return [f"{(y - k) % 100:02d}{(y - k + 1) % 100:02d}" for k in (3, 2, 1, 0)]


def load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def load_matches(div, seasons):
    out = []
    for s in seasons:
        try:
            txt = fetch(f"{BASE}mmz4281/{s}/{div}.csv")
        except Exception as e:
            print(f"! {div} {s}: {e}", file=sys.stderr)
            continue
        for row in csv.DictReader(io.StringIO(txt)):
            d = pdate(row.get("Date") or "")
            try:
                hg, ag = int(row["FTHG"]), int(row["FTAG"])
            except Exception:
                continue
            if d and row.get("HomeTeam"):
                out.append({"d": d, "s": s, "h": row["HomeTeam"], "a": row["AwayTeam"], "hg": hg, "ag": ag})
    out.sort(key=lambda m: m["d"])
    return out


def compute_elo(ms):
    elo = defaultdict(lambda: 1500.0)
    cur = None
    for m in ms:
        if m["s"] != cur:
            if cur is not None:
                for t in list(elo):
                    elo[t] = 1500 + 0.75 * (elo[t] - 1500)
            cur = m["s"]
        eh, ea = elo[m["h"]], elo[m["a"]]
        exp = 1 / (1 + 10 ** (-(eh + 60 - ea) / 400))
        res = 1 if m["hg"] > m["ag"] else 0.5 if m["hg"] == m["ag"] else 0
        k = 20 * (1 + 0.5 * math.log(1 + abs(m["hg"] - m["ag"])))
        elo[m["h"]] += k * (res - exp)
        elo[m["a"]] -= k * (res - exp)
    return elo


def strengths(ms, today):
    gf, ga, w = defaultdict(float), defaultdict(float), defaultdict(float)
    hgs = ags = tw = 0.0
    for m in ms:
        age = (today - m["d"]).days
        if age > 730:
            continue
        wt = 0.5 ** (age / HALF_LIFE)
        gf[m["h"]] += wt * m["hg"]; ga[m["h"]] += wt * m["ag"]; w[m["h"]] += wt
        gf[m["a"]] += wt * m["ag"]; ga[m["a"]] += wt * m["hg"]; w[m["a"]] += wt
        hgs += wt * m["hg"]; ags += wt * m["ag"]; tw += wt
    if tw == 0:
        raise RuntimeError("nessun dato recente")
    avg_h, avg_a = hgs / tw, ags / tw
    avg = (avg_h + avg_a) / 2
    k = 5.0
    att = {t: ((gf[t] + k * avg) / (w[t] + k)) / avg for t in w}
    dfn = {t: ((ga[t] + k * avg) / (w[t] + k)) / avg for t in w}
    return att, dfn, avg_h, avg_a


def table(ms, season):
    t = defaultdict(lambda: {"g": 0, "pt": 0, "gf": 0, "gs": 0, "v": 0, "n": 0, "p": 0})
    for m in ms:
        if m["s"] != season:
            continue
        for team, f, a in ((m["h"], m["hg"], m["ag"]), (m["a"], m["ag"], m["hg"])):
            r = t[team]
            r["g"] += 1; r["gf"] += f; r["gs"] += a
            if f > a: r["v"] += 1; r["pt"] += 3
            elif f == a: r["n"] += 1; r["pt"] += 1
            else: r["p"] += 1
    rows = [dict(squadra=k, **v) for k, v in t.items()]
    rows.sort(key=lambda r: (-r["pt"], -(r["gf"] - r["gs"]), -r["gf"]))
    for i, r in enumerate(rows, 1):
        r["pos"] = i
    return rows


def team_matches(ms):
    d = defaultdict(list)
    for m in ms:
        d[m["h"]].append((m["d"], True, m["hg"], m["ag"]))
        d[m["a"]].append((m["d"], False, m["ag"], m["hg"]))
    return d


def run(lst, cond, scope):
    n = 0
    for _, home, f, a in reversed(lst):
        if scope == "casa" and not home: continue
        if scope == "trasferta" and home: continue
        if cond(f, a): n += 1
        else: break
    return n


def poisson(k, l):
    return math.exp(-l) * l ** k / math.factorial(k)


def probs(lh, la):
    w = x = l = o = b = 0.0
    best = (0, 0, 0.0)
    for i in range(MAXG + 1):
        pi = poisson(i, lh)
        for j in range(MAXG + 1):
            p = pi * poisson(j, la)
            if i > j: w += p
            elif i == j: x += p
            else: l += p
            if i + j > 2: o += p
            if i > 0 and j > 0: b += p
            if p > best[2]: best = (i, j, p)
    s = w + x + l
    return w / s, x / s, l / s, o / s, b / s, best


def clip(x, lo, hi):
    return max(lo, min(hi, x))


def predict(h, a, c):
    att, dfn = c["att"], c["dfn"]
    base_h = c["avg_h"] * att[h] * dfn[a]
    base_a = c["avg_a"] * att[a] * dfn[h]
    d = (c["elo"][h] - c["elo"][a]) / 400
    elo_h, elo_a = 10 ** (0.15 * d), 10 ** (-0.15 * d)

    def fm(t):
        f = c["form"].get(t, [])
        if len(f) < 3: return 1.0
        pts = sum(3 if x == "V" else 1 if x == "P" else 0 for x in f)
        return 1 + 0.08 * (pts / (3 * len(f)) * 2 - 1)

    def sm(t):
        r = c["tmap"].get(t)
        if not r or r["g"] < 4: return 1.0
        return 1 + 0.06 * clip((r["pt"] / r["g"] - 1.37) / 1.0, -1, 1)

    def vm(t):
        v = c["vals"].get(t)
        if not v or not c["med"]: return 1.0
        return clip((v / c["med"]) ** 0.08, 0.9, 1.1)

    def lm(t):
        imp = c["lin"].get(t, {}).get("impatto", 0) if isinstance(c["lin"].get(t), dict) else 0
        return 1 + clip(float(imp), -0.3, 0.1)

    mult = {
        "Statistiche": (elo_h, elo_a, base_h, base_a),
        "Forma recente": (fm(h), fm(a)),
        "Classifica": (sm(h), sm(a)),
        "Valore rosa": (vm(h), vm(a)),
        "Probabili formazioni": (lm(h), lm(a)),
    }
    lh = base_h * elo_h * fm(h) * sm(h) * vm(h) * lm(h)
    la = base_a * elo_a * fm(a) * sm(a) * vm(a) * lm(a)
    effs = {}
    for k, v in mult.items():
        if k == "Statistiche":
            effs[k] = math.log(v[0] / v[1]) + math.log(v[2] / v[3])
        else:
            effs[k] = math.log(v[0] / v[1])
    tot = sum(abs(e) for e in effs.values())
    peso = {k: (round(abs(e) / tot * 100) if tot > 1e-9 else 20) for k, e in effs.items()}

    def sd(e):
        return "equilibrio" if abs(e) < 0.02 else ("casa" if e > 0 else "trasferta")

    def fs(t):
        f = c["form"].get(t, [])
        return "".join(f) if f else "n/d"

    def cl(t):
        r = c["tmap"].get(t)
        return f"{r['pos']}° · {r['pt']} pt in {r['g']} gare" if r else "n/d"

    def vs(t):
        v = c["vals"].get(t)
        return f"{v:.0f} M€" if v else "n/d"

    def ls(t):
        x = c["lin"].get(t)
        if not isinstance(x, dict): return "nessun dato"
        ass = x.get("assenti") or []
        return ("assenti: " + ", ".join(ass)) if ass else "nessuna assenza segnalata"

    txt = {
        "Statistiche": (f"Elo {c['elo'][h]:.0f} · att {att[h]:.2f} · dif {dfn[h]:.2f}", f"Elo {c['elo'][a]:.0f} · att {att[a]:.2f} · dif {dfn[a]:.2f}"),
        "Forma recente": (fs(h), fs(a)),
        "Classifica": (cl(h), cl(a)),
        "Valore rosa": (vs(h), vs(a)),
        "Probabili formazioni": (ls(h), ls(a)),
    }
    fattori = [{"nome": k, "casa": txt[k][0], "trasf": txt[k][1], "vantaggio": sd(effs[k]), "peso": peso[k]} for k in mult]

    p1, px, p2, ov, gg, best = probs(lh, la)
    m = max(p1, px, p2)
    if m >= 0.45:
        pick = "1" if m == p1 else "X" if m == px else "2"
    else:
        pick = "1X" if p1 >= p2 else "X2"
    if pick in ("1", "1X"): lead = f"Pronostico {pick}: {h} favorita ({round(p1 * 100)}% di vittoria)."
    elif pick in ("2", "X2"): lead = f"Pronostico {pick}: {a} favorita ({round(p2 * 100)}% di vittoria)."
    else: lead = "Pronostico X: partita equilibrata, il pareggio è il segno più probabile."
    top = sorted(fattori, key=lambda f: -f["peso"])[:2]
    dtxt = lambda f: {"casa": f"favorisce {h}", "trasferta": f"favorisce {a}", "equilibrio": "in equilibrio"}[f["vantaggio"]]
    spieg = f"{lead} Pesano soprattutto: " + "; ".join(f"{f['nome'].lower()} ({dtxt(f)}, {f['peso']}%)" for f in top) + f". Gol attesi: {lh:.2f} – {la:.2f}."
    return {
        "p1": round(p1, 4), "px": round(px, 4), "p2": round(p2, 4), "over25": round(ov, 4), "gg": round(gg, 4),
        "xg_casa": round(lh, 2), "xg_trasf": round(la, 2), "risultato": f"{best[0]}-{best[1]}",
        "pronostico": pick, "spiegazione": spieg, "fattori": fattori,
    }


def get_fixtures():
    try:
        rows = list(csv.DictReader(io.StringIO(fetch(BASE + "fixtures.csv"))))
    except Exception as e:
        print(f"! fixtures: {e}", file=sys.stderr)
        return {}