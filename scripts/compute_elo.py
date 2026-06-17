"""
scripts/compute_elo.py
Calcule les Elo depuis TML-Database
Elo global + par surface (hard, clay, grass)
"""
import json, glob
from pathlib import Path
from datetime import datetime
import pandas as pd

OUT = Path("data/elo_ratings.json")
OUT.parent.mkdir(exist_ok=True)

SURF = {"Hard":"hard","Clay":"clay","Grass":"grass",
        "Carpet":"hard","I.hard":"hard","Indoor":"hard"}

def expected(ra, rb):
    return 1.0 / (1.0 + 10**((rb-ra)/400))

def k(level):
    l = str(level).upper()
    if "G" in l or "GRAND" in l: return 40
    if "M" in l or "1000" in l:  return 36
    if "500" in l:                return 34
    return 32

def compute():
    files = sorted(glob.glob("/tmp/tml/*.csv"))
    if not files:
        print("  Aucun fichier TML")
        return {}

    dfs = []
    for f in files:
        try:
            df = pd.read_csv(f, low_memory=False)
            dfs.append(df)
        except:
            pass

    if not dfs:
        return {}

    df = pd.concat(dfs, ignore_index=True)
    print(f"  {len(df):,} matchs TML chargés")

    # Normalise les colonnes
    for col in ["winner_name","loser_name","surface","tourney_level","tourney_date"]:
        if col not in df.columns:
            df[col] = ""

    df["tourney_date"] = pd.to_datetime(
        df["tourney_date"].astype(str), errors="coerce"
    )
    df = df.dropna(subset=["tourney_date"]).sort_values("tourney_date")

    elo_g, elo_s = {}, {}
    snaps = {}

    for _, row in df.iterrows():
        w = str(row["winner_name"]).strip()
        l = str(row["loser_name"]).strip()
        if not w or not l or w == "nan" or l == "nan":
            continue

        surf = SURF.get(str(row["surface"]).strip(), "hard")
        K    = k(row["tourney_level"])
        date = row["tourney_date"].strftime("%Y-%m-%d")

        for p in [w, l]:
            if p not in elo_g:
                elo_g[p] = 1500
                elo_s[p] = {"hard":1500,"clay":1500,"grass":1500}

        # Snapshot avant le match
        for p in [w, l]:
            snaps[p] = {
                "elo_global": round(elo_g[p]),
                "elo_hard":   round(elo_s[p]["hard"]),
                "elo_clay":   round(elo_s[p]["clay"]),
                "elo_grass":  round(elo_s[p]["grass"]),
                "last_match": date,
            }

        # Update Elo global
        ew = expected(elo_g[w], elo_g[l])
        elo_g[w] += K*(1-ew)
        elo_g[l] += K*(0-(1-ew))

        # Update Elo surface
        ews = expected(elo_s[w][surf], elo_s[l][surf])
        elo_s[w][surf] += K*(1-ews)
        elo_s[l][surf] += K*(0-(1-ews))

    return snaps

if __name__ == "__main__":
    print("=== compute_elo.py ===")
    snaps = compute()
    OUT.write_text(json.dumps({
        "computed_at": datetime.now().isoformat(),
        "count": len(snaps),
        "ratings": snaps,
    }, ensure_ascii=False, indent=2))
    print(f"  {len(snaps)} joueurs → {OUT}")
