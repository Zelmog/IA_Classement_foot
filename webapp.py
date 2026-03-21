"""
IA Classement Foot - Application Web
=====================================

Serveur Flask fournissant une interface web responsive (mobile-first)
pour visualiser les classements, prédictions et statistiques.

Usage:
    python webapp.py
    python webapp.py --port 8080
    python webapp.py --host 0.0.0.0    (accessible sur le réseau local)
"""

import argparse
import threading
from typing import Dict, List, Optional

from flask import Flask, jsonify, redirect, render_template, request, url_for

from modules.config import (
    COMPETITIONS,
    COMPETITION_URL,
    N_SIMULATIONS,
    PROMOTION_SPOTS,
    RELEGATION_SPOTS,
    TOTAL_MATCHES_PER_TEAM,
)
from modules.models import Fixture, PredictionResult, Team, TeamStats
from modules.predictor import PromotionPredictor
from modules.scraper import (
    scrape_ranking,
    scrape_calendar,
    scrape_results,
    compute_team_stats,
    get_remaining_fixtures,
    get_calendar_summary,
    load_from_backup,
)

app = Flask(__name__)

# ─── État global de l'application ─────────────────────────────
class AppState:
    """Stocke les données partagées entre les routes."""

    def __init__(self, url: str = COMPETITION_URL):
        self.url: str = url
        self.teams: List[Team] = []
        self.fixtures: Optional[List[Fixture]] = None
        self.team_stats: Optional[Dict[str, TeamStats]] = None
        self.predictions: Optional[List[PredictionResult]] = None
        self.predictor: Optional[PromotionPredictor] = None
        self.settings = {
            "n_simulations": N_SIMULATIONS,
            "total_matches": TOTAL_MATCHES_PER_TEAM,
            "promotion_spots": PROMOTION_SPOTS,
            "relegation_spots": RELEGATION_SPOTS,
        }
        self.loading: Dict[str, bool] = {
            "ranking": False,
            "calendar": False,
            "results": False,
            "prediction": False,
        }
        self.messages: List[Dict] = []  # {"type": "success"|"error"|"info", "text": "..."}

    def add_message(self, msg_type: str, text: str):
        self.messages.append({"type": msg_type, "text": text})

    def pop_messages(self) -> List[Dict]:
        msgs = self.messages[:]
        self.messages.clear()
        return msgs

    def auto_detect_total_matches(self):
        if not self.teams:
            return
        n = len(self.teams)
        max_played = max(t.matches_played for t in self.teams)
        single = n - 1
        double = 2 * (n - 1)
        self.settings["total_matches"] = double if max_played > single else single

    def run_prediction(self):
        if not self.teams:
            return
        real_fixtures = None
        if self.fixtures:
            real_fixtures = get_remaining_fixtures(self.fixtures)

        self.predictor = PromotionPredictor(
            teams=self.teams,
            total_matches=self.settings["total_matches"],
            n_simulations=self.settings["n_simulations"],
            promotion_spots=self.settings["promotion_spots"],
            relegation_spots=self.settings["relegation_spots"],
            fixtures=real_fixtures,
            team_stats=self.team_stats,
        )
        self.predictions = self.predictor.simulate()


state = AppState()

# ─── États multi-compétition ─────────────────────────────────
states: Dict[str, AppState] = {}
for _key, _comp in COMPETITIONS.items():
    states[_key] = AppState(url=_comp["url"])


def get_state(key: str) -> AppState:
    """Retourne l'état de la compétition ou la première par défaut."""
    return states.get(key, next(iter(states.values())))


def comp_keys():
    """Liste des clés de compétition pour les templates."""
    return list(COMPETITIONS.keys())


# ─── Chargement automatique au démarrage (fonctionne avec gunicorn) ───
_startup_done = False

def _auto_startup():
    global _startup_done
    if not _startup_done:
        _startup_done = True
        loader = threading.Thread(target=startup_load, daemon=True)
        loader.start()


@app.before_request
def ensure_startup():
    _auto_startup()


# ─── Routes de pages ──────────────────────────────────────────

@app.route("/")
def root():
    """Redirige vers la première compétition."""
    first_key = next(iter(COMPETITIONS))
    return redirect(f"/{first_key}/")


@app.route("/<key>/")
def index(key: str):
    """Page principale: dashboard complet."""
    if key not in states:
        return redirect("/")
    st = get_state(key)
    messages = st.pop_messages()
    season_progress = 0.0
    if st.predictor:
        season_progress = st.predictor.get_season_progress()

    calendar_summary = None
    if st.fixtures:
        calendar_summary = get_calendar_summary(st.fixtures)

    pred_map = {}
    if st.predictions:
        for p in st.predictions:
            pred_map[p.team_name] = p

    return render_template(
        "index.html",
        teams=st.teams,
        predictions=st.predictions,
        pred_map=pred_map,
        team_stats=st.team_stats,
        season_progress=season_progress,
        calendar_summary=calendar_summary,
        url=st.url,
        settings=st.settings,
        loading=st.loading,
        messages=messages,
        promotion_spots=st.settings["promotion_spots"],
        relegation_spots=st.settings["relegation_spots"],
        comp_key=key,
        competitions=COMPETITIONS,
    )


@app.route("/<key>/equipe/<team_name>")
def team_detail(key: str, team_name: str):
    """Page détail d'une équipe."""
    if key not in states:
        return redirect("/")
    st = get_state(key)
    messages = st.pop_messages()
    team = next((t for t in st.teams if t.name == team_name), None)
    if not team:
        return render_template("404.html", message=f"Équipe '{team_name}' non trouvée."), 404

    analysis = None
    prediction = None
    if st.predictor and st.predictions:
        analysis = st.predictor.get_team_analysis(team_name)
        prediction = next((p for p in st.predictions if p.team_name == team_name), None)

    ts = st.team_stats.get(team_name) if st.team_stats else None

    return render_template(
        "team.html",
        team=team,
        analysis=analysis,
        prediction=prediction,
        team_stat=ts,
        messages=messages,
        comp_key=key,
        competitions=COMPETITIONS,
    )


@app.route("/<key>/forme")
def form_page(key: str):
    """Page forme des équipes."""
    if key not in states:
        return redirect("/")
    st = get_state(key)
    messages = st.pop_messages()
    return render_template(
        "forme.html",
        teams=st.teams,
        team_stats=st.team_stats,
        messages=messages,
        comp_key=key,
        competitions=COMPETITIONS,
    )


@app.route("/<key>/calendrier")
def calendar_page(key: str):
    """Page calendrier / matchs restants."""
    if key not in states:
        return redirect("/")
    st = get_state(key)
    messages = st.pop_messages()
    all_fixtures = []
    if st.fixtures:
        all_fixtures = sorted(st.fixtures, key=lambda f: (f.matchday, f.date))

    calendar_summary = None
    if st.fixtures:
        calendar_summary = get_calendar_summary(st.fixtures)

    return render_template(
        "calendrier.html",
        fixtures=all_fixtures,
        calendar_summary=calendar_summary,
        messages=messages,
        comp_key=key,
        competitions=COMPETITIONS,
    )


# ─── Routes API (actions) ────────────────────────────────────

@app.route("/<key>/api/load-ranking", methods=["POST"])
def api_load_ranking(key: str):
    """Charge le classement depuis le site FFF."""
    st = get_state(key)
    if st.loading["ranking"]:
        return jsonify({"status": "busy", "message": "Chargement déjà en cours..."})

    url = request.form.get("url", st.url).strip()
    if url:
        st.url = url

    st.loading["ranking"] = True
    try:
        teams = scrape_ranking(url=st.url)
        if teams:
            st.teams = teams
            st.auto_detect_total_matches()
            st.add_message("success", f"{len(teams)} équipes chargées.")
            st.run_prediction()
            st.add_message("success", "Prédiction calculée.")
        else:
            teams = load_from_backup()
            if teams:
                st.teams = teams
                st.auto_detect_total_matches()
                st.add_message("info", "Données chargées depuis le backup.")
                st.run_prediction()
            else:
                st.add_message("error", "Impossible de charger le classement.")
    except Exception as e:
        st.add_message("error", f"Erreur: {e}")
    finally:
        st.loading["ranking"] = False

    return jsonify({"status": "ok", "redirect": f"/{key}/"})


@app.route("/<key>/api/load-calendar", methods=["POST"])
def api_load_calendar(key: str):
    """Charge le calendrier réel."""
    st = get_state(key)
    if st.loading["calendar"]:
        return jsonify({"status": "busy", "message": "Chargement déjà en cours..."})
    if not st.teams:
        st.add_message("error", "Chargez d'abord le classement.")
        return jsonify({"status": "error", "redirect": f"/{key}/"})

    st.loading["calendar"] = True
    try:
        team_names = [t.name for t in st.teams]
        fixtures = scrape_calendar(st.url, team_names)
        if fixtures:
            st.fixtures = fixtures
            summary = get_calendar_summary(fixtures)
            st.add_message(
                "success",
                f"Calendrier chargé : {summary['total_matches']} matchs "
                f"({summary['played']} joués, {summary['remaining']} restants)"
            )
            st.run_prediction()
            st.add_message("success", "Prédiction recalculée avec le calendrier.")
        else:
            st.add_message("error", "Aucun match trouvé.")
    except Exception as e:
        st.add_message("error", f"Erreur calendrier: {e}")
    finally:
        st.loading["calendar"] = False

    return jsonify({"status": "ok", "redirect": f"/{key}/calendrier"})


@app.route("/<key>/api/load-results", methods=["POST"])
def api_load_results(key: str):
    """Charge les résultats détaillés."""
    st = get_state(key)
    if st.loading["results"]:
        return jsonify({"status": "busy", "message": "Chargement déjà en cours..."})
    if not st.teams:
        st.add_message("error", "Chargez d'abord le classement.")
        return jsonify({"status": "error", "redirect": f"/{key}/"})

    st.loading["results"] = True
    try:
        team_names = [t.name for t in st.teams]
        result_fixtures = scrape_results(st.url, team_names)
        if result_fixtures:
            played = [f for f in result_fixtures if f.played]
            st.team_stats = compute_team_stats(played, team_names)
            st.add_message(
                "success",
                f"Résultats chargés : {len(played)} matchs. "
                f"Stats calculées pour {len(st.team_stats)} équipes."
            )
            st.run_prediction()
            st.add_message("success", "Prédiction recalculée avec les stats détaillées.")
        else:
            st.add_message("error", "Aucun résultat trouvé.")
    except Exception as e:
        st.add_message("error", f"Erreur résultats: {e}")
    finally:
        st.loading["results"] = False

    return jsonify({"status": "ok", "redirect": f"/{key}/forme"})


@app.route("/<key>/api/predict", methods=["POST"])
def api_predict(key: str):
    """Relance la prédiction."""
    st = get_state(key)
    if not st.teams:
        st.add_message("error", "Aucune donnée chargée.")
        return jsonify({"status": "error", "redirect": f"/{key}/"})

    try:
        st.run_prediction()
        st.add_message("success", "Prédiction recalculée.")
    except Exception as e:
        st.add_message("error", f"Erreur prédiction: {e}")

    return jsonify({"status": "ok", "redirect": f"/{key}/"})


# ─── Démarrage ────────────────────────────────────────────────

def startup_load():
    """Charge toutes les données au démarrage pour chaque compétition."""
    for key, comp in COMPETITIONS.items():
        st = states[key]
        print(f"\n{'='*50}")
        print(f"📡 Chargement {comp['name']} ({key})...")
        print(f"{'='*50}")

        # 1. Classement
        teams = scrape_ranking(url=st.url)
        if teams:
            st.teams = teams
            st.auto_detect_total_matches()
            print(f"✅ {len(teams)} équipes chargées.")
        else:
            print(f"⚠️  Pas de données pour {comp['name']}.")
            continue

        team_names = [t.name for t in st.teams]

        # 2. Résultats détaillés
        try:
            print("📊 Chargement des résultats...")
            result_fixtures = scrape_results(st.url, team_names)
            if result_fixtures:
                played = [f for f in result_fixtures if f.played]
                st.team_stats = compute_team_stats(played, team_names)
                print(f"✅ Résultats chargés : {len(played)} matchs.")
            else:
                print("⚠️  Aucun résultat trouvé.")
        except Exception as e:
            print(f"⚠️  Erreur résultats : {e}")

        # 3. Calendrier
        try:
            print("📅 Chargement du calendrier...")
            fixtures = scrape_calendar(st.url, team_names)
            if fixtures:
                st.fixtures = fixtures
                summary = get_calendar_summary(fixtures)
                print(
                    f"✅ Calendrier chargé : {summary['total_matches']} matchs "
                    f"({summary['played']} joués, {summary['remaining']} restants)"
                )
            else:
                print("⚠️  Aucun match trouvé dans le calendrier.")
        except Exception as e:
            print(f"⚠️  Erreur calendrier : {e}")

        # 4. Prédiction
        st.run_prediction()
        print(f"✅ Prédiction calculée pour {comp['name']}.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="IA Classement Foot - Web")
    parser.add_argument("--host", default="0.0.0.0", help="Adresse d'écoute")
    parser.add_argument("--port", type=int, default=5000, help="Port")
    parser.add_argument("--debug", action="store_true", help="Mode debug Flask")
    args = parser.parse_args()

    print(f"\n🌐 Application web démarrée !")
    print(f"   Local:   http://127.0.0.1:{args.port}")
    print(f"   Réseau:  http://0.0.0.0:{args.port}")
    print(f"   (Sur téléphone, utilisez l'IP de votre PC)")
    print(f"   ⏳ Chargement des données en arrière-plan...\n")

    app.run(host=args.host, port=args.port, debug=args.debug)
