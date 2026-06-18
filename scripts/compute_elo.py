"""
scripts/compute_elo.py
Calcule les Elo depuis TML-Database (ATP) + MatchChartingProject (WTA stats)
Elo global + par surface (hard, clay, grass)
Stats de service : hold%, ace rate, break% depuis TML (ATP) et MCP (WTA)
"""
import json, glob, zipfile, io, requests
from pathlib import Path
from datetime import datetime
from collections import defaultdict
import pandas as pd

OUT     = Path("data/elo_ratings.json")
MCP_URL = "https://github.com/JeffSackmann/tennis_MatchChartingProject/archive/refs/heads/master.zip"
OUT.parent.mkdir(exist_ok=True)

SURF = {
    "Hard":"hard","Clay":"clay","Grass":"grass",
    "Carpet":"hard","I.hard":"hard","Indoor":"hard",
    "hard":"hard","clay":"clay","grass":"grass",
}

def expected(ra, rb):
    return 1.0 / (1.0 + 10**((rb-ra)/400))

def k_factor(level):
    l = str(level).upper()
    if any(x in l for x in ["G","GRAND","SLAM"]): return 40
    if any(x in l for x in ["M","1000","MASTERS"]): return 36
    if "500" in l: return 34
    return 32

# ── Stats de service depuis TML-Database ──────────────────────────────────────

def compute_service_stats_tml(df):
    """
    Calcule hold%, ace rate, break% par joueur depuis TML-Database.
    Utilise les 3 dernières années de données pour être représentatif.
    """
    stats = defaultdict(lambda: {
        "sv_pts":0,"sv_1st_in":0,"sv_1st_won":0,"sv_2nd_won":0,
        "sv_2nd_pts":0,"aces":0,"df":0,"bp_faced":0,"bp_saved":0,
        "by_surface": defaultdict(lambda: {
            "sv_pts":0,"sv_1st_in":0,"sv_1st_won":0,"sv_2nd_won":0,
            "sv_2nd_pts":0,"aces":0,"sv_gms":0,"bp_faced":0,"bp_saved":0,
            "matches":0,"wins":0
        })
    })

    # Colonnes TML disponibles
    svc_cols = ["w_svpt","w_1stIn","w_1stWon","w_2ndWon","w_ace","w_df",
                "w_SvGms","w_bpSaved","w_bpFaced",
                "l_svpt","l_1stIn","l_1stWon","l_2ndWon","l_ace","l_df",
                "l_SvGms","l_bpSaved","l_bpFaced"]

    # Garder seulement les 3 dernières années
    if "tourney_date" in df.columns:
        df["tourney_date"] = pd.to_datetime(df["tourney_date"].astype(str), errors="coerce")
        cutoff = df["tourney_date"].max() - pd.Timedelta(days=365*3)
        df = df[df["tourney_date"] >= cutoff]

    for col in svc_cols:
        if col not in df.columns:
            df[col] = 0

    for _, row in df.iterrows():
        w    = str(row.get("winner_name","")).strip()
        l    = str(row.get("loser_name","")).strip()
        surf = SURF.get(str(row.get("surface","")).strip(), "hard")
        if not w or not l or w=="nan" or l=="nan":
            continue

        def safe(v):
            try: return float(v) if pd.notna(v) else 0
            except: return 0

        # Stats du gagnant au service
        for player, prefix, won in [(w,"w",True),(l,"l",False)]:
            sv   = safe(row[f"{prefix}_svpt"])
            f1in = safe(row[f"{prefix}_1stIn"])
            f1wn = safe(row[f"{prefix}_1stWon"])
            f2wn = safe(row[f"{prefix}_2ndWon"])
            f2pt = sv - f1in
            ace  = safe(row[f"{prefix}_ace"])
            df_  = safe(row[f"{prefix}_df"])
            bpf  = safe(row[f"{prefix}_bpFaced"])
            bps  = safe(row[f"{prefix}_bpSaved"])
            svgm = safe(row[f"{prefix}_SvGms"])

            s = stats[player]
            s["sv_pts"]   += sv
            s["sv_1st_in"]+= f1in
            s["sv_1st_won"]+= f1wn
            s["sv_2nd_won"]+= f2wn
            s["sv_2nd_pts"]+= f2pt
            s["aces"]     += ace
            s["df"]       += df_
            s["bp_faced"] += bpf
            s["bp_saved"] += bps

            sb = s["by_surface"][surf]
            sb["sv_pts"]   += sv
            sb["sv_1st_in"]+= f1in
            sb["sv_1st_won"]+= f1wn
            sb["sv_2nd_won"]+= f2wn
            sb["sv_2nd_pts"]+= f2pt
            sb["aces"]     += ace
            sb["sv_gms"]   += svgm
            sb["bp_faced"] += bpf
            sb["bp_saved"] += bps
            sb["matches"]  += 1
            if won: sb["wins"] += 1

    return stats

def calc_hold_pct(s):
    """Calcule hold% depuis les stats de service agrégées."""
    sv = s["sv_pts"]
    if sv < 50:
        return None
    f1in = s["sv_1st_in"]
    f1wn = s["sv_1st_won"]
    f2wn = s["sv_2nd_won"]
    f2pt = s["sv_2nd_pts"]
    if f1in <= 0:
        return None
    # P(hold) ≈ P(1stIn)*P(win|1stIn) + P(2nd)*P(win|2nd)
    p1in  = f1in / sv
    pw1   = f1wn / f1in if f1in > 0 else 0
    pw2   = f2wn / f2pt if f2pt > 0 else 0
    return round((p1in*pw1 + (1-p1in)*pw2)*100, 1)

def build_player_stats(svc_stats):
    """Construit le dict de stats final par joueur."""
    result = {}
    for player, s in svc_stats.items():
        hold = calc_hold_pct(s)
        ace_rate = round(s["aces"] / s["sv_pts"] * 100, 2) if s["sv_pts"] > 50 else None
        bp_saved = round(s["bp_saved"] / s["bp_faced"] * 100, 1) if s["bp_faced"] > 10 else None

        by_surf = {}
        for surf, ss in s["by_surface"].items():
            if ss["sv_pts"] < 30:
                continue
            h  = calc_hold_pct(ss)
            ar = round(ss["aces"] / ss["sv_pts"] * 100, 2) if ss["sv_pts"] > 0 else None
            wr = round(ss["wins"] / ss["matches"] * 100, 1) if ss["matches"] > 5 else None
            bps = round(ss["bp_saved"] / ss["bp_faced"] * 100, 1) if ss.get("bp_faced",0) > 5 else None
            by_surf[surf] = {
                "hold_pct": h, "ace_rate": ar,
                "winrate": wr, "bp_saved_pct": bps,
                "matches": ss["matches"]
            }

        result[player] = {
            "hold_pct":    hold,
            "ace_rate":    ace_rate,
            "bp_saved_pct": bp_saved,
            "by_surface":  by_surf,
        }
    return result

# ── Elo depuis TML ────────────────────────────────────────────────────────────

def compute_elo_tml(df, tour="ATP"):
    """Calcule les Elo depuis un DataFrame TML."""
    for col in ["winner_name","loser_name","surface","tourney_level","tourney_date"]:
        if col not in df.columns:
            df[col] = ""

    df["tourney_date"] = pd.to_datetime(df["tourney_date"].astype(str), errors="coerce")
    df = df.dropna(subset=["tourney_date"]).sort_values("tourney_date")

    elo_g, elo_s = {}, {}
    snaps        = {}

    for _, row in df.iterrows():
        w = str(row["winner_name"]).strip()
        l = str(row["loser_name"]).strip()
        if not w or not l or w=="nan" or l=="nan":
            continue

        surf = SURF.get(str(row["surface"]).strip(), "hard")
        K    = k_factor(row["tourney_level"])
        date = row["tourney_date"].strftime("%Y-%m-%d")

        for p in [w,l]:
            if p not in elo_g:
                elo_g[p] = 1500
                elo_s[p] = {"hard":1500,"clay":1500,"grass":1500}

        # Snapshot AVANT le match
        for p in [w,l]:
            snaps[p] = {
                "elo_global": round(elo_g[p]),
                "elo_hard":   round(elo_s[p]["hard"]),
                "elo_clay":   round(elo_s[p]["clay"]),
                "elo_grass":  round(elo_s[p]["grass"]),
                "last_match": date,
                "tour":       tour,
            }

        ew = expected(elo_g[w], elo_g[l])
        elo_g[w] += K*(1-ew)
        elo_g[l] += K*(0-(1-ew))

        ews = expected(elo_s[w][surf], elo_s[l][surf])
        elo_s[w][surf] += K*(1-ews)
        elo_s[l][surf] += K*(0-(1-ews))

    return snaps

# ── MatchChartingProject (WTA stats de service) ───────────────────────────────

def load_mcp_stats():
    """
    Télécharge le MatchChartingProject ZIP et extrait les stats
    de service par joueur (ATP + WTA).
    Retourne un dict {player_name: {hold_pct, ace_rate, ...}}
    """
    print("  Téléchargement MatchChartingProject...")
    try:
        r = requests.get(MCP_URL, timeout=60)
        if r.status_code != 200:
            print(f"  MCP HTTP {r.status_code} — skip")
            return {}
    except Exception as e:
        print(f"  MCP erreur : {e} — skip")
        return {}

    try:
        z = zipfile.ZipFile(io.BytesIO(r.content))
    except:
        print("  MCP ZIP invalide — skip")
        return {}

    # Cherche les fichiers stats dans le ZIP
    stat_files = [f for f in z.namelist() if "stats" in f.lower() and f.endswith(".csv")]
    print(f"  MCP fichiers stats : {len(stat_files)}")

    mcp_stats = defaultdict(lambda: {
        "sv_pts":0,"sv_1st_in":0,"sv_1st_won":0,"sv_2nd_won":0,
        "sv_2nd_pts":0,"aces":0,"tour":""
    })

    for fname in stat_files:
        is_wta = "wta" in fname.lower() or "-W-" in fname
        try:
            with z.open(fname) as f:
                df = pd.read_csv(f, low_memory=False)
        except:
            continue

        # Colonnes MCP attendues
        needed = ["player","svpt","1stIn","1stWon","2ndWon","ace"]
        if not all(c in df.columns for c in needed[:3]):
            continue

        for _, row in df.iterrows():
            player = str(row.get("player","")).strip()
            if not player or player=="nan":
                continue

            def safe(c):
                try: return float(row[c]) if c in df.columns and pd.notna(row[c]) else 0
                except: return 0

            mcp_stats[player]["sv_pts"]   += safe("svpt")
            mcp_stats[player]["sv_1st_in"]+= safe("1stIn")
            mcp_stats[player]["sv_1st_won"]+= safe("1stWon")
            mcp_stats[player]["sv_2nd_won"]+= safe("2ndWon")
            mcp_stats[player]["sv_2nd_pts"]+= safe("svpt") - safe("1stIn")
            mcp_stats[player]["aces"]     += safe("ace")
            mcp_stats[player]["tour"]      = "WTA" if is_wta else "ATP"

    # Calcule hold% et ace rate
    result = {}
    for player, s in mcp_stats.items():
        if s["sv_pts"] < 100:
            continue
        hold = calc_hold_pct(s)
        ace  = round(s["aces"]/s["sv_pts"]*100, 2) if s["sv_pts"] > 0 else None
        result[player] = {
            "hold_pct":  hold,
            "ace_rate":  ace,
            "tour":      s["tour"],
            "source":    "mcp",
        }

    print(f"  MCP stats : {len(result)} joueurs")
    return result

# ── Pipeline principal ────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=== compute_elo.py ===")

    # 1. ATP — TML-Database
    atp_files = sorted(glob.glob("/tmp/tml/*.csv"))
    atp_snaps = {}
    atp_svc   = {}

    if atp_files:
        dfs = []
        for f in atp_files:
            try:
                df = pd.read_csv(f, low_memory=False)
                print(f"  Chargé : {Path(f).name} ({len(df):,} matchs)")
                dfs.append(df)
            except Exception as e:
                print(f"  Erreur {f}: {e}")

        if dfs:
            df_all = pd.concat(dfs, ignore_index=True)
            print(f"  ATP total : {len(df_all):,} matchs")
            atp_snaps = compute_elo_tml(df_all, "ATP")
            print(f"  ATP Elo : {len(atp_snaps)} joueurs")
            svc_stats = compute_service_stats_tml(df_all)
            atp_svc   = build_player_stats(svc_stats)
            print(f"  ATP stats service : {len(atp_svc)} joueurs")
    else:
        print("  Aucun fichier TML — skip ATP")

    # 2. WTA — MatchChartingProject (stats service) + Elo 1500 par défaut
    mcp_stats = load_mcp_stats()

    # 3. Fusion
    all_ratings = {}

    # ATP : Elo depuis TML + stats service depuis TML
    for player, snap in atp_snaps.items():
        svc = atp_svc.get(player, {})
        all_ratings[player] = {
            **snap,
            "hold_pct":       svc.get("hold_pct"),
            "ace_rate":       svc.get("ace_rate"),
            "bp_saved_pct":   svc.get("bp_saved_pct"),
            "by_surface":     svc.get("by_surface", {}),
            "source_elo":     "tml",
            "source_svc":     "tml",
        }

    # WTA : Elo 1500 par défaut + stats service depuis MCP
    wta_count = 0
    for player, mcp in mcp_stats.items():
        if mcp.get("tour") != "WTA":
            continue
        if player not in all_ratings:
            all_ratings[player] = {
                "elo_global": 1500,
                "elo_hard":   1500,
                "elo_clay":   1500,
                "elo_grass":  1500,
                "last_match": "",
                "tour":       "WTA",
                "source_elo": "default",
            }
        all_ratings[player]["hold_pct"]   = mcp.get("hold_pct")
        all_ratings[player]["ace_rate"]   = mcp.get("ace_rate")
        all_ratings[player]["source_svc"] = "mcp"
        wta_count += 1

    print(f"  WTA stats service : {wta_count} joueurs depuis MCP")
    print(f"  Total : {len(all_ratings)} joueurs")

    OUT.write_text(json.dumps({
        "computed_at": datetime.now().isoformat(),
        "count":       len(all_ratings),
        "atp_count":   len(atp_snaps),
        "wta_count":   wta_count,
        "ratings":     all_ratings,
    }, ensure_ascii=False, indent=2))

    print(f"  Sauvegardé → {OUT}")
