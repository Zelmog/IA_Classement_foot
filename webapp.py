"""
IA Classement Foot - Application Web
=====================================

Serveur Flask qui expose l'IA de prédiction via une interface web.
Destiné à être déployé sur un serveur Oracle Cloud.

Usage:
    python webapp.py                    # Démarre sur http://0.0.0.0:5000
    python webapp.py --port 8080        # Port personnalisé
    gunicorn webapp:app -b 0.0.0.0:5000 --workers 2 --timeout 300
"""

import argparse
import json
import threading
import time
from dataclasses import asdict
from typing import Dict, List, Optional

from flask import Flask, jsonify, render_template, request

from modules.config import COMPETITIONS, N_SIMULATIONS, PROMOTION_SPOTS, RELEGATION_SPOTS, TOTAL_MATCHES_PER_TEAM
from modules.models import Fixture, PredictionResult, Team, TeamStats
from modules.predictor import PromotionPredictor
from modules.scraper import (
    compute_team_stats,
    get_calendar_summary,
    get_remaining_fixtures,
    scrape_competition,
)

app = Flask(__name__)

# ── État global par compétition ──────────────────────────────────────
class CompetitionState:
    """Stocke les données d'une compétition."""

    def __init__(self, key: str, name: str, url: str):
        self.key = key
        self.name = name
        self.url = url
        self.teams: List[Team] = []
        self.predictions: Optional[List[PredictionResult]] = None
        self.fixtures: Optional[List[Fixture]] = None
        self.team_stats: Optional[Dict[str, TeamStats]] = None
        self.season_progress: float = 0.0
        self.calendar_summary: Optional[dict] = None
        self.loading = False
        self.last_update: Optional[str] = None
        self.error: Optional[str] = None


# Initialiser les compétitions
states: Dict[str, CompetitionState] = {}
for key, info in COMPETITIONS.items():
    states[key] = CompetitionState(key, info["name"], info["url"])


# ── Fonctions utilitaires ────────────────────────────────────────────
def _load_competition(state: CompetitionState) -> None:
    """Charge toutes les données d'une compétition (scraping + prédiction)."""
    state.loading = True
    state.error = None

    try:
        teams, result_fixtures, calendar_fixtures = scrape_competition(state.url)

        if not teams:
            state.error = "Impossible de charger le classement."
            state.loading = False
            return

        state.teams = teams

        # Détection auto du nombre de matchs
        n_teams = len(teams)
        max_played = max(t.matches_played for t in teams)
        single_round = n_teams - 1
        double_round = 2 * (n_teams - 1)
        total_matches = double_round if max_played > single_round else single_round

        # Stats détaillées
        if result_fixtures:
            played = [f for f in result_fixtures if f.played]
            team_names = [t.name for t in teams]
            state.team_stats = compute_team_stats(played, team_names)

        # Calendrier
        if calendar_fixtures:
            state.fixtures = calendar_fixtures
            state.calendar_summary = get_calendar_summary(calendar_fixtures)

        # Prédiction
        real_fixtures = None
        if state.fixtures:
            real_fixtures = get_remaining_fixtures(state.fixtures)

        predictor = PromotionPredictor(
            teams=teams,
            total_matches=total_matches,
            n_simulations=N_SIMULATIONS,
            promotion_spots=PROMOTION_SPOTS,
            relegation_spots=RELEGATION_SPOTS,
            fixtures=real_fixtures,
            team_stats=state.team_stats,
        )

        state.season_progress = predictor.get_season_progress()
        state.predictions = predictor.simulate()

        state.last_update = time.strftime("%d/%m/%Y %H:%M")

    except Exception as e:
        state.error = str(e)
    finally:
        state.loading = False


def _team_to_dict(team: Team) -> dict:
    return {
        "rank": team.rank,
        "name": team.name,
        "points": team.points,
        "matches_played": team.matches_played,
        "wins": team.wins,
        "draws": team.draws,
        "losses": team.losses,
        "goals_for": team.goals_for,
        "goals_against": team.goals_against,
        "goal_difference": team.goal_difference,
        "points_per_match": round(team.points_per_match, 2),
    }


def _prediction_to_dict(pred: PredictionResult) -> dict:
    return {
        "team_name": pred.team_name,
        "current_rank": pred.current_rank,
        "current_points": pred.current_points,
        "matches_played": pred.matches_played,
        "matches_remaining": pred.matches_remaining,
        "promotion_probability": round(pred.promotion_probability, 1),
        "relegation_probability": round(pred.relegation_probability, 1),
        "avg_final_position": round(pred.avg_final_position, 1),
        "predicted_final_points": round(pred.predicted_final_points, 1),
        "promotion_emoji": pred.promotion_emoji,
        "relegation_emoji": pred.relegation_emoji,
    }


def _stats_to_dict(stats: TeamStats) -> dict:
    return {
        "name": stats.name,
        "form_score": round(stats.form_score, 1),
        "form_label": stats.form_label,
        "home_wins": stats.home_wins,
        "home_draws": stats.home_draws,
        "home_losses": stats.home_losses,
        "home_goals_for": stats.home_goals_for,
        "home_goals_against": stats.home_goals_against,
        "away_wins": stats.away_wins,
        "away_draws": stats.away_draws,
        "away_losses": stats.away_losses,
        "away_goals_for": stats.away_goals_for,
        "away_goals_against": stats.away_goals_against,
        "home_ppg": round(stats.home_ppg, 2),
        "away_ppg": round(stats.away_ppg, 2),
    }


# ── Routes HTML ──────────────────────────────────────────────────────
@app.route("/")
def index():
    """Page d'accueil — redirige vers la première compétition."""
    first_key = next(iter(COMPETITIONS))
    return render_template(
        "index.html",
        competitions=COMPETITIONS,
        current_key=first_key,
        states=states,
    )


@app.route("/<key>/")
def competition(key):
    """Dashboard d'une compétition."""
    if key not in states:
        return render_template("404.html", competitions=COMPETITIONS), 404

    state = states[key]
    # Séparer matchs joués et à venir, triés par date
    upcoming = []
    recent = []
    if state.fixtures:
        def _date_sort_key(f):
            """Parse DD/MM/YYYY into sortable tuple."""
            try:
                parts = f.date.split()[0].split("/")
                return (int(parts[2]), int(parts[1]), int(parts[0]))
            except (IndexError, ValueError):
                return (9999, f.matchday, 0)
        upcoming = sorted([f for f in state.fixtures if not f.played], key=_date_sort_key)
        recent = sorted([f for f in state.fixtures if f.played], key=_date_sort_key, reverse=True)

    return render_template(
        "dashboard.html",
        competitions=COMPETITIONS,
        current_key=key,
        state=state,
        teams=[_team_to_dict(t) for t in state.teams],
        predictions=[_prediction_to_dict(p) for p in state.predictions] if state.predictions else [],
        team_stats={name: _stats_to_dict(s) for name, s in state.team_stats.items()} if state.team_stats else {},
        calendar_summary=state.calendar_summary,
        upcoming=upcoming,
        recent=recent,
    )


@app.route("/<key>/equipe/<team_name>")
def team_detail(key, team_name):
    """Page détaillée d'une équipe."""
    if key not in states:
        return render_template("404.html", competitions=COMPETITIONS), 404

    state = states[key]
    team = next((t for t in state.teams if t.name == team_name), None)
    prediction = next((p for p in (state.predictions or []) if p.team_name == team_name), None)
    stats = state.team_stats.get(team_name) if state.team_stats else None

    if not team:
        return render_template("404.html", competitions=COMPETITIONS), 404

    return render_template(
        "team.html",
        competitions=COMPETITIONS,
        current_key=key,
        state=state,
        team=_team_to_dict(team),
        prediction=_prediction_to_dict(prediction) if prediction else None,
        stats=_stats_to_dict(stats) if stats else None,
    )


# ── Routes API ───────────────────────────────────────────────────────
@app.route("/api/<key>/status")
def api_status(key):
    """État de chargement d'une compétition."""
    if key not in states:
        return jsonify({"error": "Compétition inconnue"}), 404
    state = states[key]
    return jsonify({
        "loading": state.loading,
        "has_data": bool(state.teams),
        "last_update": state.last_update,
        "error": state.error,
        "team_count": len(state.teams),
    })


@app.route("/api/<key>/load", methods=["POST"])
def api_load(key):
    """Lance le chargement d'une compétition en arrière-plan."""
    if key not in states:
        return jsonify({"error": "Compétition inconnue"}), 404

    state = states[key]
    if state.loading:
        return jsonify({"status": "already_loading"})

    thread = threading.Thread(target=_load_competition, args=(state,), daemon=True)
    thread.start()
    return jsonify({"status": "started"})


@app.route("/api/<key>/data")
def api_data(key):
    """Renvoie toutes les données d'une compétition en JSON."""
    if key not in states:
        return jsonify({"error": "Compétition inconnue"}), 404

    state = states[key]
    return jsonify({
        "loading": state.loading,
        "error": state.error,
        "last_update": state.last_update,
        "season_progress": round(state.season_progress, 1),
        "teams": [_team_to_dict(t) for t in state.teams],
        "predictions": [_prediction_to_dict(p) for p in state.predictions] if state.predictions else [],
        "team_stats": {name: _stats_to_dict(s) for name, s in state.team_stats.items()} if state.team_stats else {},
        "calendar_summary": state.calendar_summary,
    })


# ── Chargement automatique au démarrage ──────────────────────────────
def _auto_startup():
    """Charge toutes les compétitions au démarrage du serveur."""
    time.sleep(2)  # Laisser le serveur démarrer
    for key, state in states.items():
        print(f"⏳ Chargement auto : {state.name}...")
        _load_competition(state)
        if state.error:
            print(f"❌ Erreur {state.name}: {state.error}")
        else:
            print(f"✅ {state.name} chargé ({len(state.teams)} équipes)")


# Lancer le chargement au démarrage
startup_thread = threading.Thread(target=_auto_startup, daemon=True)
startup_thread.start()


# ── Point d'entrée ───────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="IA Foot - Serveur Web")
    parser.add_argument("--host", default="0.0.0.0", help="Adresse d'écoute")
    parser.add_argument("--port", type=int, default=5000, help="Port")
    parser.add_argument("--debug", action="store_true", help="Mode debug")
    args = parser.parse_args()

    print(f"\n⚽ IA Classement Foot - Serveur Web")
    print(f"   http://{args.host}:{args.port}\n")

    app.run(host=args.host, port=args.port, debug=args.debug)
