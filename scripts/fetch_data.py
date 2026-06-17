"""
scripts/fetch_data.py
Récupère toutes les données depuis RapidAPI tennis-api-atp-wta-itf
- Fixtures du jour (ATP/WTA 250+)
- Stats joueur (surface, service, forme)
- H2H
- Cotes Bet365
- Event IDs pour cotes
"""
import os, json, time, requests
from datetime import datetime, timedelta, timezone
from pathlib import Path
from collections import defaultdict

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

# ── Cache ─────────────────────────────────────────────────────────────────────

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
        age = (datetime.now() - datetime.fromisoformat(
            CACHE[key]["cached_at"])).total_seconds() / 3600
        if age < max_age_hours:
            return CACHE[key]["data"]
    return None

def cache_set(key, data):
    CACHE[key] = {"cached_at": datetime.now().isoformat(), "data": data}

# ── API ───────────────────────────────────────────────────────────────────────

def api(path, params=None, cache_key=None, cache_hours=6):
    global REQ_COUNT
    if cache_key:
        cached = cache_get(cache_key, cache_hours)
        if cached is not None:
            return cached

    if not RAPIDAPI_KEY:
        log("WARN", f"Clé API manquante — {path}")
        return None

    try:
        r = requests.get(f"{BASE}/{path}", headers=HEADERS,
                         params=params or {}, timeout=15)
        REQ_COUNT += 1
        if r.status_code == 200:
            data = r.json()
            result = data.get("data", data) if isinstance(data, dict) else data
            if cache_key:
                cache_set(cache_key, result)
            time.sleep(0.3)
            return result
        else:
            log("WARN", f"HTTP {r.status_code} → {path}")
            return None
    except Exception as e:
        log("ERROR", f"{path} : {e}")
        return None

def api_pages(path, params=None, cache_key=None, max_pages=5):
    """Récupère toutes les pages d'un endpoint paginé."""
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
            if r.status_code != 200:
                break
            d = r.json()
            items = d.get("data", []) if isinstance(d, dict) else d
            all_items.extend(items)
            if not (d.get("hasNextPage", False) if isinstance(d, dict) else False):
                break
            page += 1
            time.sleep(0.3)
        except Exception as e:
            log("ERROR", f"{path} p{page}: {e}")
            break

    if cache_key:
        cache_set(cache_key, all_items)
    return all_items

# ── Logging ───────────────────────────────────────────────────────────────────

def log(level, msg):
    entry = {
        "time":  datetime.now().strftime("%H:%M:%S"),
        "level": level,
        "msg":   msg
    }
    LOG.append(entry)
    print(f"  [{level}] {msg}")

# ── Fixtures ──────────────────────────────────────────────────────────────────

def get_fixtures():
    """Récupère les fixtures ATP/WTA pour aujourd'hui et demain."""
    fixtures = []
    today    = datetime.now().strftime("%Y-%m-%d")
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    params   = {
        "include":  "round,tournament.court,tournament.rank",
        "filter":   "PlayerGroup:singles",
        "pageSize": "100"
    }

    for tour in ["atp", "wta"]:
        for date in [today, tomorrow]:
            items = api_pages(
                f"{tour}/fixtures/{date}", params,
                cache_key=f"fixtures_{tour}_{date}", max_pages=3
            )
            singles = 0
            for m in (items or []):
                pa = (m.get("player1") or {}).get("name","")
                pb = (m.get("player2") or {}).get("name","")
                if not pa or not pb or "/" in pa or "/" in pb:
                    continue

                # Filtre ATP/WTA 250+ via tournament rank
                rank_info = (m.get("tournament") or {}).get("rank") or {}
                rank_name = rank_info.get("name","") if isinstance(rank_info,dict) else ""

                # Détecter si le match est à venir
                raw_time = m.get("date","") or ""
                is_upcoming = True
                match_time  = "TBD"
                if raw_time:
                    try:
                        dt = datetime.fromisoformat(raw_time.replace("Z","+00:00"))
                        is_upcoming = dt > datetime.now(timezone.utc)
                        match_time  = dt.strftime("%H:%M")
                    except:
                        pass

                if not is_upcoming:
                    continue

                tournament = (m.get("tournament") or {}).get("name","")
                court      = ((m.get("tournament") or {}).get("court") or {})
                surface    = court.get("name","") if isinstance(court,dict) else "Hard"
                round_name = (m.get("round") or {}).get("name","")

                fixtures.append({
                    "id":           m.get("id"),
                    "player1_id":   m.get("player1Id"),
                    "player2_id":   m.get("player2Id"),
                    "player_a":     pa,
                    "player_b":     pb,
                    "tour":         tour.upper(),
                    "tournament":   tournament,
                    "tournament_rank": rank_name,
                    "surface":      surface,
                    "round":        round_name,
                    "date":         date,
                    "time":         match_time,
                })
                singles += 1

            log("INFO", f"{tour.upper()} {date} → {singles} matchs")

    # Déduplique
    seen, out = set(), []
    for f in fixtures:
        k = (f["player_a"], f["player_b"], f["date"])
        if k not in seen:
            seen.add(k); out.append(f)

    log("INFO", f"Total fixtures : {len(out)}")
    return out

# ── Player data ───────────────────────────────────────────────────────────────

def get_player_data(player_id, tour):
    """Récupère toutes les données d'un joueur."""
    if not player_id:
        return {}

    t = tour.lower()
    data = {}

    # Info de base (cache 24h)
    info = api(f"{t}/player/{player_id}",
               cache_key=f"player_info_{player_id}", cache_hours=24)
    if info:
        data["info"] = info

    # Stats service globales (cache 24h)
    stats = api(f"{t}/player/stats/{player_id}",
                cache_key=f"player_stats_{player_id}", cache_hours=24)
    if stats:
        data["stats"] = stats

    # Surface summary (cache 24h)
    surf = api(f"{t}/player/surface/{player_id}",
               cache_key=f"player_surf_{player_id}", cache_hours=24)
    if surf:
        data["surface"] = surf

    # Derniers matchs (cache 6h)
    past = api_pages(
        f"{t}/player/matches/{player_id}",
        {"pageSize":"20"},
        cache_key=f"player_past_{player_id}", max_pages=1
    )
    if past:
        data["past_matches"] = past

    # Performance breakdown (cache 24h)
    perf = api(f"{t}/player/performance/{player_id}",
               cache_key=f"player_perf_{player_id}", cache_hours=24)
    if perf:
        data["performance"] = perf

    return data

# ── H2H ──────────────────────────────────────────────────────────────────────

def get_h2h(p1_id, p2_id, tour):
    if not p1_id or not p2_id:
        return {}
    t = tour.lower()
    cache_key = f"h2h_{min(p1_id,p2_id)}_{max(p1_id,p2_id)}"
    stats = api(f"{t}/h2h/stats/{p1_id}/{p2_id}",
                cache_key=cache_key, cache_hours=12)
    return stats or {}

# ── Cotes Bet365 ──────────────────────────────────────────────────────────────

def get_odds(player_a, player_b, date):
    """
    1. Trouve l'event ID via Get Event Id
    2. Récupère les cotes via Get Odds Summary
    """
    # Cherche l'event ID
    cache_key = f"event_id_{player_a}_{player_b}_{date}"
    event_data = cache_get(cache_key, 24)

    if event_data is None:
        try:
            r = requests.get(
                f"{BASE}/extend/api/event/get/{player_a}/{player_b}/{date}",
                headers=HEADERS, timeout=15
            )
            REQ_COUNT += 1
            time.sleep(0.3)
            if r.status_code == 200:
                d = r.json()
                if d.get("success"):
                    event_data = d.get("result", {})
                    cache_set(cache_key, event_data)
                else:
                    cache_set(cache_key, {})
                    event_data = {}
            else:
                event_data = {}
        except Exception as e:
            log("WARN", f"Event ID {player_a} vs {player_b}: {e}")
            event_data = {}

    if not event_data or not event_data.get("id"):
        return None

    event_id = event_data["id"]

    # Récupère les cotes
    cache_key_odds = f"odds_{event_id}"
    odds_data = cache_get(cache_key_odds, 2)

    if odds_data is None:
        try:
            r = requests.get(
                f"{BASE}/extend/api/odds/summary/{event_id}",
                headers=HEADERS, timeout=15
            )
            REQ_COUNT += 1
            time.sleep(0.3)
            if r.status_code == 200:
                d = r.json()
                if d.get("success"):
                    odds_data = d.get("result", {})
                    cache_set(cache_key_odds, odds_data)
                else:
                    odds_data = {}
            else:
                odds_data = {}
        except Exception as e:
            log("WARN", f"Odds {event_id}: {e}")
            odds_data = {}

    # Parse les cotes Bet365
    bet365 = (odds_data or {}).get("Bet365", {})
    ftr    = bet365.get("Full Time Result", {})
    start  = ftr.get("start", {})
    kickoff = ftr.get("kickoff", {})

    od1 = start.get("od1") or kickoff.get("od1")
    od2 = start.get("od2") or kickoff.get("od2")

    if od1 and od2:
        try:
            return {
                "player_a_odds": float(od1),
                "player_b_odds": float(od2),
                "source":        "bet365",
                "type":          "start" if start.get("od1") else "kickoff",
            }
        except:
            pass

    return None

# ── Pipeline principal ────────────────────────────────────────────────────────

def run():
    log("INFO", f"=== fetch_data.py === {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    # 1. Fixtures
    log("INFO", "Récupération des fixtures...")
    fixtures = get_fixtures()

    # 2. Données joueurs + H2H + cotes
    enriched = []
    players_fetched = set()

    for i, f in enumerate(fixtures):
        log("INFO", f"[{i+1}/{len(fixtures)}] {f['player_a']} vs {f['player_b']}")

        p1_id = f.get("player1_id")
        p2_id = f.get("player2_id")
        tour  = f.get("tour", "ATP")

        # Données joueur A
        if p1_id and p1_id not in players_fetched:
            f["player_a_data"] = get_player_data(p1_id, tour)
            players_fetched.add(p1_id)
        else:
            f["player_a_data"] = {}

        # Données joueur B
        if p2_id and p2_id not in players_fetched:
            f["player_b_data"] = get_player_data(p2_id, tour)
            players_fetched.add(p2_id)
        else:
            f["player_b_data"] = {}

        # H2H
        f["h2h"] = get_h2h(p1_id, p2_id, tour)

        # Cotes Bet365
        odds = get_odds(f["player_a"], f["player_b"], f["date"])
        f["odds"] = odds
        if odds:
            log("INFO", f"  ✅ Cotes Bet365 : {odds['player_a_odds']} / {odds['player_b_odds']}")
        else:
            log("INFO", f"  ⚠️ Pas de cotes disponibles")

        enriched.append(f)

    # Sauvegarde
    out = {
        "fetched_at": datetime.now().isoformat(),
        "fixtures_count": len(enriched),
        "requests_used": REQ_COUNT,
        "fixtures": enriched,
    }
    Path("data/fixtures.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2)
    )

    save_cache(CACHE)

    log("INFO", f"=== Terminé : {len(enriched)} fixtures · {REQ_COUNT} requêtes API ===")

    # Sauvegarde du log
    Path("data/pipeline_log.json").write_text(
        json.dumps({
            "date": datetime.now().isoformat(),
            "steps": LOG,
            "requests_used": REQ_COUNT,
            "fixtures_count": len(enriched),
        }, ensure_ascii=False, indent=2)
    )

if __name__ == "__main__":
    run()
