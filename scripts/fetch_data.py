"""
scripts/fetch_data.py
Whitelist complète ATP 500+ / Masters 1000 / Grand Chelem + WTA équivalents
Cotes : The Odds API (the-odds-api.com) — Bet365 pré-match ATP/WTA 500+
"""
import os, json, time, re, unicodedata, requests
from datetime import datetime, timedelta, timezone
from pathlib import Path

RAPIDAPI_KEY    = os.getenv("RAPIDAPI_KEY", "")
THE_ODDS_API_KEY = os.getenv("THE_ODDS_API_KEY", "")

BASE    = "https://tennis-api-atp-wta-itf.p.rapidapi.com/tennis/v2"
HEADERS = {
    "X-RapidAPI-Key":  RAPIDAPI_KEY,
    "X-RapidAPI-Host": "tennis-api-atp-wta-itf.p.rapidapi.com",
    "Content-Type":    "application/json"
}

ODDS_API_BASE = "https://api.the-odds-api.com/v4"

Path("data").mkdir(exist_ok=True)
CACHE_FILE = Path("data/api_cache.json")
LOG        = []
REQ_COUNT  = 0

# ── Whitelist officielle ATP 500+ / Masters 1000 / Grand Chelem + WTA ─────────
BETCLIC_WHITELIST = [
    # GRAND CHELEM
    "australian open", "roland-garros", "roland garros",
    "the championships, wimbledon", "wimbledon", "us open",
    # ATP MASTERS 1000
    "bnp paribas open", "miami open", "rolex monte-carlo masters",
    "mutua madrid open", "internazionali bnl d'italia",
    "national bank open presented by rogers", "national bank open",
    "cincinnati open", "western & southern open",
    "rolex shanghai masters", "rolex paris masters", "paris masters",
    # ATP 500
    "nexo dallas open", "abn amro open", "rio open presented by claro", "rio open",
    "qatar exxonmobil open", "dubai duty free tennis championships",
    "abierto mexicano telcel presentado por hsbc", "abierto mexicano telcel",
    "barcelona open banc sabadell", "bmw open by bitpanda",
    "bitpanda hamburg open", "gonet geneva open",
    "hsbc championships", "terra wortmann open",
    "mubadala citi dc open",
    "kinoshita group japan open tennis championships",
    "china open", "swiss indoors basel", "erste bank open",
    # WTA 1000
    "united cup", "mubadala abu dhabi open", "qatar totalenergies open",
    "porsche tennis grand prix", "wuhan open",
    "guadalajara open akron", "guadalajara open",
    # WTA 500
    "asb classic", "brisbane international presented by anz", "brisbane international",
    "merida open akron", "atx open",
    "credit one charleston open", "internationaux de strasbourg",
    "strasbourg international", "berlin tennis open", "lexus nottingham open",
    "bad homburg open", "lexus eastbourne open", "mubadala dc open",
    "toray pan pacific open", "korea open", "singapore tennis open",
    "kinoshita group japan open", "sp open", "ningbo open",
    # ATP/WTA FINALS
    "nitto atp finals", "atp finals", "wta finals", "next gen atp finals",
]

def is_betclic(tournament_name):
    t = tournament_name.lower().strip()
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
    fixtures   = []
    today      = datetime.now().strftime("%Y-%m-%d")
    tomorrow   = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    params     = {
        "include":  "round,tournament.court,tournament.rank",
        "filter":   "PlayerGroup:singles",
        "pageSize": "100"
    }
    total_seen = 0
    rejected   = set()

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
                if not is_betclic(tournament):
                    rejected.add(tournament)
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

            log("INFO", f"{tour.upper()} {date} → {kept} matchs retenus (sur {len(items or [])} vus)")

    if rejected:
        log("DEBUG", f"Exclus : {sorted(rejected)}")

    seen, out = set(), []
    for f in fixtures:
        k = (f["player_a"], f["player_b"], f["date"])
        if k not in seen:
            seen.add(k)
            out.append(f)

    out.sort(key=lambda x: (
        0 if x["tour"] == "ATP" else 1,
        x["tournament"],
        x["time"]
    ))

    log("INFO", f"✅ {len(out)} matchs retenus / {total_seen} analysés")
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

# ── Cotes Bet365 via The Odds API ─────────────────────────────────────────────
#
# Mapping : nom de tournoi (whitelist) → sport_key The Odds API
# https://the-odds-api.com/sports/tennis-odds.html
#
TOURNAMENT_TO_SPORT_KEY = {
    # Grand Chelem
    "australian open":                       "tennis_atp_aus_open_singles",
    "roland-garros":                         "tennis_atp_french_open",
    "roland garros":                         "tennis_atp_french_open",
    "the championships, wimbledon":          "tennis_atp_wimbledon",
    "wimbledon":                             "tennis_atp_wimbledon",
    "us open":                               "tennis_atp_us_open",
    # ATP Masters 1000
    "bnp paribas open":                      "tennis_atp_indian_wells",
    "miami open":                            "tennis_atp_miami_open",
    "rolex monte-carlo masters":             "tennis_atp_monte_carlo_masters",
    "mutua madrid open":                     "tennis_atp_madrid_open",
    "internazionali bnl d'italia":           "tennis_atp_italian_open",
    "national bank open presented by rogers":"tennis_atp_canadian_open",
    "national bank open":                    "tennis_atp_canadian_open",
    "cincinnati open":                       "tennis_atp_cincinnati_open",
    "western & southern open":               "tennis_atp_cincinnati_open",
    "rolex shanghai masters":                "tennis_atp_shanghai_masters",
    "rolex paris masters":                   "tennis_atp_paris_masters",
    "paris masters":                         "tennis_atp_paris_masters",
    # ATP 500
    "qatar exxonmobil open":                 "tennis_atp_qatar_open",
    "dubai duty free tennis championships":  "tennis_atp_dubai",
    "barcelona open banc sabadell":          "tennis_atp_barcelona_open",
    "bmw open by bitpanda":                  "tennis_atp_munich",
    "bitpanda hamburg open":                 "tennis_atp_hamburg_open",
    "hsbc championships":                    "tennis_atp_queens",
    "terra wortmann open":                   "tennis_atp_halle",
    "swiss indoors basel":                   "tennis_atp_swiss_indoors_basel",
    "erste bank open":                       "tennis_atp_erste_bank_open",
    "china open":                            "tennis_atp_china_open",
    # WTA 1000 / 500 — The Odds API couvre les principaux
    "porsche tennis grand prix":             "tennis_wta_stuttgart",
    "wuhan open":                            "tennis_wta_wuhan_open",
    "berlin tennis open":                    "tennis_wta_berlin",
    "lexus nottingham open":                 "tennis_wta_nottingham",
    "bad homburg open":                      "tennis_wta_bad_homburg",
    "lexus eastbourne open":                 "tennis_wta_eastbourne",
    "guadalajara open akron":                "tennis_wta_guadalajara",
    "guadalajara open":                      "tennis_wta_guadalajara",
    "toray pan pacific open":                "tennis_wta_pan_pacific_open",
    # ATP/WTA Finals
    "nitto atp finals":                      "tennis_atp_finals",
    "atp finals":                            "tennis_atp_finals",
    "wta finals":                            "tennis_wta_finals",
}

def _normalize_name(name: str) -> str:
    """'Félix Auger-Aliassime' → 'felix auger aliassime'"""
    n = unicodedata.normalize("NFD", name)
    n = "".join(c for c in n if unicodedata.category(c) != "Mn")
    n = n.lower()
    n = re.sub(r"[^a-z\s]", " ", n)
    return re.sub(r"\s+", " ", n).strip()

def _names_match(api_name: str, fixture_name: str) -> bool:
    """
    Vérifie si deux noms de joueurs correspondent,
    tolérant les abréviations (ex: 'A. Zverev' ↔ 'Alexander Zverev').
    """
    a = _normalize_name(api_name)
    b = _normalize_name(fixture_name)
    if a == b:
        return True
    a_parts = set(a.split())
    b_parts = set(b.split())
    # Le nom de famille doit matcher + au moins un autre token (prénom ou initiale)
    common = a_parts & b_parts
    return len(common) >= 2 or (
        len(common) == 1 and len(a_parts) >= 2 and len(b_parts) >= 2
        and max(len(p) for p in common) >= 4  # pas juste une initiale
    )

def _get_sport_key(tournament_name: str) -> str | None:
    """Retourne le sport_key The Odds API pour un nom de tournoi."""
    t = tournament_name.lower().strip()
    # Recherche exacte d'abord
    if t in TOURNAMENT_TO_SPORT_KEY:
        return TOURNAMENT_TO_SPORT_KEY[t]
    # Recherche partielle (substring)
    for key, sport_key in TOURNAMENT_TO_SPORT_KEY.items():
        if key in t or t in key:
            return sport_key
    return None

def _fetch_odds_api_upcoming() -> list:
    """
    Stratégie principale : GET /v4/sports/upcoming/odds
    Retourne tous les matchs à venir de tous les sports en UNE seule requête.
    On filtre ensuite côté Python sur le tennis.
    Cache 30 min — économise le quota (1 requête pour tout le pipeline).
    """
    if not THE_ODDS_API_KEY:
        return []
    ck = "theoddsapi_upcoming"
    cached = cache_get(ck, max_age_hours=0.5)
    if cached is not None:
        return cached
    try:
        r = requests.get(
            f"{ODDS_API_BASE}/sports/upcoming/odds",
            params={
                "apiKey":      THE_ODDS_API_KEY,
                "regions":     "eu,uk",    # tous bookmakers EU+UK (Bet365, Unibet, Pinnacle…)
                "markets":     "h2h",
                "oddsFormat":  "decimal",
            },
            timeout=10,
        )
        remaining = r.headers.get("x-requests-remaining", "?")
        used      = r.headers.get("x-requests-used", "?")
        log("INFO", f"TheOddsAPI upcoming → HTTP {r.status_code} | quota : {used} used / {remaining} remaining")
        if r.status_code == 200:
            data = r.json()
            tennis = [e for e in data if e.get("sport_key", "").startswith("tennis_")]
            bm_names = sorted({bm["title"] for e in tennis for bm in e.get("bookmakers", [])})
            log("INFO", f"TheOddsAPI : {len(tennis)} matchs tennis | bookmakers : {', '.join(bm_names) or 'aucun'}")
            cache_set(ck, tennis)
            return tennis
        elif r.status_code == 401:
            log("ERROR", "THE_ODDS_API_KEY invalide ou manquante (HTTP 401)")
        elif r.status_code == 429:
            log("WARN", "TheOddsAPI : quota dépassé (HTTP 429)")
        else:
            log("WARN", f"TheOddsAPI HTTP {r.status_code} : {r.text[:200]}")
    except Exception as e:
        log("ERROR", f"TheOddsAPI upcoming : {e}")
    return []

def _fetch_odds_api_sport(sport_key: str) -> list:
    """
    Fallback : requête ciblée sur un sport_key spécifique.
    Utilisé seulement si upcoming ne contient pas le tournoi.
    """
    if not THE_ODDS_API_KEY:
        return []
    ck = f"theoddsapi_{sport_key}"
    cached = cache_get(ck, max_age_hours=0.5)
    if cached is not None:
        return cached
    try:
        r = requests.get(
            f"{ODDS_API_BASE}/sports/{sport_key}/odds",
            params={
                "apiKey":      THE_ODDS_API_KEY,
                "regions":     "eu,uk",
                "markets":     "h2h",
                "oddsFormat":  "decimal",
            },
            timeout=10,
        )
        remaining = r.headers.get("x-requests-remaining", "?")
        log("DEBUG", f"TheOddsAPI [{sport_key}] → HTTP {r.status_code} | quota restant : {remaining}")
        if r.status_code == 200:
            data = r.json()
            cache_set(ck, data)
            return data
        elif r.status_code == 422:
            log("WARN", f"TheOddsAPI : '{sport_key}' hors-saison ou sport_key inconnu")
        else:
            log("WARN", f"TheOddsAPI HTTP {r.status_code} pour {sport_key}")
    except Exception as e:
        log("ERROR", f"TheOddsAPI {sport_key}: {e}")
    return []

# Cache en mémoire pour les events upcoming (évite de re-filtrer à chaque match)
_UPCOMING_EVENTS_CACHE: list | None = None

def _get_all_tennis_events() -> list:
    """Retourne les events tennis avec fallback sport_key si upcoming vide."""
    global _UPCOMING_EVENTS_CACHE
    if _UPCOMING_EVENTS_CACHE is not None:
        return _UPCOMING_EVENTS_CACHE
    _UPCOMING_EVENTS_CACHE = _fetch_odds_api_upcoming()
    return _UPCOMING_EVENTS_CACHE

# Bookmakers préférés dans l'ordre de priorité (le premier disponible est utilisé)
BOOKMAKER_PRIORITY = ["bet365", "unibet", "pinnacle", "betfair_ex_eu", "william_hill", "betway", "bwin", "marathonbet"]

def _find_in_events(events: list, player_a: str, player_b: str) -> dict | None:
    """Cherche un match dans une liste d'events et retourne les cotes du meilleur bookmaker dispo."""
    for event in events:
        h_team = event.get("home_team", "")
        a_team = event.get("away_team", "")

        pa_home = _names_match(h_team, player_a)
        pa_away = _names_match(a_team, player_a)
        pb_home = _names_match(h_team, player_b)
        pb_away = _names_match(a_team, player_b)

        if not ((pa_home and pb_away) or (pa_away and pb_home)):
            continue

        bookmakers = event.get("bookmakers", [])
        # Trier par priorité, garder les autres en fallback
        bm_by_key = {bm["key"]: bm for bm in bookmakers}
        ordered = [bm_by_key[k] for k in BOOKMAKER_PRIORITY if k in bm_by_key]
        ordered += [bm for bm in bookmakers if bm["key"] not in BOOKMAKER_PRIORITY]

        for bm in ordered:
            for market in bm.get("markets", []):
                if market.get("key") != "h2h":
                    continue
                outcomes = {o["name"]: o["price"] for o in market.get("outcomes", [])}
                if pa_home:
                    od_a = outcomes.get(h_team)
                    od_b = outcomes.get(a_team)
                else:
                    od_a = outcomes.get(a_team)
                    od_b = outcomes.get(h_team)
                if od_a and od_b:
                    return {
                        "player_a_odds": round(float(od_a), 3),
                        "player_b_odds": round(float(od_b), 3),
                        "source":        bm.get("title", bm.get("key", "?")),
                        "sport_key":     event.get("sport_key", ""),
                        "last_update":   bm.get("last_update", ""),
                    }
    return None

def get_odds(player_a: str, player_b: str, date: str, tournament: str = "") -> dict | None:
    """
    Récupère les cotes Bet365 via The Odds API.

    Stratégie :
    1. upcoming/odds — 1 requête pour TOUS les matchs tennis, mis en cache
    2. Fallback : requête ciblée avec sport_key si le tournoi n'était pas dans upcoming
    """
    if not THE_ODDS_API_KEY:
        log("WARN", "THE_ODDS_API_KEY non définie — cotes ignorées")
        return None

    # Étape 1 : chercher dans le cache upcoming
    events = _get_all_tennis_events()
    result = _find_in_events(events, player_a, player_b)
    if result:
        return result

    # Étape 2 : fallback avec sport_key spécifique
    sport_key = _get_sport_key(tournament)
    if sport_key:
        fallback_events = _fetch_odds_api_sport(sport_key)
        result = _find_in_events(fallback_events, player_a, player_b)
        if result:
            return result
        log("DEBUG", f"Pas de cote trouvée pour {player_a} vs {player_b} ({sport_key})")
    else:
        log("DEBUG", f"Pas de cote trouvée pour {player_a} vs {player_b} ('{tournament}' absent de upcoming)")

    return None

# ── Pipeline principal ────────────────────────────────────────────────────────

def run():
    global REQ_COUNT
    log("INFO", f"=== fetch_data.py === {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    if not THE_ODDS_API_KEY:
        log("WARN", "⚠️  THE_ODDS_API_KEY non définie — les cotes Bet365 seront absentes")

    fixtures = get_fixtures()
    if not fixtures:
        log("WARN", "Aucun match trouvé — vérifier la whitelist")

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

        odds = get_odds(pa, pb, f["date"], tournament=f.get("tournament", ""))
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
