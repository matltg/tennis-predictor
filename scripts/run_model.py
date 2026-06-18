"""
scripts/run_model.py
Prédit pour chaque match :
1. Vainqueur (probabilité + indice de confiance)
2. Over/Under jeux (nombre total de jeux)
3. 2 sets vs 3 sets

Améliorations v2.1 :
- Cotes Bet365 intégrées comme feature dans le modèle (market signal)
- Stats de service enrichies depuis compute_elo (hold%, ace rate, bp_saved%)
- WTA supporté (Elo 1500 par défaut + stats MCP)
"""
import json
from pathlib import Path
from datetime import datetime

ELO_PATH      = Path("data/elo_ratings.json")
FIXTURES_PATH = Path("data/fixtures.json")
OUT_PATH      = Path("data/predictions.json")
OUT_PATH.parent.mkdir(exist_ok=True)

EDGE_MIN  = 5.0
KELLY_K   = 0.25
KELLY_MAX = 3.5

SURF_MAP = {"Grass":"grass","Clay":"clay","Hard":"hard","I.hard":"hard","Carpet":"hard"}

# ── Elo ───────────────────────────────────────────────────────────────────────

def load_elo():
    if not ELO_PATH.exists():
        return {}
    return json.loads(ELO_PATH.read_text()).get("ratings", {})

def get_elo(ratings, name, surface="global"):
    key = f"elo_{surface}" if surface != "global" else "elo_global"

    # Recherche exacte
    if name in ratings:
        r = ratings[name]
        return r.get(key, r.get("elo_global", 1500))

    # Recherche partielle
    nl = name.lower()
    best = None
    for n, r in ratings.items():
        if nl == n.lower():
            return r.get(key, r.get("elo_global", 1500))
        if nl in n.lower() or n.lower() in nl:
            best = r
    if best:
        return best.get(key, best.get("elo_global", 1500))
    return 1500

def get_elo_stats(ratings, name):
    """Retourne les stats de service calculées depuis TML/MCP."""
    if name in ratings:
        return ratings[name]
    nl = name.lower()
    for n, r in ratings.items():
        if nl in n.lower() or n.lower() in nl:
            return r
    return {}

def elo_prob(ra, rb):
    return 1.0 / (1.0 + 10**((rb-ra)/400))

# ── Features depuis API data ──────────────────────────────────────────────────

def parse_score(result):
    if not result:
        return None, None
    sets = result.strip().split()
    total_games, n_sets = 0, 0
    for s in sets:
        s = s.split("(")[0]
        if "-" in s:
            try:
                a, b = s.split("-")
                total_games += int(a) + int(b)
                n_sets += 1
            except:
                pass
    return total_games if total_games > 0 else None, n_sets if n_sets > 0 else None

def get_service_stats(player_data):
    """Extrait les stats de service depuis les données API RapidAPI."""
    stats = player_data.get("stats", {})
    if not stats:
        return {}

    svc    = stats.get("serviceStats", {})
    rtn    = stats.get("rtnStats", {})
    bp_svc = stats.get("breakPointsServeStats", {})
    bp_rtn = stats.get("breakPointsRtnStats", {})

    result = {}

    fs    = svc.get("firstServeGm", 0)
    fs_of = svc.get("firstServeOfGm", 1)
    if fs_of > 0:
        result["first_serve_pct"] = round(fs / fs_of * 100, 1)

    w1s = svc.get("winningOnFirstServeGm", 0)
    if fs > 0:
        result["win_1st_serve_pct"] = round(w1s / fs * 100, 1)

    w2s    = svc.get("winningOnSecondServeGm", 0)
    w2s_of = svc.get("winningOnSecondServeOfGm", 1)
    if w2s_of > 0:
        result["win_2nd_serve_pct"] = round(w2s / w2s_of * 100, 1)

    if all(k in result for k in ["first_serve_pct","win_1st_serve_pct","win_2nd_serve_pct"]):
        fs_p  = result["first_serve_pct"] / 100
        w1s_p = result["win_1st_serve_pct"] / 100
        w2s_p = result["win_2nd_serve_pct"] / 100
        result["hold_pct"] = round((fs_p*w1s_p + (1-fs_p)*w2s_p)*100, 1)

    rw    = rtn.get("winningOnFirstServeGm", 0)
    rw_of = rtn.get("firstServeGm", 1)
    if rw_of > 0:
        result["return_win_pct"] = round((1 - rw/rw_of)*100, 1)

    bpf = bp_svc.get("breakPointFacedGm", 0)
    bps = bp_svc.get("breakPointSavedGm", 0)
    if bpf > 0:
        result["bp_saved_pct"] = round(bps/bpf*100, 1)

    bpc = bp_rtn.get("breakPointChanceGm", 0)
    bpw = bp_rtn.get("breakPointWonGm", 0)
    if bpc > 0:
        result["bp_converted_pct"] = round(bpw/bpc*100, 1)

    return result

def get_form(past_matches):
    if not past_matches:
        return {}
    wins, losses, games_total, sets_counts = 0, 0, [], []
    for m in past_matches[:10]:
        winner = m.get("match_winner")
        p1_id  = m.get("player1Id")
        result = m.get("result", "")
        is_win = (winner == p1_id)
        if is_win: wins += 1
        else: losses += 1
        total_g, n_sets = parse_score(result)
        if total_g: games_total.append(total_g)
        if n_sets:  sets_counts.append(n_sets)
    total = wins + losses
    return {
        "wins_10":    wins,
        "losses_10":  losses,
        "winrate_10": round(wins/total*100, 1) if total > 0 else 50.0,
        "avg_games":  round(sum(games_total)/len(games_total), 1) if games_total else None,
        "pct_3sets":  round(sum(1 for s in sets_counts if s==3)/len(sets_counts)*100, 1) if sets_counts else None,
    }

def get_surface_winrate(surface_data, surface):
    if not surface_data:
        return None
    surf_key = surface
    total_w, total_l = 0, 0
    for year_data in (surface_data if isinstance(surface_data, list) else []):
        for s in year_data.get("surfaces", []):
            if s.get("court","").lower() == surf_key.lower():
                total_w += s.get("courtWins", 0)
                total_l += s.get("courtLosses", 0)
    total = total_w + total_l
    if total < 5:
        return None
    return round(total_w / total * 100, 1)

def get_h2h_stats(h2h_data, player_id):
    if not h2h_data:
        return {}
    p1s = h2h_data.get("player1Stats", {})
    p2s = h2h_data.get("player2Stats", {})
    s   = p1s if p1s.get("id") == player_id else (p2s if p2s.get("id") == player_id else {})
    if not s:
        return {}
    return {
        "h2h_wins":         s.get("matchesWon", 0),
        "h2h_total":        s.get("statMatchesPlayed", 0),
        "h2h_winrate":      round(s.get("matchesWon",0)/max(s.get("statMatchesPlayed",1),1)*100, 1),
        "h2h_tiebreak_pct": s.get("totalTBWinPercentage"),
        "h2h_deciding_set": s.get("decidingSetWinPercentage"),
        "h2h_bp_converted": s.get("breakpointsWonPercentage"),
    }

# ── Signal de marché (cotes comme feature) ────────────────────────────────────

def market_prob(odds_a, odds_b):
    """
    Convertit les cotes Bet365 en probabilités implicites calibrées.
    Retire la marge bookmaker (overround) pour avoir des proba "vraies".
    """
    if not odds_a or not odds_b:
        return None, None
    try:
        raw_a = 1.0 / float(odds_a)
        raw_b = 1.0 / float(odds_b)
        total = raw_a + raw_b  # overround typiquement ~1.05-1.08
        # Normalise pour retirer la marge
        return round(raw_a / total, 4), round(raw_b / total, 4)
    except:
        return None, None

# ── Modèle vainqueur ──────────────────────────────────────────────────────────

def predict_winner(pa, pb, surface, ratings, feat_a, feat_b, h2h_a, odds_data=None):
    surf = SURF_MAP.get(surface, "hard")

    # Elo
    elo_ga = get_elo(ratings, pa, "global")
    elo_gb = get_elo(ratings, pb, "global")
    elo_sa = get_elo(ratings, pa, surf)
    elo_sb = get_elo(ratings, pb, surf)

    p_elo_g = elo_prob(elo_ga, elo_gb)
    p_elo_s = elo_prob(elo_sa, elo_sb)

    # ── Signal marché (cotes Bet365 comme feature) ──────────────────────────
    # Les cotes agrègent beaucoup d'information (blessures, forme, conditions)
    # On les intègre comme signal externe pondéré
    market_a, market_b = market_prob(
        (odds_data or {}).get("player_a_odds"),
        (odds_data or {}).get("player_b_odds")
    )
    has_market = market_a is not None

    # Forme récente
    wr_a     = feat_a.get("winrate_10", 50) / 100
    wr_b     = feat_b.get("winrate_10", 50) / 100
    form_adj = (wr_a - wr_b) * 0.10

    # Surface win rate
    surf_a   = feat_a.get("surface_winrate")
    surf_b   = feat_b.get("surface_winrate")
    surf_adj = (surf_a - surf_b) / 100 * 0.08 if (surf_a and surf_b) else 0

    # H2H
    h2h_adj = 0
    if h2h_a.get("h2h_total", 0) >= 3:
        h2h_wr  = h2h_a.get("h2h_winrate", 50) / 100
        h2h_adj = (h2h_wr - 0.5) * 0.08

    # Service (hold%)
    hold_a  = feat_a.get("hold_pct", 60) / 100
    hold_b  = feat_b.get("hold_pct", 60) / 100
    svc_adj = (hold_a - hold_b) * 0.05

    # Break points
    bp_a    = feat_a.get("bp_saved_pct", 60) / 100
    bp_b    = feat_b.get("bp_saved_pct", 60) / 100
    bp_adj  = (bp_a - bp_b) * 0.03

    # ── Combinaison des signaux ──────────────────────────────────────────────
    if has_market:
        # Avec cotes : le marché est le meilleur prédicteur unique
        # On le pondère fortement mais on garde nos features
        # Poids : Elo surface 25% + Elo global 15% + Marché 35% + Autres 25%
        base = (
            0.25 * p_elo_s +
            0.15 * p_elo_g +
            0.35 * market_a +  # Signal marché fort
            0.25 * (0.5 + form_adj + surf_adj + h2h_adj + svc_adj + bp_adj)
        )
    else:
        # Sans cotes : Elo + features
        # Poids : Elo surface 40% + Elo global 25% + Autres 35%
        base = (
            0.40 * p_elo_s +
            0.25 * p_elo_g +
            0.35 * (0.5 + form_adj + surf_adj + h2h_adj + svc_adj + bp_adj)
        )

    prob_a = max(0.05, min(0.95, base))
    prob_b = 1 - prob_a

    return {
        "prob_a":       round(prob_a, 4),
        "prob_b":       round(prob_b, 4),
        "elo_g_diff":   round(elo_ga - elo_gb),
        "elo_s_diff":   round(elo_sa - elo_sb),
        "market_a":     market_a,
        "market_b":     market_b,
        "has_market":   has_market,
    }

# ── Over/Under jeux ───────────────────────────────────────────────────────────

# Baselines moyennes de jeux par match par surface (historique TML)
SURFACE_BASELINES = {
    "grass": 19.5,   # Gazon : matchs rapides, gros serveurs
    "clay":  23.5,   # Terre : longs échanges
    "hard":  21.5,   # Dur : intermédiaire
}

def predict_over_under(feat_a, feat_b, surface, h2h_data, elo_ratings, pa, pb):
    surf    = SURF_MAP.get(surface, "hard")
    base_ou = SURFACE_BASELINES.get(surf, 21.5)

    # Hold% des deux joueurs → plus les 2 holdent, plus il y a de jeux
    hold_a = feat_a.get("hold_pct", 65) / 100
    hold_b = feat_b.get("hold_pct", 65) / 100

    # Formule : E[jeux] = f(hold_A, hold_B)
    # Si hold_A=0.7 et hold_B=0.7 → beaucoup de jeux
    # Si hold_A=0.5 et hold_B=0.5 → peu de jeux (beaucoup de breaks)
    avg_hold   = (hold_a + hold_b) / 2
    hold_adj   = (avg_hold - 0.65) * 15  # +/-7.5 jeux max

    # Stats TML/MCP enrichies
    elo_a_stats = get_elo_stats(elo_ratings, pa)
    elo_b_stats = get_elo_stats(elo_ratings, pb)

    # Hold% par surface depuis TML (plus précis)
    surf_hold_a = (elo_a_stats.get("by_surface") or {}).get(surf, {}).get("hold_pct")
    surf_hold_b = (elo_b_stats.get("by_surface") or {}).get(surf, {}).get("hold_pct")
    if surf_hold_a and surf_hold_b:
        avg_surf_hold = (surf_hold_a + surf_hold_b) / 200
        hold_adj = (avg_surf_hold - 0.65) * 15  # remplace avec données surface

    # Moyenne des jeux récents
    avg_g_a = feat_a.get("avg_games")
    avg_g_b = feat_b.get("avg_games")
    hist_adj = 0
    if avg_g_a and avg_g_b:
        hist_avg  = (avg_g_a + avg_g_b) / 2
        hist_adj  = (hist_avg - base_ou) * 0.3

    expected_games = round(base_ou + hold_adj + hist_adj, 1)
    line           = round(expected_games * 2) / 2  # arrondi à 0.5

    # Probabilité Over/Under
    spread   = expected_games - line
    prob_over  = max(0.25, min(0.75, 0.5 + spread * 0.08))
    prob_under = 1 - prob_over

    if prob_over > 0.58:
        rec = "OVER"
        conf_ou = min(4, 2 + round((prob_over - 0.55) * 20))
    elif prob_under > 0.58:
        rec = "UNDER"
        conf_ou = min(4, 2 + round((prob_under - 0.55) * 20))
    else:
        rec     = "NEUTRE"
        conf_ou = 1

    return {
        "expected_games": expected_games,
        "line":           line,
        "prob_over":      round(prob_over, 3),
        "prob_under":     round(prob_under, 3),
        "recommendation": rec,
        "confidence":     conf_ou,
    }

# ── 2 sets vs 3 sets ──────────────────────────────────────────────────────────

def predict_sets(elo_diff, feat_a, feat_b, h2h_data):
    # Base : plus l'écart Elo est grand, plus probable 2 sets
    base_2sets = 0.50 + min(0.20, abs(elo_diff) / 1000)

    # % historique de matchs en 2 sets
    p3_a = feat_a.get("pct_3sets")
    p3_b = feat_b.get("pct_3sets")
    form_adj = 0
    if p3_a and p3_b:
        avg_3sets = (p3_a + p3_b) / 200
        form_adj  = (0.35 - avg_3sets) * 0.15

    # H2H
    h2h_adj = 0
    if h2h_data:
        p1s = h2h_data.get("player1Stats", {})
        if p1s:
            b3 = p1s.get("bestOfThreeWonPercentage", 55)
            h2h_adj = (1 - b3/100 - 0.45) * 0.10

    prob_2sets = min(0.85, max(0.30, base_2sets + form_adj + h2h_adj))

    if prob_2sets > 0.60:
        rec  = "2 SETS"
        conf = min(4, 2 + round((prob_2sets - 0.55) * 20))
    elif prob_2sets < 0.45:
        rec  = "3 SETS"
        conf = min(4, 2 + round((0.45 - prob_2sets) * 20))
    else:
        rec  = "NEUTRE"
        conf = 1

    return {
        "prob_2sets":     round(prob_2sets, 4),
        "prob_3sets":     round(1-prob_2sets, 4),
        "recommendation": rec,
        "confidence":     conf,
    }

# ── Indice de confiance global ────────────────────────────────────────────────

def confidence_score(elo_diff, has_surface_data, has_h2h, has_form,
                     has_odds, has_tml_stats, n_features):
    score = 1.0
    if abs(elo_diff) > 150: score += 1.0
    elif abs(elo_diff) > 80: score += 0.5
    if has_surface_data: score += 0.5
    if has_h2h:          score += 0.5
    if has_form:         score += 0.5
    if has_odds:         score += 0.5   # cotes = signal fort
    if has_tml_stats:    score += 0.5   # stats TML/MCP disponibles
    if n_features >= 6:  score += 0.5
    return min(5, round(score))

# ── Edge & Kelly ──────────────────────────────────────────────────────────────

def compute_edge(model_prob, market_odds):
    if not market_odds or market_odds <= 1.0:
        return None
    return round((model_prob - 1.0/market_odds)*100, 2)

def compute_kelly(prob, odds):
    if not odds or odds <= 1.0:
        return 0.0
    b = odds-1; q = 1-prob
    return round(max(0.0, min(KELLY_MAX, KELLY_K*((b*prob-q)/b)*100)), 2)

# ── Pipeline principal ────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=== run_model.py ===")

    ratings       = load_elo()
    fixtures_data = json.loads(FIXTURES_PATH.read_text()) if FIXTURES_PATH.exists() else {}
    fixtures      = fixtures_data.get("fixtures", [])

    print(f"  Elo : {len(ratings)} joueurs")
    print(f"  Fixtures : {len(fixtures)}")

    predictions = []
    ev_count    = 0
    total_kelly = 0.0

    for f in fixtures:
        pa = f.get("player_a","")
        pb = f.get("player_b","")
        if not pa or not pb:
            continue

        surface   = f.get("surface","Hard")
        p1_id     = f.get("player1_id")
        p2_id     = f.get("player2_id")
        data_a    = f.get("player_a_data", {})
        data_b    = f.get("player_b_data", {})
        odds_data = f.get("odds")

        # Features API
        svc_a    = get_service_stats(data_a)
        svc_b    = get_service_stats(data_b)
        form_a   = get_form(data_a.get("past_matches", []))
        form_b   = get_form(data_b.get("past_matches", []))
        surf_wr_a = get_surface_winrate(data_a.get("surface", []), surface)
        surf_wr_b = get_surface_winrate(data_b.get("surface", []), surface)

        # Stats TML/MCP depuis elo_ratings (enrichissement)
        elo_stats_a = get_elo_stats(ratings, pa)
        elo_stats_b = get_elo_stats(ratings, pb)

        # Hold% : priorité TML/MCP sur API (plus fiable car plus de données)
        hold_a_tml = elo_stats_a.get("hold_pct")
        hold_b_tml = elo_stats_b.get("hold_pct")

        feat_a = {
            **svc_a, **form_a,
            "surface_winrate": surf_wr_a,
            "hold_pct":    hold_a_tml or svc_a.get("hold_pct", 60),
            "bp_saved_pct": elo_stats_a.get("bp_saved_pct") or svc_a.get("bp_saved_pct", 60),
        }
        feat_b = {
            **svc_b, **form_b,
            "surface_winrate": surf_wr_b,
            "hold_pct":    hold_b_tml or svc_b.get("hold_pct", 60),
            "bp_saved_pct": elo_stats_b.get("bp_saved_pct") or svc_b.get("bp_saved_pct", 60),
        }

        h2h_data = f.get("h2h", {})
        h2h_a    = get_h2h_stats(h2h_data, p1_id) if p1_id else {}

        # Prédictions
        winner_pred = predict_winner(pa, pb, surface, ratings, feat_a, feat_b, h2h_a, odds_data)
        ou_pred     = predict_over_under(feat_a, feat_b, surface, h2h_data, ratings, pa, pb)
        sets_pred   = predict_sets(winner_pred["elo_g_diff"], feat_a, feat_b, h2h_data)

        # Favori
        if winner_pred["prob_a"] >= winner_pred["prob_b"]:
            fav, opp  = pa, pb
            fav_prob  = winner_pred["prob_a"]
            fav_key   = "player_a"
            fav_odds  = (odds_data or {}).get("player_a_odds")
        else:
            fav, opp  = pb, pa
            fav_prob  = winner_pred["prob_b"]
            fav_key   = "player_b"
            fav_odds  = (odds_data or {}).get("player_b_odds")

        fair_odds = round(1.0/fav_prob, 2)
        has_odds  = fav_odds is not None
        edge      = compute_edge(fav_prob, fav_odds) if has_odds else None
        stake     = compute_kelly(fav_prob, fav_odds) if (has_odds and edge and edge > 0) else 0.0

        has_tml   = hold_a_tml is not None or hold_b_tml is not None
        n_feat    = sum(1 for v in feat_a.values() if v is not None)
        conf      = confidence_score(
            winner_pred["elo_g_diff"],
            surf_wr_a is not None,
            bool(h2h_a.get("h2h_total", 0) >= 3),
            bool(form_a.get("wins_10")),
            has_odds,
            has_tml,
            n_feat
        )

        ev_status = "play" if (has_odds and edge and edge >= EDGE_MIN) else "skip"
        if ev_status == "play":
            ev_count    += 1
            total_kelly += stake

        # Raison
        reasons = []
        elo_d = winner_pred["elo_s_diff"]
        if abs(elo_d) > 50:
            surf_name = surface.lower()
            reasons.append(f"Elo {surf_name} {'+' if elo_d>0 else ''}{elo_d}")
        if surf_wr_a and surf_wr_b:
            diff = round(surf_wr_a - surf_wr_b, 1)
            if abs(diff) > 5:
                reasons.append(f"Win rate surface {'+' if diff>0 else ''}{diff}%")
        if h2h_a.get("h2h_total", 0) >= 3:
            reasons.append(f"H2H {h2h_a['h2h_wins']}/{h2h_a['h2h_total']}")
        if winner_pred["has_market"] and edge:
            mkt_signal = "marché aligné" if edge > 0 else "contre marché"
            reasons.append(mkt_signal)
        if not reasons:
            reasons.append("Léger avantage Elo")

        predictions.append({
            "id":              f"{f['date']}_{pa.replace(' ','_')}_{pb.replace(' ','_')}",
            "player_a":        pa,
            "player_b":        pb,
            "favorite":        fav_key,
            "tournament":      f.get("tournament",""),
            "tournament_rank": f.get("tournament_rank",""),
            "surface":         surface,
            "round":           f.get("round",""),
            "time":            f.get("time","TBD"),
            "date":            f.get("date",""),
            "winner": {
                "prob_a":      winner_pred["prob_a"],
                "prob_b":      winner_pred["prob_b"],
                "favorite":    fav_key,
                "confidence":  conf,
                "fair_odds":   fair_odds,
                "market_odds": fav_odds,
                "edge_pct":    edge,
                "kelly_pct":   stake,
                "has_odds":    has_odds,
                "ev_status":   ev_status,
                "reason":      " · ".join(reasons)[:100],
                "market_prob": winner_pred.get("market_a") if fav_key=="player_a" else winner_pred.get("market_b"),
            },
            "over_under": ou_pred,
            "sets":       sets_pred,
            "features": {
                "elo_global_diff":  winner_pred["elo_g_diff"],
                "elo_surface_diff": winner_pred["elo_s_diff"],
                "hold_pct_a":       feat_a.get("hold_pct"),
                "hold_pct_b":       feat_b.get("hold_pct"),
                "winrate_10_a":     feat_a.get("winrate_10"),
                "winrate_10_b":     feat_b.get("winrate_10"),
                "surf_winrate_a":   surf_wr_a,
                "surf_winrate_b":   surf_wr_b,
                "h2h_total":        h2h_a.get("h2h_total", 0),
                "h2h_wins_a":       h2h_a.get("h2h_wins", 0),
                "avg_games_a":      feat_a.get("avg_games"),
                "avg_games_b":      feat_b.get("avg_games"),
                "market_prob_a":    winner_pred.get("market_a"),
                "bp_saved_a":       feat_a.get("bp_saved_pct"),
                "bp_saved_b":       feat_b.get("bp_saved_pct"),
            }
        })

    # Tri : EV+ en premier, puis confiance décroissante
    predictions.sort(key=lambda x: (
        -1 if x["winner"]["ev_status"]=="play" else 0,
        -x["winner"]["confidence"],
        -(x["winner"]["edge_pct"] or -99)
    ))

    out = {
        "generated_at":  datetime.now().isoformat(),
        "date":          datetime.now().strftime("%Y-%m-%d"),
        "model_version": "2.1.0",
        "summary": {
            "matches_analysed":  len(predictions),
            "ev_plus_count":     ev_count,
            "total_kelly_pct":   round(total_kelly, 1),
            "matches_with_odds": sum(1 for p in predictions if p["winner"]["has_odds"]),
        },
        "matches": predictions,
    }

    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"\n  {len(predictions)} matchs analysés")
    print(f"  {ev_count} paris EV+ (edge ≥ {EDGE_MIN}%)")
    print(f"  Sauvegardé → {OUT_PATH}")
