"""
scripts/run_model.py
Prédit pour chaque match :
1. Vainqueur (probabilité + indice de confiance)
2. Over/Under jeux (nombre total de jeux)
3. 2 sets vs 3 sets
"""
import json
from pathlib import Path
from datetime import datetime
from collections import defaultdict

ELO_PATH      = Path("data/elo_ratings.json")
FIXTURES_PATH = Path("data/fixtures.json")
OUT_PATH      = Path("data/predictions.json")
OUT_PATH.parent.mkdir(exist_ok=True)

EDGE_MIN  = 5.0
KELLY_K   = 0.25
KELLY_MAX = 3.5

SURF_MAP  = {"Grass":"grass","Clay":"clay","Hard":"hard","I.hard":"hard","Carpet":"hard"}

# ── Elo ───────────────────────────────────────────────────────────────────────

def load_elo():
    if not ELO_PATH.exists(): return {}
    return json.loads(ELO_PATH.read_text()).get("ratings", {})

def get_elo(ratings, name, surface="global"):
    key = f"elo_{surface}" if surface != "global" else "elo_global"
    if name in ratings:
        return ratings[name].get(key, ratings[name].get("elo_global", 1500))
    # Recherche partielle
    nl = name.lower()
    for n, r in ratings.items():
        if nl in n.lower() or n.lower() in nl:
            return r.get(key, r.get("elo_global", 1500))
    return 1500

def elo_prob(ra, rb):
    return 1.0 / (1.0 + 10**((rb-ra)/400))

# ── Features depuis API data ──────────────────────────────────────────────────

def parse_score(result):
    """Parse '6-3 7-5' → nombre de jeux total et nombre de sets."""
    if not result:
        return None, None
    sets = result.strip().split()
    total_games = 0
    n_sets = 0
    for s in sets:
        s = s.split("(")[0]  # enlève tie-break ex: "7-6(3)"
        if "-" in s:
            try:
                a, b = s.split("-")
                total_games += int(a) + int(b)
                n_sets += 1
            except:
                pass
    return total_games if total_games > 0 else None, n_sets if n_sets > 0 else None

def get_service_stats(player_data):
    """Extrait les stats de service depuis les données API."""
    stats = player_data.get("stats", {})
    if not stats:
        return {}

    svc = stats.get("serviceStats", {})
    rtn = stats.get("rtnStats", {})
    bp_svc = stats.get("breakPointsServeStats", {})
    bp_rtn = stats.get("breakPointsRtnStats", {})

    result = {}

    # First serve %
    fs = svc.get("firstServeGm", 0)
    fs_of = svc.get("firstServeOfGm", 1)
    if fs_of > 0:
        result["first_serve_pct"] = round(fs / fs_of * 100, 1)

    # Win on 1st serve %
    w1s = svc.get("winningOnFirstServeGm", 0)
    if fs > 0:
        result["win_1st_serve_pct"] = round(w1s / fs * 100, 1)

    # Win on 2nd serve %
    w2s = svc.get("winningOnSecondServeGm", 0)
    w2s_of = svc.get("winningOnSecondServeOfGm", 1)
    if w2s_of > 0:
        result["win_2nd_serve_pct"] = round(w2s / w2s_of * 100, 1)

    # Hold % approximatif
    if "first_serve_pct" in result and "win_1st_serve_pct" in result and "win_2nd_serve_pct" in result:
        fs_p  = result["first_serve_pct"] / 100
        w1s_p = result["win_1st_serve_pct"] / 100
        w2s_p = result["win_2nd_serve_pct"] / 100
        result["hold_pct"] = round((fs_p * w1s_p + (1-fs_p) * w2s_p) * 100, 1)

    # Return win %
    rw = rtn.get("winningOnFirstServeGm", 0)
    rw_of = rtn.get("firstServeGm", 1)
    if rw_of > 0:
        result["return_win_pct"] = round((1 - rw/rw_of) * 100, 1)

    # BP saved %
    bpf = bp_svc.get("breakPointFacedGm", 0)
    bps = bp_svc.get("breakPointSavedGm", 0)
    if bpf > 0:
        result["bp_saved_pct"] = round(bps/bpf*100, 1)

    # BP converted %
    bpc = bp_rtn.get("breakPointChanceGm", 0)
    bpw = bp_rtn.get("breakPointWonGm", 0)
    if bpc > 0:
        result["bp_converted_pct"] = round(bpw/bpc*100, 1)

    return result

def get_form(past_matches):
    """Calcule la forme depuis les derniers matchs."""
    if not past_matches:
        return {}

    wins, losses = 0, 0
    games_total  = []
    sets_counts  = []

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
        "wins_10":        wins,
        "losses_10":      losses,
        "winrate_10":     round(wins/total*100, 1) if total > 0 else 50.0,
        "avg_games":      round(sum(games_total)/len(games_total), 1) if games_total else None,
        "pct_3sets":      round(sum(1 for s in sets_counts if s==3)/len(sets_counts)*100, 1) if sets_counts else None,
    }

def get_surface_winrate(surface_data, surface):
    """Win rate sur cette surface depuis getPlayerSurfaceSummary."""
    if not surface_data:
        return None

    surf_key = {"Grass":"Grass","Clay":"Clay","Hard":"Hard","I.hard":"I.hard"}.get(surface, surface)

    total_w, total_l = 0, 0
    for year_data in (surface_data if isinstance(surface_data, list) else []):
        for s in year_data.get("surfaces", []):
            if s.get("court", "").lower() == surf_key.lower():
                total_w += s.get("courtWins", 0)
                total_l += s.get("courtLosses", 0)

    total = total_w + total_l
    if total < 5:
        return None
    return round(total_w / total * 100, 1)

def get_h2h_stats(h2h_data, player_id):
    """Extrait les stats H2H pour un joueur spécifique."""
    if not h2h_data:
        return {}

    # Détermine si le joueur est p1 ou p2
    p1_stats = h2h_data.get("player1Stats", {})
    p2_stats = h2h_data.get("player2Stats", {})

    if p1_stats.get("id") == player_id:
        s = p1_stats
    elif p2_stats.get("id") == player_id:
        s = p2_stats
    else:
        return {}

    return {
        "h2h_wins":           s.get("matchesWon", 0),
        "h2h_total":          s.get("statMatchesPlayed", 0),
        "h2h_winrate":        round(s.get("matchesWon",0)/s.get("statMatchesPlayed",1)*100,1),
        "h2h_hold_pct":       s.get("winningOnFirstServePercentage"),
        "h2h_return_pct":     s.get("returnPtsWinPercentage"),
        "h2h_bp_converted":   s.get("breakpointsWonPercentage"),
        "h2h_deciding_set":   s.get("decidingSetWinPercentage"),
        "h2h_tiebreak_pct":   s.get("totalTBWinPercentage"),
        "h2h_avg_games":      None,  # calculable depuis gamesWon/matchesPlayed
        "h2h_pct_3sets":      None,
    }

# ── Modèle vainqueur ──────────────────────────────────────────────────────────

def predict_winner(pa, pb, surface, ratings, feat_a, feat_b, h2h_a):
    surf = SURF_MAP.get(surface, "hard")

    # Elo
    elo_ga = get_elo(ratings, pa, "global")
    elo_gb = get_elo(ratings, pb, "global")
    elo_sa = get_elo(ratings, pa, surf)
    elo_sb = get_elo(ratings, pb, surf)

    p_elo_g = elo_prob(elo_ga, elo_gb)
    p_elo_s = elo_prob(elo_sa, elo_sb)

    # Forme
    wr_a = feat_a.get("winrate_10", 50) / 100
    wr_b = feat_b.get("winrate_10", 50) / 100
    form_adj = (wr_a - wr_b) * 0.15

    # Surface win rate
    surf_a = feat_a.get("surface_winrate")
    surf_b = feat_b.get("surface_winrate")
    surf_adj = 0
    if surf_a and surf_b:
        surf_adj = (surf_a - surf_b) / 100 * 0.10

    # H2H
    h2h_adj = 0
    h2h_total = h2h_a.get("h2h_total", 0)
    if h2h_total >= 3:
        h2h_wr = h2h_a.get("h2h_winrate", 50) / 100
        h2h_adj = (h2h_wr - 0.5) * 0.10

    # Service
    hold_a = feat_a.get("hold_pct", 60) / 100
    hold_b = feat_b.get("hold_pct", 60) / 100
    svc_adj = (hold_a - hold_b) * 0.05

    prob = max(0.05, min(0.95,
        0.40 * p_elo_g +
        0.35 * p_elo_s +
        form_adj + surf_adj + h2h_adj + svc_adj
    ))

    return {
        "prob_a": round(prob, 4),
        "prob_b": round(1-prob, 4),
        "elo_g_diff": round(elo_ga - elo_gb),
        "elo_s_diff": round(elo_sa - elo_sb),
    }

# ── Modèle Over/Under ─────────────────────────────────────────────────────────

def predict_over_under(feat_a, feat_b, surface, h2h_data):
    """
    Prédit le nombre total de jeux attendus.
    Formule : basée sur hold% des deux joueurs
    Un match avec hold% élevés → plus de jeux (services tenus)
    """
    hold_a = feat_a.get("hold_pct", 65) / 100
    hold_b = feat_b.get("hold_pct", 65) / 100

    # Nombre de jeux attendus dans un set
    # Si les deux joueurs holdent bien → plus de jeux (6-4, 7-5...)
    # Si beaucoup de breaks → moins de jeux (6-2, 6-1...)
    avg_hold = (hold_a + hold_b) / 2

    # Ligne de base par surface
    base = {"Grass": 20.5, "Clay": 22.5, "Hard": 21.5, "I.hard": 21.5}.get(surface, 21.5)

    # Ajustement hold
    # Hold moyen 65% → ligne de base
    # Chaque 1% de hold supplémentaire → +0.2 jeux
    hold_adj = (avg_hold - 0.65) * 20

    # Ajustement H2H si disponible
    h2h_adj = 0
    if h2h_data:
        p1s = h2h_data.get("player1Stats", {})
        p2s = h2h_data.get("player2Stats", {})
        if p1s and p2s:
            g1 = p1s.get("gamesWon", 0)
            g2 = p2s.get("gamesWon", 0)
            n  = p1s.get("statMatchesPlayed", 0)
            if n > 0:
                avg_h2h_games = (g1 + g2) / n
                h2h_adj = (avg_h2h_games - base) * 0.3

    expected_games = base + hold_adj + h2h_adj

    # Ligne Over/Under la plus proche (arrondi au .5)
    line = round(expected_games * 2) / 2

    # Probabilité Over
    # Si expected_games > line → probabilité Over > 50%
    diff = expected_games - line
    prob_over = max(0.30, min(0.70, 0.50 + diff * 0.08))

    return {
        "expected_games":  round(expected_games, 1),
        "line":            line,
        "prob_over":       round(prob_over, 4),
        "prob_under":      round(1-prob_over, 4),
        "recommendation":  "OVER" if prob_over > 0.55 else ("UNDER" if prob_over < 0.45 else "NEUTRE"),
    }

# ── Modèle 2 sets vs 3 sets ───────────────────────────────────────────────────

def predict_sets(elo_diff, feat_a, feat_b, h2h_data):
    """
    Prédit la probabilité de 2 sets vs 3 sets.
    Plus l'écart Elo est grand → plus probable 2 sets.
    """
    # Base : ~55% des matchs ATP se terminent en 2 sets
    base_2sets = 0.55

    # Ajustement Elo
    elo_adj = min(0.20, abs(elo_diff) / 400 * 0.25)

    # Ajustement forme
    wr_a = feat_a.get("winrate_10", 50)
    wr_b = feat_b.get("winrate_10", 50)
    form_diff = abs(wr_a - wr_b)
    form_adj  = form_diff / 100 * 0.05

    # H2H 3 sets history
    h2h_adj = 0
    if h2h_data:
        p1s = h2h_data.get("player1Stats", {})
        if p1s:
            b3_pct = (1 - p1s.get("bestOfThreeWonPercentage",55)/100)
            h2h_adj = (b3_pct - 0.45) * 0.10

    prob_2sets = min(0.85, base_2sets + elo_adj + form_adj + h2h_adj)

    return {
        "prob_2sets": round(prob_2sets, 4),
        "prob_3sets": round(1-prob_2sets, 4),
        "recommendation": "2 SETS" if prob_2sets > 0.60 else ("3 SETS" if prob_2sets < 0.45 else "NEUTRE"),
    }

# ── Indice de confiance ───────────────────────────────────────────────────────

def confidence_score(elo_diff, has_surface_data, has_h2h, has_form, has_odds, n_features):
    """
    Score de 1 à 5 étoiles basé sur la qualité des données.
    """
    score = 1.0

    # Écart Elo significatif
    if abs(elo_diff) > 150: score += 1.0
    elif abs(elo_diff) > 80: score += 0.5

    # Données disponibles
    if has_surface_data: score += 0.5
    if has_h2h:          score += 0.5
    if has_form:         score += 0.5
    if has_odds:         score += 0.5

    # Nombre de features
    if n_features >= 6: score += 0.5

    stars = min(5, round(score))
    return stars

# ── Edge & Kelly ──────────────────────────────────────────────────────────────

def compute_edge(model_prob, market_odds):
    if not market_odds or market_odds <= 1.0:
        return None
    return round((model_prob - 1.0/market_odds) * 100, 2)

def compute_kelly(prob, odds):
    if not odds or odds <= 1.0:
        return 0.0
    b = odds-1; q = 1-prob
    return round(max(0.0, min(KELLY_MAX, KELLY_K*((b*prob-q)/b)*100)), 2)

# ── Pipeline principal ────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=== run_model.py ===")

    ratings  = load_elo()
    fixtures_data = json.loads(FIXTURES_PATH.read_text()) if FIXTURES_PATH.exists() else {}
    fixtures = fixtures_data.get("fixtures", [])

    print(f"  Elo : {len(ratings)} joueurs")
    print(f"  Fixtures : {len(fixtures)}")

    predictions = []
    ev_count    = 0
    total_kelly = 0.0

    for f in fixtures:
        pa = f.get("player_a", "")
        pb = f.get("player_b", "")
        if not pa or not pb:
            continue

        surface   = f.get("surface", "Hard")
        p1_id     = f.get("player1_id")
        p2_id     = f.get("player2_id")

        # Données joueurs
        data_a = f.get("player_a_data", {})
        data_b = f.get("player_b_data", {})

        svc_a = get_service_stats(data_a)
        svc_b = get_service_stats(data_b)

        form_a = get_form(data_a.get("past_matches", []))
        form_b = get_form(data_b.get("past_matches", []))

        surf_wr_a = get_surface_winrate(data_a.get("surface", []), surface)
        surf_wr_b = get_surface_winrate(data_b.get("surface", []), surface)

        feat_a = {**svc_a, **form_a, "surface_winrate": surf_wr_a}
        feat_b = {**svc_b, **form_b, "surface_winrate": surf_wr_b}

        # H2H
        h2h_data = f.get("h2h", {})
        h2h_a    = get_h2h_stats(h2h_data, p1_id) if p1_id else {}

        # Prédictions
        winner_pred = predict_winner(pa, pb, surface, ratings, feat_a, feat_b, h2h_a)
        ou_pred     = predict_over_under(feat_a, feat_b, surface, h2h_data)
        sets_pred   = predict_sets(winner_pred["elo_g_diff"], feat_a, feat_b, h2h_data)

        # Favori
        if winner_pred["prob_a"] >= winner_pred["prob_b"]:
            fav, opp  = pa, pb
            fav_prob  = winner_pred["prob_a"]
            fav_key   = "player_a"
            fav_odds  = (f.get("odds") or {}).get("player_a_odds")
        else:
            fav, opp  = pb, pa
            fav_prob  = winner_pred["prob_b"]
            fav_key   = "player_b"
            fav_odds  = (f.get("odds") or {}).get("player_b_odds")

        fair_odds = round(1.0/fav_prob, 2)

        # Edge & Kelly
        has_odds = fav_odds is not None
        edge     = compute_edge(fav_prob, fav_odds) if has_odds else None
        stake    = compute_kelly(fav_prob, fav_odds) if (has_odds and edge and edge > 0) else 0.0

        # Confiance
        n_feat = sum(1 for v in feat_a.values() if v is not None)
        conf   = confidence_score(
            winner_pred["elo_g_diff"],
            surf_wr_a is not None,
            bool(h2h_a.get("h2h_total", 0) >= 3),
            bool(form_a.get("wins_10")),
            has_odds,
            n_feat
        )

        # EV status
        ev_status = "play" if (has_odds and edge and edge >= EDGE_MIN) else "skip"
        if ev_status == "play":
            ev_count    += 1
            total_kelly += stake

        # Raison
        reasons = []
        elo_d = winner_pred["elo_s_diff"]
        if abs(elo_d) > 50:
            reasons.append(f"Elo {surface.lower()} {'+' if elo_d>0 else ''}{elo_d}")
        if surf_wr_a and surf_wr_b:
            diff = round(surf_wr_a - surf_wr_b, 1)
            if abs(diff) > 5:
                reasons.append(f"Win rate surface {'+' if diff>0 else ''}{diff}%")
        if h2h_a.get("h2h_total", 0) >= 3:
            reasons.append(f"H2H {h2h_a['h2h_wins']}/{h2h_a['h2h_total']}")
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

            # Vainqueur
            "winner": {
                "prob_a":       winner_pred["prob_a"],
                "prob_b":       winner_pred["prob_b"],
                "favorite":     fav_key,
                "confidence":   conf,
                "fair_odds":    fair_odds,
                "market_odds":  fav_odds,
                "edge_pct":     edge,
                "kelly_pct":    stake,
                "has_odds":     has_odds,
                "ev_status":    ev_status,
                "reason":       " · ".join(reasons)[:80],
            },

            # Over/Under
            "over_under": {
                **ou_pred,
                "confidence": max(1, conf - 1),
            },

            # Sets
            "sets": {
                **sets_pred,
                "confidence": max(1, conf - 1),
            },

            # Features clés
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
            }
        })

    # Tri : EV+ en premier, puis confiance
    predictions.sort(key=lambda x: (
        -1 if x["winner"]["ev_status"]=="play" else 0,
        -x["winner"]["confidence"],
        -(x["winner"]["edge_pct"] or -99)
    ))

    out = {
        "generated_at":  datetime.now().isoformat(),
        "date":          datetime.now().strftime("%Y-%m-%d"),
        "model_version": "2.0.0",
        "summary": {
            "matches_analysed": len(predictions),
            "ev_plus_count":    ev_count,
            "total_kelly_pct":  round(total_kelly, 1),
            "matches_with_odds": sum(1 for p in predictions if p["winner"]["has_odds"]),
        },
        "matches": predictions,
    }

    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"\n  {len(predictions)} matchs analysés")
    print(f"  {ev_count} paris EV+ (edge ≥ {EDGE_MIN}%)")
    print(f"  Sauvegardé → {OUT_PATH}")
