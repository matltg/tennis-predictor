# Tennis Predictor v2

Système de prédiction tennis pré-match — vainqueur + Over/Under + sets.

## Sources de données
- **RapidAPI** (tennis-api-atp-wta-itf) : fixtures, stats joueur, H2H, cotes Bet365
- **TML-Database** : historique ATP 2015-2026 pour le calcul Elo
- **MatchChartingProject** : stats avancées point-par-point

## Installation

### 1. GitHub Pages
Settings → Pages → Branch: main · Folder: /docs → Save

### 2. Secrets GitHub
Settings → Secrets → Actions → New secret :
- `RAPIDAPI_KEY` : ta clé RapidAPI (plan Pro)

### 3. Premier run
Actions → Tennis Predictor v2 → Run workflow

## Routine hebdomadaire (optionnel)
Chaque lundi : télécharger ATP/WTA 2026 sur tennis-data.co.uk
et uploader dans `data/tennis_data/` pour enrichir les cotes historiques.

## URL
`https://matltg.github.io/tennis-predictor/`
