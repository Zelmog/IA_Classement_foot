"""
Module de prédiction par simulation Monte Carlo.

Utilise un modèle de force d'équipe et la distribution de Poisson
pour simuler les matchs restants de la saison et estimer les
probabilités de montée / descente pour chaque équipe.

Approche inspirée des méthodes utilisées par FiveThirtyEight et Opta.
"""

import copy
from typing import Dict, List, Tuple

import numpy as np

from modules.config import (
    DRAW_POINTS,
    LOSS_POINTS,
    N_SIMULATIONS,
    PROMOTION_SPOTS,
    RELEGATION_SPOTS,
    TOTAL_MATCHES_PER_TEAM,
    WIN_POINTS,
)
from modules.models import Fixture, PredictionResult, Team, TeamStats


class PromotionPredictor:
    """
    Prédicteur de montée/descente basé sur la simulation Monte Carlo.

    Le modèle calcule la force offensive et défensive de chaque équipe
    à partir de leurs statistiques actuelles, puis simule les matchs
    restants de la saison en utilisant la distribution de Poisson pour
    générer des scores réalistes.

    Attributes:
        teams: Liste des équipes avec leurs statistiques.
        total_matches: Nombre total de matchs par équipe dans la saison.
        n_simulations: Nombre de simulations Monte Carlo.
        promotion_spots: Nombre de places de montée.
        relegation_spots: Nombre de places de descente.
    """

    def __init__(
        self,
        teams: List[Team],
        total_matches: int = TOTAL_MATCHES_PER_TEAM,
        n_simulations: int = N_SIMULATIONS,
        promotion_spots: int = PROMOTION_SPOTS,
        relegation_spots: int = RELEGATION_SPOTS,
        fixtures: List[Fixture] = None,
        team_stats: Dict[str, TeamStats] = None,
    ):
        self.teams = teams
        self.total_matches = total_matches
        self.n_simulations = n_simulations
        self.promotion_spots = promotion_spots
        self.relegation_spots = relegation_spots
        self.n_teams = len(teams)
        self.rng = np.random.default_rng()

        # Matchs réels restants (si disponibles)
        self.real_fixtures = fixtures or []
        self.use_real_fixtures = len(self.real_fixtures) > 0

        # Statistiques détaillées (forme, dom/ext)
        self.team_stats: Dict[str, TeamStats] = team_stats or {}
        self.use_detailed_stats = len(self.team_stats) > 0

        # Statistiques de la ligue
        self.avg_goals_per_match = self._calculate_league_average()

        # Calculer l'avantage domicile moyen de la ligue
        self.home_advantage = self._calculate_home_advantage()

        # Calculer les forces des équipes
        self._calculate_team_strengths()

    def _calculate_league_average(self) -> float:
        """
        Calcule la moyenne de buts par équipe par match dans la ligue.

        Returns:
            Moyenne de buts par équipe par match.
        """
        total_goals = sum(t.goals_for for t in self.teams)
        total_matches_played = sum(t.matches_played for t in self.teams)

        if total_matches_played == 0:
            return 1.3  # Valeur par défaut réaliste pour le foot amateur

        # Chaque match implique 2 équipes, donc on divise par le nombre total
        # de "performances d'équipe" (= nombre total de matchs joués)
        return total_goals / total_matches_played

    def _calculate_home_advantage(self) -> float:
        """
        Calcule l'avantage domicile moyen de la ligue.

        Basé sur le ratio buts domicile / buts extérieur.
        Retourne un multiplicateur (ex: 1.25 = 25% d'avantage domicile).
        """
        if not self.use_detailed_stats:
            return 1.25  # Valeur par défaut réaliste pour le foot amateur

        total_home_goals = sum(s.home_goals_for for s in self.team_stats.values())
        total_away_goals = sum(s.away_goals_for for s in self.team_stats.values())
        total_home_matches = sum(s.home_played for s in self.team_stats.values())
        total_away_matches = sum(s.away_played for s in self.team_stats.values())

        if total_away_matches == 0 or total_home_matches == 0:
            return 1.25

        home_avg = total_home_goals / total_home_matches
        away_avg = total_away_goals / total_away_matches

        if away_avg == 0:
            return 1.25

        return max(0.9, min(1.6, home_avg / away_avg))  # Borné [0.9, 1.6]

    def _calculate_team_strengths(self) -> None:
        """
        Calcule la force offensive et défensive de chaque équipe.

        Force offensive = (buts marqués/match) / (moyenne ligue buts/match)
        Force défensive = (buts encaissés/match) / (moyenne ligue buts/match)

        Une force >1 = supérieur à la moyenne, <1 = inférieur.
        """
        avg = self.avg_goals_per_match

        for team in self.teams:
            if team.matches_played > 0 and avg > 0:
                team.attack_strength = team.goals_per_match / avg
                team.defense_strength = team.goals_conceded_per_match / avg
            else:
                team.attack_strength = 1.0
                team.defense_strength = 1.0

            # Appliquer une régression vers la moyenne pour les petits échantillons
            # Plus une équipe a joué, plus on fait confiance à ses stats
            confidence = min(team.matches_played / 10, 1.0)
            team.attack_strength = (
                confidence * team.attack_strength + (1 - confidence) * 1.0
            )
            team.defense_strength = (
                confidence * team.defense_strength + (1 - confidence) * 1.0
            )

    def _simulate_match(self, team_a: Team, team_b: Team) -> Tuple[int, int]:
        """
        Simule un match entre deux équipes en utilisant la distribution de Poisson.

        Le nombre de buts attendus est calculé en fonction de :
        - La force offensive/défensive globale de chaque équipe
        - Les performances domicile/extérieur (si stats détaillées dispo)
        - La forme récente (si stats détaillées dispo)
        - L'avantage terrain

        Args:
            team_a: Équipe domicile.
            team_b: Équipe extérieur.

        Returns:
            Tuple (buts_a, buts_b).
        """
        # Forces de base (globales)
        attack_a = team_a.attack_strength
        defense_a = team_a.defense_strength
        attack_b = team_b.attack_strength
        defense_b = team_b.defense_strength

        # Ajustements si stats détaillées disponibles
        # Flag pour savoir si les ajustements dom/ext ont été appliqués
        home_away_adjusted = False

        if self.use_detailed_stats:
            stats_a = self.team_stats.get(team_a.name)
            stats_b = self.team_stats.get(team_b.name)

            if stats_a and stats_b:
                avg = self.avg_goals_per_match

                # --- Ajustement domicile/extérieur ---
                # Mélanger force globale (70%) et force dom/ext (30%)
                if stats_a.home_played >= 2 and avg > 0:
                    home_att = stats_a.home_attack / avg
                    home_def = stats_a.home_defense / avg
                    attack_a = 0.7 * attack_a + 0.3 * home_att
                    defense_a = 0.7 * defense_a + 0.3 * home_def
                    home_away_adjusted = True

                if stats_b.away_played >= 2 and avg > 0:
                    away_att = stats_b.away_attack / avg
                    away_def = stats_b.away_defense / avg
                    attack_b = 0.7 * attack_b + 0.3 * away_att
                    defense_b = 0.7 * defense_b + 0.3 * away_def
                    home_away_adjusted = True

                # --- Ajustement forme récente ---
                # form_score va de 0 (que des défaites) à 3 (que des victoires)
                # Neutre = 1.5 → facteur = 1.0
                form_a = stats_a.form_score
                form_b = stats_b.form_score

                # Convertir en multiplicateur : forme 3.0 → 1.06, forme 0.0 → 0.94
                form_factor_a = 1.0 + (form_a - 1.5) * 0.04
                form_factor_b = 1.0 + (form_b - 1.5) * 0.04

                attack_a *= form_factor_a
                attack_b *= form_factor_b

        # Avantage terrain pour ce match
        # Si les stats dom/ext sont déjà dans les forces, réduire le
        # multiplicateur global pour éviter le double comptage
        if home_away_adjusted:
            match_home_adv = 1.0 + (self.home_advantage - 1.0) * 0.35
        else:
            match_home_adv = self.home_advantage

        # Buts attendus pour chaque équipe
        expected_goals_a = (
            attack_a * defense_b * self.avg_goals_per_match * match_home_adv
        )
        expected_goals_b = (
            attack_b * defense_a * self.avg_goals_per_match / match_home_adv
        )

        # Limiter les valeurs extrêmes (entre 0.2 et 5.0 buts attendus)
        expected_goals_a = np.clip(expected_goals_a, 0.2, 5.0)
        expected_goals_b = np.clip(expected_goals_b, 0.2, 5.0)

        # Générer les buts avec la distribution de Poisson
        goals_a = self.rng.poisson(expected_goals_a)
        goals_b = self.rng.poisson(expected_goals_b)

        return int(goals_a), int(goals_b)

    def _get_remaining_fixtures(self) -> List[Tuple[Team, Team]]:
        """
        Retourne les matchs restants de la saison.

        Si le calendrier réel a été chargé, utilise les vrais matchs.
        Sinon, génère des pairings aléatoires.

        Returns:
            Liste de tuples (équipe_a, équipe_b) pour chaque match restant.
        """
        if self.use_real_fixtures:
            return self._fixtures_from_calendar()
        return self._generate_random_fixtures()

    def _fixtures_from_calendar(self) -> List[Tuple[Team, Team]]:
        """
        Construit les paires de matchs à partir du calendrier réel.

        Returns:
            Liste de tuples (Team, Team) pour les matchs restants.
        """
        team_dict = {t.name: t for t in self.teams}
        result = []

        for fixture in self.real_fixtures:
            home = team_dict.get(fixture.home_team)
            away = team_dict.get(fixture.away_team)
            if home and away:
                result.append((home, away))

        return result

    def _generate_random_fixtures(self) -> List[Tuple[Team, Team]]:
        """
        Génère les matchs restants aléatoirement (fallback sans calendrier).

        Returns:
            Liste de tuples (équipe_a, équipe_b) pour chaque match restant.
        """
        remaining = {t.name: self.total_matches - t.matches_played for t in self.teams}
        team_dict = {t.name: t for t in self.teams}
        fixtures = []

        max_iterations = 500
        iteration = 0

        while iteration < max_iterations:
            # Trouver les équipes qui ont encore des matchs à jouer
            available = [
                team_dict[name]
                for name, count in remaining.items()
                if count > 0
            ]

            if len(available) < 2:
                break

            # Mélanger pour créer des pairings aléatoires
            indices = self.rng.permutation(len(available))
            available = [available[i] for i in indices]

            paired_this_round = False
            for i in range(0, len(available) - 1, 2):
                a = available[i]
                b = available[i + 1]

                if remaining[a.name] > 0 and remaining[b.name] > 0:
                    fixtures.append((a, b))
                    remaining[a.name] -= 1
                    remaining[b.name] -= 1
                    paired_this_round = True

            if not paired_this_round:
                break

            iteration += 1

        return fixtures

    def simulate(self, progress_callback=None) -> List[PredictionResult]:
        """
        Lance la simulation Monte Carlo complète.

        Pour chaque simulation :
        1. Génère les matchs restants
        2. Simule chaque match
        3. Calcule le classement final
        4. Enregistre les positions finales

        Args:
            progress_callback: Fonction optionnelle appelée à chaque simulation
                             avec (current, total) en arguments.

        Returns:
            Liste de PredictionResult triée par probabilité de montée décroissante.
        """
        n_teams = self.n_teams

        # Compteurs
        promotion_count = {t.name: 0 for t in self.teams}
        relegation_count = {t.name: 0 for t in self.teams}
        position_counts = {t.name: np.zeros(n_teams, dtype=int) for t in self.teams}
        total_final_points = {t.name: 0.0 for t in self.teams}

        for sim in range(self.n_simulations):
            # Points et différence de buts pour cette simulation
            points = {t.name: t.points for t in self.teams}
            goal_diff = {t.name: t.goal_difference for t in self.teams}

            # Récupérer les matchs restants (réels ou générés)
            fixtures = self._get_remaining_fixtures()

            for team_a, team_b in fixtures:
                goals_a, goals_b = self._simulate_match(team_a, team_b)

                goal_diff[team_a.name] += goals_a - goals_b
                goal_diff[team_b.name] += goals_b - goals_a

                if goals_a > goals_b:
                    points[team_a.name] += WIN_POINTS
                elif goals_a == goals_b:
                    points[team_a.name] += DRAW_POINTS
                    points[team_b.name] += DRAW_POINTS
                else:
                    points[team_b.name] += WIN_POINTS

            # Classement final : tri par points puis différence de buts
            final_ranking = sorted(
                points.keys(),
                key=lambda name: (-points[name], -goal_diff[name]),
            )

            # Enregistrer les résultats
            for pos, name in enumerate(final_ranking):
                position_counts[name][pos] += 1
                total_final_points[name] += points[name]

                if pos < self.promotion_spots:
                    promotion_count[name] += 1
                elif pos >= n_teams - self.relegation_spots:
                    relegation_count[name] += 1

            # Callback de progression
            if progress_callback and (sim + 1) % max(1, self.n_simulations // 100) == 0:
                progress_callback(sim + 1, self.n_simulations)

        # Construire les résultats
        results = []
        for team in self.teams:
            result = PredictionResult(
                team_name=team.name,
                current_rank=team.rank,
                current_points=team.points,
                matches_played=team.matches_played,
                matches_remaining=self.total_matches - team.matches_played,
                promotion_probability=round(
                    promotion_count[team.name] / self.n_simulations * 100, 1
                ),
                relegation_probability=round(
                    relegation_count[team.name] / self.n_simulations * 100, 1
                ),
                avg_final_position=round(
                    sum(
                        (i + 1) * position_counts[team.name][i]
                        for i in range(n_teams)
                    )
                    / self.n_simulations,
                    1,
                ),
                predicted_final_points=round(
                    total_final_points[team.name] / self.n_simulations, 1
                ),
                position_probabilities=[
                    round(count / self.n_simulations * 100, 1)
                    for count in position_counts[team.name]
                ],
            )
            results.append(result)

        # Trier par probabilité de montée décroissante
        results.sort(key=lambda r: -r.promotion_probability)

        return results

    def get_season_progress(self) -> float:
        """
        Calcule le pourcentage d'avancement de la saison.

        Returns:
            Pourcentage d'avancement (0-100).
        """
        avg_played = sum(t.matches_played for t in self.teams) / self.n_teams
        return round(avg_played / self.total_matches * 100, 1)

    def get_team_analysis(self, team_name: str) -> Dict:
        """
        Analyse détaillée d'une équipe spécifique.

        Args:
            team_name: Nom de l'équipe.

        Returns:
            Dictionnaire avec les statistiques détaillées.
        """
        team = next((t for t in self.teams if t.name == team_name), None)
        if not team:
            return {}

        remaining = self.total_matches - team.matches_played
        max_points = team.points + remaining * WIN_POINTS

        analysis = {
            "name": team.name,
            "current_rank": team.rank,
            "points": team.points,
            "matches_played": team.matches_played,
            "matches_remaining": remaining,
            "max_possible_points": max_points,
            "points_per_match": round(team.points_per_match, 2),
            "goals_per_match": round(team.goals_per_match, 2),
            "goals_conceded_per_match": round(team.goals_conceded_per_match, 2),
            "attack_strength": round(team.attack_strength, 3),
            "defense_strength": round(team.defense_strength, 3),
            "win_rate": round(team.win_rate * 100, 1),
            "form_rating": self._calculate_form_rating(team),
        }

        # Ajouter les stats détaillées si disponibles
        stats = self.team_stats.get(team_name)
        if stats:
            analysis["form_label"] = stats.form_label
            analysis["form_score"] = round(stats.form_score, 2)
            analysis["home_record"] = (
                f"{stats.home_wins}V {stats.home_draws}N {stats.home_losses}D"
            )
            analysis["away_record"] = (
                f"{stats.away_wins}V {stats.away_draws}N {stats.away_losses}D"
            )
            analysis["home_goals"] = (
                f"{stats.home_goals_for}BP / {stats.home_goals_against}BC"
            )
            analysis["away_goals"] = (
                f"{stats.away_goals_for}BP / {stats.away_goals_against}BC"
            )
            analysis["home_ppg"] = round(stats.home_ppg, 2)
            analysis["away_ppg"] = round(stats.away_ppg, 2)
            analysis["forfeits"] = stats.forfeits_given

        return analysis

    def _calculate_form_rating(self, team: Team) -> str:
        """
        Estime la forme actuelle de l'équipe (A à E).

        Basé sur les points par match comparés à la moyenne de la ligue.
        """
        if team.matches_played == 0:
            return "?"

        avg_ppm = sum(t.points_per_match for t in self.teams) / self.n_teams
        ratio = team.points_per_match / avg_ppm if avg_ppm > 0 else 1.0

        if ratio >= 1.5:
            return "A"
        elif ratio >= 1.2:
            return "B"
        elif ratio >= 0.8:
            return "C"
        elif ratio >= 0.5:
            return "D"
        else:
            return "E"
