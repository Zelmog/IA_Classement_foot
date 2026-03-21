"""
Modèles de données pour le projet IA Classement Foot.
Contient les classes représentant les équipes et les résultats de prédiction.
"""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Team:
    """
    Représente une équipe de football avec ses statistiques actuelles.

    Attributes:
        rank: Position actuelle au classement.
        name: Nom de l'équipe.
        points: Nombre de points actuels.
        matches_played: Nombre de matchs joués.
        wins: Nombre de victoires.
        draws: Nombre de matchs nuls.
        losses: Nombre de défaites.
        forfeits: Nombre de forfaits.
        goals_for: Buts marqués.
        goals_against: Buts encaissés.
        penalties: Pénalités.
        goal_difference: Différence de buts.
        attack_strength: Force offensive (calculée par le prédicteur).
        defense_strength: Force défensive (calculée par le prédicteur).
    """

    rank: int
    name: str
    points: int
    matches_played: int
    wins: int
    draws: int
    losses: int
    forfeits: int
    goals_for: int
    goals_against: int
    penalties: int
    goal_difference: int

    # Champs calculés par le prédicteur
    attack_strength: float = 1.0
    defense_strength: float = 1.0

    @property
    def points_per_match(self) -> float:
        """Moyenne de points par match."""
        if self.matches_played == 0:
            return 0.0
        return self.points / self.matches_played

    @property
    def goals_per_match(self) -> float:
        """Moyenne de buts marqués par match."""
        if self.matches_played == 0:
            return 0.0
        return self.goals_for / self.matches_played

    @property
    def goals_conceded_per_match(self) -> float:
        """Moyenne de buts encaissés par match."""
        if self.matches_played == 0:
            return 0.0
        return self.goals_against / self.matches_played

    @property
    def win_rate(self) -> float:
        """Taux de victoire."""
        if self.matches_played == 0:
            return 0.0
        return self.wins / self.matches_played

    def __str__(self) -> str:
        return f"{self.rank}. {self.name} - {self.points} pts ({self.matches_played} matchs)"


@dataclass
class PredictionResult:
    """
    Résultat de la prédiction pour une équipe.

    Attributes:
        team_name: Nom de l'équipe.
        current_rank: Classement actuel.
        current_points: Points actuels.
        matches_played: Matchs joués.
        matches_remaining: Matchs restants.
        promotion_probability: Probabilité de montée (%).
        relegation_probability: Probabilité de descente (%).
        avg_final_position: Position finale moyenne prédite.
        predicted_final_points: Points finaux prédits (moyenne).
        position_probabilities: Probabilité pour chaque position finale (%).
    """

    team_name: str
    current_rank: int
    current_points: int
    matches_played: int
    matches_remaining: int
    promotion_probability: float
    relegation_probability: float
    avg_final_position: float
    predicted_final_points: float = 0.0
    position_probabilities: List[float] = field(default_factory=list)

    @property
    def promotion_emoji(self) -> str:
        """Emoji indicateur de probabilité de montée."""
        if self.promotion_probability >= 80:
            return "🟢"
        elif self.promotion_probability >= 50:
            return "🟡"
        elif self.promotion_probability >= 20:
            return "🟠"
        else:
            return "🔴"

    @property
    def relegation_emoji(self) -> str:
        """Emoji indicateur de probabilité de descente."""
        if self.relegation_probability >= 80:
            return "🔴"
        elif self.relegation_probability >= 50:
            return "🟠"
        elif self.relegation_probability >= 20:
            return "🟡"
        else:
            return "🟢"


@dataclass
class Fixture:
    """
    Représente un match (joué ou à venir).

    Attributes:
        matchday: Numéro de la journée.
        date: Date du match (texte brut).
        home_team: Nom de l'équipe à domicile.
        away_team: Nom de l'équipe à l'extérieur.
        home_goals: Buts de l'équipe domicile (None si pas encore joué).
        away_goals: Buts de l'équipe extérieur (None si pas encore joué).
        played: True si le match a déjà été joué.
    """

    matchday: int
    date: str
    home_team: str
    away_team: str
    home_goals: Optional[int] = None
    away_goals: Optional[int] = None
    played: bool = False

    def __str__(self) -> str:
        if self.played:
            return f"J{self.matchday}: {self.home_team} {self.home_goals}-{self.away_goals} {self.away_team}"
        return f"J{self.matchday}: {self.home_team} vs {self.away_team} ({self.date})"


@dataclass
class TeamStats:
    """
    Statistiques détaillées d'une équipe construites à partir des résultats
    individuels match par match.

    Attributes:
        name: Nom de l'équipe.
        home_wins / home_draws / home_losses: Bilan à domicile.
        away_wins / away_draws / away_losses: Bilan à l'extérieur.
        home_goals_for / home_goals_against: Buts dom.
        away_goals_for / away_goals_against: Buts ext.
        recent_results: Derniers résultats ('W', 'D', 'L') du plus ancien au plus récent.
        forfeits_given: Nombre de forfaits donnés.
    """

    name: str

    # Bilan domicile
    home_wins: int = 0
    home_draws: int = 0
    home_losses: int = 0
    home_goals_for: int = 0
    home_goals_against: int = 0

    # Bilan extérieur
    away_wins: int = 0
    away_draws: int = 0
    away_losses: int = 0
    away_goals_for: int = 0
    away_goals_against: int = 0

    # Forme récente (derniers résultats, du + ancien au + récent)
    recent_results: List[str] = field(default_factory=list)

    # Forfaits
    forfeits_given: int = 0

    @property
    def home_played(self) -> int:
        return self.home_wins + self.home_draws + self.home_losses

    @property
    def away_played(self) -> int:
        return self.away_wins + self.away_draws + self.away_losses

    @property
    def home_points(self) -> int:
        return self.home_wins * 3 + self.home_draws

    @property
    def away_points(self) -> int:
        return self.away_wins * 3 + self.away_draws

    @property
    def home_ppg(self) -> float:
        """Points par match à domicile."""
        return self.home_points / self.home_played if self.home_played else 0.0

    @property
    def away_ppg(self) -> float:
        """Points par match à l'extérieur."""
        return self.away_points / self.away_played if self.away_played else 0.0

    @property
    def home_attack(self) -> float:
        """Buts marqués par match à domicile."""
        return self.home_goals_for / self.home_played if self.home_played else 0.0

    @property
    def away_attack(self) -> float:
        """Buts marqués par match à l'extérieur."""
        return self.away_goals_for / self.away_played if self.away_played else 0.0

    @property
    def home_defense(self) -> float:
        """Buts encaissés par match à domicile."""
        return self.home_goals_against / self.home_played if self.home_played else 0.0

    @property
    def away_defense(self) -> float:
        """Buts encaissés par match à l'extérieur."""
        return self.away_goals_against / self.away_played if self.away_played else 0.0

    @property
    def form_score(self) -> float:
        """
        Score de forme sur les N derniers matchs (0.0 à 3.0).
        3 pts victoire, 1 pt nul, 0 pt défaite.
        Pondéré : les matchs récents comptent plus.
        """
        if not self.recent_results:
            return 1.5  # Neutre

        values = {"V": 3.0, "N": 1.0, "D": 0.0}
        n = len(self.recent_results)
        total_weight = 0.0
        weighted_sum = 0.0

        for i, result in enumerate(self.recent_results):
            weight = 1.0 + i * 0.5  # Plus récent = plus lourd
            weighted_sum += values.get(result, 1.0) * weight
            total_weight += weight

        return weighted_sum / total_weight if total_weight > 0 else 1.5

    @property
    def form_label(self) -> str:
        """Forme en lettres (5 derniers matchs max)."""
        return "".join(self.recent_results[-5:]) if self.recent_results else "-"
