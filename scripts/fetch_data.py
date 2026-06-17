"""
scripts/fetch_data.py
Whitelist stricte des tournois Betclic (ATP 500 / Masters 1000 / Grand Chelem / WTA équivalents)
Mis à jour chaque semaine selon le calendrier
"""
import os, json, time, requests
from datetime import datetime, timedelta, timezone
from pathlib import Path

RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY", "")
BASE    = "https://tennis-api-atp-wta-itf.p.rapidapi.com/tennis/v2"
HEADERS = {
    "X-RapidAPI-Key":  RAPIDAPI_KEY,
    "X-RapidAPI-Host": "tennis-api-atp-wta-itf.p.rapidapi.com",
    "Content-Type":    "application/json"
}

Path("data").mkdir(exist_ok=True)
CACHE_FILE = Path("data/api_cache.json")
LOG        = []
REQ_COUNT  = 0

# ── Whitelist tournois Betclic ─────────────────────────────────────────────────
# Mettre à jour chaque semaine selon le calendrier ATP/WTA
# Format : fragment du nom du tournoi en minuscules

BETCLIC_WHITELIST = [
    # === SEMAINE ACTUELLE (16-22 juin 2025) ===
    "halle",
    "queen",          # Queen's Club Championships
    "berlin",         # WTA Berlin
    "nottingham",     # WTA Nottingham

    # === SEMAINES SUIVANTES (pré-Wimbledon) ===
    "eastbourne",     # ATP + WTA Eastbourne
    "bad homburg",    # WTA Bad Homburg
    "s-hertogenbosch", # ATP Rosmalen
    "mallorca",       # WTA Mallorca

    # === GRAND CHELEM ===
    "wimbledon",
    "roland garros",
    "australian open",
    "us open",

    # === MASTERS 1000 ATP ===
    "indian wells",
    "miami",
    "monte carlo",
    "madrid",
    "rome",
    "montreal",
    "toronto",
    "cincinnati",
    "shanghai",
    "paris",
    "bercy",
    "canada",

    # === WTA 1000 ===
    "indian wells",
    "miami",
    "madrid",
    "rome",
    "montreal",
    "toronto",
    "cincinnati",
    "beijing",
    "wuhan",
    "guadalajara",

    # === ATP 500 ===
    "rotterdam",
    "rio",
    "dubai",
    "acapulco",
    "barcelona",
    "hamburg",
    "hambourg",
    "tokyo",
    "beijing",
    "vienna",
    "wien",
    "basel",
    "washington",

    # === WTA 500 ===
    "doha",
    "dubai",
    "strasbourg",
    "charleston",
    "birmingham",
    "chicago",
]

def is_betclic(tournament_name):
    """True uniquement si le tournoi est dans la whitelist Betclic."""
    t = tournament_name.lower()
    return any(w in t for w in BETCLIC_WHITELIST)

# ── Cache ──────────────────────────────────────────────────────────────────────

def load_cache():
    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text())
        except:
            pass
    return {}

def save_cache(cache):
    CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=2))

CACHE = load_cache()

def cache_get(key, max_age_hours=6):
    if key in CACHE:
        try:
            age = (datetime.now() - datetime.fromisoformat(
                CACHE[key]["cached_at"])).total_seconds() / 3600
            if age < max_age_hours:
                return CACHE[key]["data"]
        except:
            pass
    return None

def cache_set(key, data):
    CACHE[key] = {"cached_at": datetime.now().isoformat(), "data": data}

# ── Logging ───────────────────────────────────────────────────────────────────

def log(level, msg):
    entry = {"time": datetime.now().strftime("%H:%M:%S"), "level": level, "msg": msg}
    LOG.append(entry)
    print(f"  [{level}] {msg}")

# ── API helpers ───────────────────────────────────────────────────────────────

def api_get(path, params=None, cache_key=None, cache_hours=6):
    global REQ_COUNT
    if cache_key:
        cached = cache_get(cache_key, cache_hours)
        if cached is not None:
            return cached
    if not RAPIDAPI_KEY:
        return None
    try:
        r = requests.get(f"{BASE}/{path}", headers=HEADERS,
                         params=params or {}, timeout=15)
        REQ_COUNT += 1
        time.sleep(0.2)
        if r.status_code == 200:
            data   = r.json()
            result = data.get("data", data) if isinstance(data, dict) else data
            if cache_key:
                cache_set(cache_key, result)
            return result
        else:
            log("WARN", f"HTTP {r.status_code} → {path}")
            return None
    except Exception as e:
        log("ERROR", f"{path}: {e}")
        return None

def api_pages(path, params=None, cache_key=None, max_pages=3):
    global REQ_COUNT
    if cache_key:
        cached = cache_get(cache_key, 6)
        if cached is not None:
            return cached
    all_items, page = [], 1
    p = dict(params or {})
    while page <= max_pages:
        p["pageNo"] = str(page)
        try:
            r = requests.get(f"{BASE}/{path}", headers=HEADERS,
                             params=p, timeout=15)
            REQ_COUNT += 1
            time.sleep(0.2)
            if r.status_code != 200:
                break
            d     = r.json()
            items = d.get("data", []) if isinstance(d, dict) else d
            if isinstance(items, list):
                all_items.extend(items)
            if not (d.get("hasNextPage", False) if isinstance(d, dict) else False):
                break
            page += 1
        except Exception as e:
            log("ERROR", f"{path} p{page}: {e}")
            break
    if cache_key:
        cache_set(cache_key, all_items)
    return all_items

def api_extend(path, cache_key=None, cache_hours=6):
    global REQ_COUNT
    if cache_key:
        cached = cache_get(cache_key, cache_hours)
        if cached is not None:
            return cached
    if not RAPIDAPI_KEY:
        return None
    try:
        r = requests.get(f"{BASE}/{path}", headers=HEADERS, timeout=15)
        REQ_COUNT += 1
        time.sleep(0.2)
        if r.status_code == 200:
            d = r.json()
            if d.get("success"):
                result = d.get("result", {})
                if cache_key:
                    cache_set(cache_key, result)
                return result
        return None
    except Exception as e:
        log("WARN", f"extend {path}: {e}")
        return None

# ── Fixtures ──────────────────────────────────────────────────────────────────

def get_fixtures():
    global REQ_COUNT
    fixtures  = []
    today     = datetime.now().strftime("%Y-%m-%d")
    tomorrow  = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    params    = {
        "include":  "round,tournament.court,tournament.rank",
        "filter":   "PlayerGroup:singles",
        "pageSize": "100"
    }

    total_seen = 0
    total_kept = 0

    for tour in ["atp", "wta"]:
        for date in [today, tomorrow]:
            items = api_pages(
                f"{tour}/fixtures/{date}", params,
                cache_key=f"fix_{tour}_{date}", max_pages=3
            )
            kept = 0
            for m in (items or []):
                pa = (m.get("player1") or {}).get("name", "")
                pb = (m.get("player2") or {}).get("name", "")
                if not pa or not pb or "/" in pa or "/" in pb:
                    continue

                total_seen += 1
                tournament = (m.get("tournament") or {}).get("name", "")

                # Whitelist stricte
                if not is_betclic(tournament):
                    continue

                raw_time    = m.get("date", "") or ""
                is_upcoming = True
                match_time  = "TBD"
                if raw_time:
                    try:
                        dt = datetime.fromisoformat(raw_time.replace("Z", "+00:00"))
                        is_upcoming = dt > datetime.now(timezone.utc)
                        match_time  = (dt + timedelta(hours=2)).strftime("%H:%M")
                    except:
                        pass

                if not is_upcoming:
                    continue

                court_info = ((m.get("tournament") or {}).get("court") or {})
                surface    = court_info.get("name", "Hard") if isinstance(court_info, dict) else "Hard"
                rank_info  = (m.get("tournament") or {}).get("rank") or {}
                rank_name  = rank_info.get("name", "") if isinstance(rank_info, dict) else ""
                round_name = (m.get("round") or {}).get("name", "")

                fixtures.append({
                    "id":              m.get("id"),
                    "player1_id":      m.get("player1Id"),
                    "player2_id":      m.get("player2Id"),
                    "player_a":        pa,
                    "player_b":        pb,
                    "tour":            tour.upper(),
                    "tournament":      tournament,
                    "tournament_rank": rank_name,
                    "surface":         surface,
                    "round":           round_name,
                    "date":            date,
                    "time":            match_time,
                })
                kept += 1

            total_kept += kept
            log("INFO", f"{tour.upper()} {date} → {kept} matchs Betclic (sur {len(items or [])} vus)")

    # Déduplique
    seen, out = set(), []
    for f in fixtures:
        k = (f["player_a"], f["player_b"], f["date"])
        if k not in seen:
            seen.add(k)
            out.append(f)

    # Tri : ATP avant WTA, puis par tournoi, puis par heure
    out.sort(key=lambda x: (
        0 if x["tour"] == "ATP" else 1,
        x["tournament"],
        x["time"]
    ))

    log("INFO", f"✅ {len(out)} matchs retenus (filtrés depuis {total_seen} total)")
    return out

# ── Player data ───────────────────────────────────────────────────────────────

def get_player_data(player_id, tour):
    global REQ_COUNT
    if not player_id:
        return {}
    t    = tour.lower()
    data = {}

    stats = api_get(f"{t}/player/match-stats/{player_id}",
                    cache_key=f"pstats_{player_id}", cache_hours=24)
    if stats:
        data["stats"] = stats

    surf = api_get(f"{t}/player/surface-summary/{player_id}",
                   cache_key=f"psurf_{player_id}", cache_hours=24)
    if surf:
        data["surface"] = surf

    past = api_pages(f"{t}/player/matches/{player_id}",
                     {"pageSize": "20"},
                     cache_key=f"ppast_{player_id}", max_pages=1)
    if past:
        data["past_matches"] = past

    return data

# ── H2H ──────────────────────────────────────────────────────────────────────

def get_h2h(p1_id, p2_id, tour):
    global REQ_COUNT
    if not p1_id or not p2_id:
        return {}
    t         = tour.lower()
    cache_key = f"h2h_{min(p1_id,p2_id)}_{max(p1_id,p2_id)}"
    result    = api_get(f"{t}/h2h/stats/{p1_id}/{p2_id}",
                        cache_key=cache_key, cache_hours=12)
    return result or {}

# ── Cotes Bet365 ──────────────────────────────────────────────────────────────

def get_odds(player_a, player_b, date):
    global REQ_COUNT

    ck_event   = f"evid_{player_a[:12]}_{player_b[:12]}_{date}"
    event_data = cache_get(ck_event, 24)
    if event_data is None:
        event_data = api_extend(
            f"extend/api/event/get/{player_a}/{player_b}/{date}",
            cache_key=ck_event, cache_hours=24
        ) or {}

    if not event_data or not event_data.get("id"):
        return None

    event_id  = event_data["id"]
    ck_odds   = f"odds_{event_id}"
    odds_data = cache_get(ck_odds, 2)
    if odds_data is None:
        odds_data = api_extend(
            f"extend/api/odds/summary/{event_id}",
            cache_key=ck_odds, cache_hours=2
        ) or {}

    if not odds_data:
        return None

    bet365  = odds_data.get("Bet365", {})
    ftr     = bet365.get("Full Time Result", {})
    start   = ftr.get("start", {}) or {}
    kickoff = ftr.get("kickoff", {}) or {}

    od1 = start.get("od1") or kickoff.get("od1")
    od2 = start.get("od2") or kickoff.get("od2")
    if not od1 or not od2:
        return None

    try:
        o1, o2 = float(od1), float(od2)
        if o1 > 20 or o2 > 20:
            return None
        return {
            "player_a_odds": o1,
            "player_b_odds": o2,
            "source":        "bet365",
            "type":          "start" if start.get("od1") else "kickoff",
        }
    except:
        return None

# ── Pipeline principal ────────────────────────────────────────────────────────

def run():
    global REQ_COUNT
    log("INFO", f"=== fetch_data.py === {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    fixtures = get_fixtures()
    if not fixtures:
        log("WARN", "Aucun match Betclic trouvé — vérifier la whitelist")

    enriched     = []
    players_done = {}
    odds_ok      = 0

    for i, f in enumerate(fixtures):
        pa    = f["player_a"]
        pb    = f["player_b"]
        p1_id = f.get("player1_id")
        p2_id = f.get("player2_id")
        tour  = f.get("tour", "ATP")

        log("INFO", f"[{i+1}/{len(fixtures)}] {pa} vs {pb} · {f['tournament']} · {f['time']}")

        if p1_id and p1_id not in players_done:
            players_done[p1_id] = get_player_data(p1_id, tour)
        if p2_id and p2_id not in players_done:
            players_done[p2_id] = get_player_data(p2_id, tour)

        f["player_a_data"] = players_done.get(p1_id, {})
        f["player_b_data"] = players_done.get(p2_id, {})
        f["h2h"]           = get_h2h(p1_id, p2_id, tour)

        odds = get_odds(pa, pb, f["date"])
        f["odds"] = odds
        if odds:
            odds_ok += 1
            log("INFO", f"  ✅ Bet365 {pa} {odds['player_a_odds']} / {pb} {odds['player_b_odds']}")
        else:
            log("INFO", f"  ⚠️ Pas de cotes Bet365")

        enriched.append(f)

    Path("data/fixtures.json").write_text(
        json.dumps({
            "fetched_at":     datetime.now().isoformat(),
            "fixtures_count": len(enriched),
            "odds_available": odds_ok,
            "requests_used":  REQ_COUNT,
            "fixtures":       enriched,
        }, ensure_ascii=False, indent=2)
    )

    save_cache(CACHE)
    log("INFO", f"=== Terminé : {len(enriched)} matchs · {odds_ok} cotes · {REQ_COUNT} requêtes ===")

    Path("data/pipeline_log.json").write_text(
        json.dumps({
            "date":           datetime.now().isoformat(),
            "steps":          LOG,
            "requests_used":  REQ_COUNT,
            "fixtures_count": len(enriched),
            "odds_available": odds_ok,
        }, ensure_ascii=False, indent=2)
    )

if __name__ == "__main__":
    run()
