"""
Module de scraping pour récupérer le classement depuis l'API FFF DOFA.

Utilise des appels HTTP directs à l'API publique api-dofa.fff.fr
au lieu de Selenium (plus rapide, plus fiable, pas de dépendance navigateur).
"""

import json
import os
import re
import datetime
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from modules.config import (
    COMPETITION_URL,
    DATA_BACKUP_FILE,
)
from modules.models import Fixture, Team, TeamStats

# ============================================================
# Base URL de l'API FFF DOFA
# ============================================================
API_BASE = "https://api-dofa.fff.fr/api"


def _new_session() -> requests.Session:
    """Crée une session HTTP avec retry automatique."""
    s = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[500, 502, 503, 504],
    )
    s.mount("https://", HTTPAdapter(max_retries=retry))
    return s


_session = _new_session()


def _log(msg: str) -> None:
    """Print avec gestion des erreurs d'encodage (emojis sur Windows cp1252)."""
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode("ascii", errors="replace").decode("ascii"))


# ============================================================
# Helpers API
# ============================================================


def _build_team_name(equipe: dict) -> str:
    """
    Construit le nom complet d'une équipe à partir des données API.

    Si l'équipe a un code > 1, on l'ajoute au short_name.
    Ex: short_name='MACAUDAISE SJ', code=2 → 'MACAUDAISE SJ 2'
    """
    name = equipe.get("short_name", "?")
    code = equipe.get("code", 1)
    if code and code > 1:
        name = f"{name} {code}"
    return name


def _extract_params(url: str) -> Tuple[str, str, str]:
    """
    Extrait les paramètres id, phase, poule depuis une URL FFF.

    Args:
        url: URL de compétition FFF (ex: ...?tab=ranking&id=435749&phase=1&poule=1&type=ch)

    Returns:
        Tuple (comp_id, phase, poule).
    """
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    comp_id = params.get("id", [""])[0]
    phase = params.get("phase", ["1"])[0]
    poule = params.get("poule", ["1"])[0]
    return comp_id, phase, poule


def _api_get(path: str, retries: int = 4) -> dict:
    """
    Effectue un GET sur l'API FFF DOFA avec retry et reset de session SSL.

    En cas d'erreur SSL, ferme la session et en recrée une nouvelle
    pour forcer un nouveau handshake TLS (corrige DECRYPTION_FAILED sur Oracle Cloud).
    """
    global _session
    url = f"{API_BASE}{path}"
    for attempt in range(retries):
        try:
            resp = _session.get(url, timeout=60)
            resp.raise_for_status()
            return resp.json()
        except (requests.exceptions.SSLError, requests.exceptions.ConnectionError) as e:
            if attempt < retries - 1:
                wait = 2 * (attempt + 1)
                _log(f"⚠️  Erreur réseau (tentative {attempt + 1}/{retries}), reset session, retry dans {wait}s...")
                _session.close()
                _session = _new_session()
                time.sleep(wait)
            else:
                raise


def _fetch_ranking(comp_id: str, phase: str, poule: str) -> Optional[List[Team]]:
    """
    Récupère le classement depuis l'API DOFA.

    Returns:
        Liste de Team triées par classement, ou None si échec.
    """
    path = f"/compets/{comp_id}/phases/{phase}/poules/{poule}/classement_journees"
    data = _api_get(path)
    members = data.get("hydra:member", [])
    if not members:
        return None

    teams = []
    for entry in members:
        equipe = entry.get("equipe", {})
        team = Team(
            rank=entry.get("rank", 0),
            name=_build_team_name(equipe),
            points=entry.get("point_count", 0),
            matches_played=entry.get("total_games_count", 0),
            wins=entry.get("won_games_count", 0),
            draws=entry.get("draw_games_count", 0),
            losses=entry.get("lost_games_count", 0),
            forfeits=entry.get("forfeits_games_count", 0),
            goals_for=entry.get("goals_for_count", 0),
            goals_against=entry.get("goals_against_count", 0),
            penalties=entry.get("penalty_point_count", 0),
            goal_difference=entry.get("goals_for_count", 0) - entry.get("goals_against_count", 0),
        )
        teams.append(team)

    teams.sort(key=lambda t: t.rank)
    return teams


def _fetch_all_matchs(comp_id: str, phase: str, poule: str) -> Optional[List[Fixture]]:
    """
    Récupère tous les matchs (paginés) depuis l'API DOFA.

    Gère deux formats de réponse :
    - dict avec 'hydra:member' (ancien format)
    - list directe (nouveau format)

    Returns:
        Liste de Fixture (joués et à venir), ou None si échec.
    """
    all_fixtures: List[Fixture] = []
    page = 1

    while True:
        path = f"/compets/{comp_id}/phases/{phase}/poules/{poule}/matchs?page={page}"
        data = _api_get(path)

        # Gérer les deux formats de réponse API
        if isinstance(data, list):
            members = data
        elif isinstance(data, dict):
            members = data.get("hydra:member", [])
        else:
            break

        if not members:
            break

        for m in members:
            journee = m.get("poule_journee") or {}
            matchday = journee.get("number", 0)

            # Date ISO → "DD/MM/YYYY HHhMM"
            date_raw = m.get("date", "") or ""
            time_raw = m.get("time", "") or ""
            date_str = _format_date(date_raw, time_raw)

            home_info = m.get("home") or {}
            away_info = m.get("away") or {}
            home_name = _build_team_name(home_info)
            away_name = _build_team_name(away_info)

            # Déterminer si le match a été joué
            # home_resu: "GA" (gagné), "PE" (perdu), "NU" (nul), null (pas joué)
            home_resu = m.get("home_resu")
            played = home_resu is not None and home_resu != ""

            home_goals = m.get("home_score") if played else None
            away_goals = m.get("away_score") if played else None

            fixture = Fixture(
                matchday=matchday,
                date=date_str,
                home_team=home_name,
                away_team=away_name,
                home_goals=home_goals,
                away_goals=away_goals,
                played=played,
            )
            all_fixtures.append(fixture)

        # Pagination : ancien format (dict avec hydra:view) ou nouveau (list)
        if isinstance(data, dict):
            view = data.get("hydra:view", {})
            if "hydra:next" not in view:
                break
        else:
            # Format liste : si la page retourne moins de 30 items, c'est la dernière
            if len(members) < 30:
                break
        page += 1
        time.sleep(0.5)  # Pause entre les pages pour éviter les erreurs SSL

    all_fixtures.sort(key=lambda f: (f.matchday, f.date))
    return all_fixtures if all_fixtures else None


def _format_date(date_iso: str, time_fff: str) -> str:
    """
    Convertit une date ISO + heure FFF en string lisible.

    Args:
        date_iso: Date ISO (ex: "2025-09-21T00:00:00+00:00")
        time_fff: Heure FFF (ex: "15H00")

    Returns:
        String "21/09/2025 15H00" ou "21/09/2025"
    """
    if not date_iso:
        return ""
    try:
        dt = datetime.datetime.fromisoformat(date_iso)
        date_part = dt.strftime("%d/%m/%Y")
        if time_fff:
            return f"{date_part} {time_fff}"
        return date_part
    except (ValueError, TypeError):
        return date_iso


# ============================================================
# Fonctions publiques (même interface qu'avant)
# ============================================================


def scrape_ranking(url: str = COMPETITION_URL, external_driver=None) -> List[Team]:
    """
    Récupère le classement depuis l'API FFF DOFA.

    En cas d'échec, charge les données depuis le fichier de sauvegarde.

    Args:
        url: URL de la page de classement.
        external_driver: Ignoré (conservé pour compatibilité).

    Returns:
        Liste d'objets Team triés par classement.
    """
    comp_id, phase, poule = _extract_params(url)

    # Tentative 1 : API
    try:
        _log("📡 Récupération du classement via API FFF...")
        teams = _fetch_ranking(comp_id, phase, poule)
        if teams:
            _log(f"✅ {len(teams)} équipes récupérées avec succès !")
            _save_backup(teams, comp_id)
            return teams
    except Exception as e:
        _log(f"❌ Erreur API classement : {e}")

    # Tentative 2 : Sauvegarde
    _log("\n⚠️  API échouée. Tentative de chargement depuis la sauvegarde...")
    teams = load_from_backup(comp_id=comp_id)
    if teams:
        _log("✅ Données chargées depuis la sauvegarde.")
        return teams

    # Tentative 3 : Données de démonstration
    _log("\n⚠️  Aucune sauvegarde trouvée. Chargement des données de démonstration...")
    return _get_demo_data()


def scrape_results(
    url: str = COMPETITION_URL,
    team_names: Optional[List[str]] = None,
    max_journee: int = 22,
    external_driver=None,
) -> Optional[List[Fixture]]:
    """
    Récupère les résultats (avec scores) depuis l'API FFF DOFA.

    Args:
        url: URL de la page classement.
        team_names: Ignoré (conservé pour compatibilité).
        max_journee: Ignoré (conservé pour compatibilité).
        external_driver: Ignoré (conservé pour compatibilité).

    Returns:
        Liste de Fixture avec les scores remplis, ou None.
    """
    comp_id, phase, poule = _extract_params(url)
    try:
        _log("📊 Récupération des résultats via API FFF...")
        fixtures = _fetch_all_matchs(comp_id, phase, poule)
        if fixtures:
            played = [f for f in fixtures if f.played]
            _log(f"✅ {len(played)} matchs avec score sur {len(fixtures)} total")
            return fixtures
    except Exception as e:
        _log(f"❌ Erreur API résultats : {e}")
    return None


def scrape_calendar(
    url: str = COMPETITION_URL,
    team_names: Optional[List[str]] = None,
    external_driver=None,
) -> Optional[List[Fixture]]:
    """
    Récupère le calendrier complet depuis l'API FFF DOFA.

    Args:
        url: URL de la page de classement.
        team_names: Ignoré (conservé pour compatibilité).
        external_driver: Ignoré (conservé pour compatibilité).

    Returns:
        Liste de Fixture ou None si échec.
    """
    comp_id, phase, poule = _extract_params(url)
    try:
        _log("📅 Récupération du calendrier via API FFF...")
        fixtures = _fetch_all_matchs(comp_id, phase, poule)
        if fixtures:
            played = sum(1 for f in fixtures if f.played)
            remaining = len(fixtures) - played
            _log(f"✅ {len(fixtures)} matchs ({played} joués, {remaining} à venir)")
            return fixtures
    except Exception as e:
        _log(f"❌ Erreur API calendrier : {e}")
    return None


def scrape_competition(url: str):
    """
    Récupère classement + résultats + calendrier via l'API FFF DOFA.

    Un seul appel API pour les matchs (résultats et calendrier sont les mêmes données).

    Args:
        url: URL de la page de classement FFF.

    Returns:
        Tuple (teams, result_fixtures, calendar_fixtures).
        Chaque élément peut être None en cas d'échec.
    """
    comp_id, phase, poule = _extract_params(url)
    teams = None
    result_fixtures = None
    calendar_fixtures = None

    # 1. Classement
    try:
        _log(f"📡 API FFF - classement (compet={comp_id}, phase={phase}, poule={poule})...")
        teams = _fetch_ranking(comp_id, phase, poule)
        if teams:
            _save_backup(teams, comp_id)
            _log(f"✅ {len(teams)} équipes: {', '.join(t.name for t in teams[:4])}...")
    except Exception as e:
        _log(f"❌ Erreur API classement: {e}")

    if not teams:
        _log("⚠️  Tentative de chargement depuis la sauvegarde...")
        teams = load_from_backup(comp_id=comp_id)
    if not teams:
        teams = _get_demo_data()
    if not teams:
        return None, None, None

    # 2. Matchs (un seul appel pour résultats + calendrier)
    try:
        _log("📊 API FFF - matchs...")
        all_matchs = _fetch_all_matchs(comp_id, phase, poule)
        if all_matchs:
            result_fixtures = all_matchs
            calendar_fixtures = all_matchs
            played = sum(1 for f in all_matchs if f.played)
            _log(f"✅ {len(all_matchs)} matchs ({played} joués, {len(all_matchs) - played} à venir)")
    except Exception as e:
        _log(f"❌ Erreur API matchs: {e}")

    return teams, result_fixtures, calendar_fixtures


# ============================================================
# Sauvegarde / Chargement
# ============================================================


def _backup_path_for(comp_id: str = "") -> Path:
    """Retourne le chemin du fichier de sauvegarde pour une compétition."""
    if comp_id:
        return Path(DATA_BACKUP_FILE).parent / f"dernier_classement_{comp_id}.json"
    return Path(DATA_BACKUP_FILE)


def _save_backup(teams: List[Team], comp_id: str = "") -> None:
    """Sauvegarde les données scrapées dans un fichier JSON par compétition."""
    try:
        backup_path = _backup_path_for(comp_id)
        backup_path.parent.mkdir(parents=True, exist_ok=True)

        data = []
        for team in teams:
            data.append({
                "rank": team.rank,
                "name": team.name,
                "points": team.points,
                "matches_played": team.matches_played,
                "wins": team.wins,
                "draws": team.draws,
                "losses": team.losses,
                "forfeits": team.forfeits,
                "goals_for": team.goals_for,
                "goals_against": team.goals_against,
                "penalties": team.penalties,
                "goal_difference": team.goal_difference,
            })

        with open(backup_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    except Exception as e:
        _log(f"⚠️  Impossible de sauvegarder les données : {e}")


def load_from_backup(path: str = DATA_BACKUP_FILE, comp_id: str = "") -> Optional[List[Team]]:
    """
    Charge les données depuis un fichier JSON de sauvegarde.

    Args:
        path: Chemin vers le fichier JSON (ignoré si comp_id fourni).
        comp_id: ID de la compétition pour charger le bon fichier.

    Returns:
        Liste de Team ou None si le fichier n'existe pas.
    """
    try:
        backup_path = str(_backup_path_for(comp_id)) if comp_id else path
        if not os.path.exists(backup_path):
            return None

        with open(backup_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        teams = []
        for item in data:
            teams.append(Team(**item))

        teams.sort(key=lambda t: t.rank)
        return teams

    except Exception as e:
        _log(f"❌ Erreur de chargement : {e}")
        return None


def _get_demo_data() -> List[Team]:
    """
    Retourne les données de démonstration.
    Utilisé comme dernier recours si l'API et la sauvegarde échouent.
    """
    demo_teams = [
        Team(1, "MERIGNACAIS SA", 28, 15, 9, 2, 4, 0, 48, 25, 1, 23),
        Team(2, "MACAUDAISE SJ", 27, 13, 8, 3, 2, 0, 27, 17, 0, 10),
        Team(3, "MEDOC OCEAN FC", 23, 12, 6, 5, 1, 0, 27, 17, 0, 10),
        Team(4, "BLANQUEFORTAISE ES", 22, 14, 6, 4, 4, 0, 34, 30, 0, 4),
        Team(5, "MAZERES ROAILLAN ES", 21, 14, 6, 3, 5, 0, 24, 25, 0, -1),
        Team(6, "PAYS AUROSSAIS FC", 18, 13, 5, 4, 4, 0, 30, 26, 1, 4),
        Team(7, "CASTETS EN DORTHE CA", 18, 12, 5, 3, 4, 0, 22, 24, 0, -2),
        Team(8, "LANTONNAIS CS", 15, 13, 4, 4, 4, 1, 25, 25, 0, 0),
        Team(9, "APIS FOOTBALL", 15, 11, 5, 0, 6, 0, 21, 25, 0, -4),
        Team(10, "GRAVES FC", 10, 13, 2, 4, 7, 0, 29, 36, 0, -7),
        Team(11, "PAUILLAC ST LAURENT", 9, 11, 2, 3, 6, 0, 25, 35, 0, -10),
        Team(12, "TEICHOISE JS", 6, 15, 1, 3, 11, 0, 24, 51, 0, -27),
    ]
    _log(f"✅ {len(demo_teams)} équipes chargées (données de démonstration).")
    return demo_teams


# ============================================================
# Utilitaires pour le calendrier
# ============================================================


def get_remaining_fixtures(
    fixtures: List[Fixture],
) -> List[Fixture]:
    """
    Filtre et retourne uniquement les matchs restants (non joués).

    Args:
        fixtures: Liste complète des matchs.

    Returns:
        Liste des matchs à venir.
    """
    return [f for f in fixtures if not f.played]


def get_calendar_summary(fixtures: List[Fixture]) -> dict:
    """
    Résumé du calendrier.

    Args:
        fixtures: Liste de tous les matchs.

    Returns:
        Dictionnaire avec les stats du calendrier.
    """
    total = len(fixtures)
    played = sum(1 for f in fixtures if f.played)
    remaining = total - played
    matchdays = max((f.matchday for f in fixtures), default=0)
    current_matchday = 0
    for md in range(1, matchdays + 1):
        md_fixtures = [f for f in fixtures if f.matchday == md]
        if md_fixtures and all(f.played for f in md_fixtures):
            current_matchday = md

    return {
        "total_matches": total,
        "played": played,
        "remaining": remaining,
        "total_matchdays": matchdays,
        "current_matchday": current_matchday,
    }


# ============================================================
# Calcul des statistiques détaillées par équipe
# ============================================================


def _parse_date(date_str: str) -> Optional[datetime.date]:
    """
    Parse une date depuis le format API (DD/MM/YYYY ...).

    Returns:
        datetime.date ou None.
    """
    if not date_str:
        return None

    # Format "DD/MM/YYYY" ou "DD/MM/YYYY HHhMM"
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})", date_str)
    if m:
        try:
            return datetime.date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            return None

    return None


def compute_team_stats(
    fixtures: List[Fixture],
    team_names: List[str],
    n_recent: int = 5,
) -> Dict[str, TeamStats]:
    """
    Calcule les statistiques détaillées de chaque équipe à partir des résultats.

    Permet de calculer :
    - Bilan domicile / extérieur
    - Forme récente (derniers N matchs)
    - Forfaits

    Args:
        fixtures: Liste des matchs avec scores (played=True, home_goals/away_goals remplis).
        team_names: Liste des noms d'équipes.
        n_recent: Nombre de matchs récents pour la forme.

    Returns:
        Dict nom_équipe -> TeamStats.
    """
    from collections import defaultdict

    stats: Dict[str, TeamStats] = {name: TeamStats(name=name) for name in team_names}
    team_results: Dict[str, List[Tuple[datetime.date, int, str]]] = defaultdict(list)

    def _sort_key(f: Fixture):
        parsed = _parse_date(f.date) if f.date else None
        if parsed:
            return (parsed, f.matchday)
        return (datetime.date(1900, 1, 1), f.matchday)

    played_fixtures = sorted(
        [f for f in fixtures if f.played and f.home_goals is not None],
        key=_sort_key,
    )

    for fixture in played_fixtures:
        home = fixture.home_team
        away = fixture.away_team
        hg = fixture.home_goals
        ag = fixture.away_goals
        match_date = _parse_date(fixture.date) if fixture.date else None
        if not match_date:
            match_date = datetime.date(1900, 1, fixture.matchday)

        if home not in stats or away not in stats:
            continue

        # Domicile
        s_home = stats[home]
        s_home.home_goals_for += hg
        s_home.home_goals_against += ag
        if hg > ag:
            s_home.home_wins += 1
            team_results[home].append((match_date, fixture.matchday, "V"))
        elif hg == ag:
            s_home.home_draws += 1
            team_results[home].append((match_date, fixture.matchday, "N"))
        else:
            s_home.home_losses += 1
            team_results[home].append((match_date, fixture.matchday, "D"))

        # Extérieur
        s_away = stats[away]
        s_away.away_goals_for += ag
        s_away.away_goals_against += hg
        if ag > hg:
            s_away.away_wins += 1
            team_results[away].append((match_date, fixture.matchday, "V"))
        elif ag == hg:
            s_away.away_draws += 1
            team_results[away].append((match_date, fixture.matchday, "N"))
        else:
            s_away.away_losses += 1
            team_results[away].append((match_date, fixture.matchday, "D"))

    # Forme récente (derniers n_recent matchs), triés par date réelle
    for name, results_list in team_results.items():
        results_list.sort(key=lambda x: (x[0], x[1]))
        stats[name].recent_results = [r for _, _, r in results_list[-n_recent:]]

    return stats
