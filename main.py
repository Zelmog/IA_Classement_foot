"""
IA Classement Foot - Prédiction des chances de montée
=====================================================

Programme principal qui orchestre :
1. Le scraping du classement depuis le site de la FFF
2. La simulation Monte Carlo pour prédire les chances de montée/descente
3. L'affichage interactif des résultats

Usage:
    python main.py              # Mode normal (scraping + prédiction)
    python main.py --demo       # Mode démo (sans scraping, données intégrées)
"""

import argparse
import sys
from typing import Dict, List, Optional

from modules.config import (
    COMPETITION_URL,
    N_SIMULATIONS,
    PROMOTION_SPOTS,
    RELEGATION_SPOTS,
    TOTAL_MATCHES_PER_TEAM,
)
from modules.display import (
    console,
    create_progress_bar,
    display_calendar_summary,
    display_current_ranking,
    display_error,
    display_header,
    display_info,
    display_menu,
    display_predictions,
    display_promotion_ranking,
    display_remaining_fixtures,
    display_settings,
    display_success,
    display_team_detail,
    display_team_form_stats,
    display_team_selector,
    display_url_input,
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
    _get_demo_data,
)


class Application:
    """
    Application principale du prédicteur de classement football.

    Gère le cycle de vie de l'application :
    - Chargement des données
    - Simulation
    - Affichage interactif
    """

    def __init__(self, demo_mode: bool = False, url: str = COMPETITION_URL):
        self.teams: List[Team] = []
        self.predictions: Optional[List[PredictionResult]] = None
        self.predictor: Optional[PromotionPredictor] = None
        self.fixtures: Optional[List[Fixture]] = None
        self.team_stats: Optional[Dict[str, TeamStats]] = None
        self.demo_mode = demo_mode
        self.url = url
        self.settings: Dict = {
            "n_simulations": N_SIMULATIONS,
            "total_matches": TOTAL_MATCHES_PER_TEAM,
            "promotion_spots": PROMOTION_SPOTS,
            "relegation_spots": RELEGATION_SPOTS,
        }

    def run(self) -> None:
        """Lance l'application interactive."""
        display_header(self.url)

        # Chargement initial des données
        self._load_data()

        if not self.teams:
            display_error("Impossible de charger les données. Arrêt du programme.")
            sys.exit(1)

        # Lancer automatiquement une première prédiction
        self._run_prediction()

        # Boucle interactive
        while True:
            try:
                choice = display_menu(
                    self.url,
                    calendar_loaded=bool(self.fixtures),
                    results_loaded=bool(self.team_stats),
                )
                self._handle_choice(choice)
            except KeyboardInterrupt:
                console.print("\n\n[bold]Au revoir ! ⚽[/bold]\n")
                break

    def _load_data(self) -> None:
        """Charge les données du classement."""
        console.print("\n[bold]📡 Récupération du classement...[/bold]\n")

        try:
            if self.demo_mode:
                self.teams = _get_demo_data()
            else:
                self.teams = scrape_ranking(url=self.url)
            if self.teams:
                display_success(f"{len(self.teams)} équipes chargées.")

                # Détection automatique du nombre de matchs total
                self._auto_detect_total_matches()
        except Exception as e:
            display_error(f"Erreur lors du chargement : {e}")

    def _auto_detect_total_matches(self) -> None:
        """
        Détecte automatiquement le nombre total de matchs par équipe.

        Pour n équipes en double aller-retour : total = 2 × (n - 1)
        """
        n_teams = len(self.teams)
        max_played = max(t.matches_played for t in self.teams)

        # Si le max joué est > n-1, c'est probablement un double aller-retour
        single_round = n_teams - 1
        double_round = 2 * (n_teams - 1)

        if max_played > single_round:
            detected = double_round
        else:
            detected = single_round

        if detected != self.settings["total_matches"]:
            self.settings["total_matches"] = detected
            display_info(
                f"Détection auto : {detected} matchs par équipe "
                f"({'double' if detected == double_round else 'simple'} aller-retour, "
                f"{n_teams} équipes)"
            )

    def _run_prediction(self) -> None:
        """Lance la simulation Monte Carlo."""
        if not self.teams:
            display_error("Aucune donnée chargée. Veuillez d'abord charger le classement.")
            return

        console.print()

        # Récupérer les vrais matchs restants si le calendrier est chargé
        real_fixtures = None
        if self.fixtures:
            real_fixtures = get_remaining_fixtures(self.fixtures)
            display_info(
                f"Calendrier réel utilisé : {len(real_fixtures)} matchs restants"
            )

        # Créer le prédicteur
        self.predictor = PromotionPredictor(
            teams=self.teams,
            total_matches=self.settings["total_matches"],
            n_simulations=self.settings["n_simulations"],
            promotion_spots=self.settings["promotion_spots"],
            relegation_spots=self.settings["relegation_spots"],
            fixtures=real_fixtures,
            team_stats=self.team_stats,
        )

        season_progress = self.predictor.get_season_progress()

        # Simulation avec barre de progression
        progress = create_progress_bar()
        with progress:
            task = progress.add_task(
                "Simulation",
                total=self.settings["n_simulations"],
            )

            def update_progress(current, total):
                progress.update(task, completed=current)

            self.predictions = self.predictor.simulate(
                progress_callback=update_progress
            )

        console.print()
        display_success(
            f"Simulation terminée ! ({self.settings['n_simulations']:,} scénarios analysés)"
        )

        # Afficher les résultats
        display_predictions(self.predictions, season_progress)
        display_promotion_ranking(self.predictions)

    def _handle_choice(self, choice: str) -> None:
        """
        Traite le choix de l'utilisateur dans le menu.

        Args:
            choice: Choix de l'utilisateur.
        """
        if choice == "1":
            display_current_ranking(self.teams)

        elif choice == "2":
            self._run_prediction()

        elif choice == "3":
            if self.predictions:
                display_promotion_ranking(self.predictions)
            else:
                display_info("Lancez d'abord une prédiction (option 2).")

        elif choice == "4":
            self._show_team_detail()

        elif choice == "5":
            self._load_data()
            # Relancer la prédiction avec les nouvelles données
            if self.teams:
                self._run_prediction()

        elif choice == "6":
            self.settings = display_settings(self.settings)

        elif choice == "7":
            self._change_url()

        elif choice == "8":
            self._load_calendar()

        elif choice == "9":
            self._show_calendar_info()

        elif choice == "10":
            self._load_results()

        elif choice == "11":
            self._show_form_stats()

        elif choice == "0":
            console.print("\n[bold]Au revoir ! ⚽[/bold]\n")
            sys.exit(0)

        else:
            display_error("Choix invalide. Veuillez réessayer.")

    def _show_team_detail(self) -> None:
        """Affiche l'analyse détaillée d'une équipe choisie."""
        if not self.predictor or not self.predictions:
            display_info("Lancez d'abord une prédiction (option 2).")
            return

        team_name = display_team_selector(self.teams)
        if not team_name:
            display_error("Équipe non trouvée.")
            return

        analysis = self.predictor.get_team_analysis(team_name)
        prediction = next(
            (p for p in self.predictions if p.team_name == team_name), None
        )

        if analysis and prediction:
            display_team_detail(analysis, prediction)
        else:
            display_error("Impossible d'analyser cette équipe.")

    def _change_url(self) -> None:
        """Permet de changer l'URL de la compétition et recharge les données."""
        new_url = display_url_input(self.url)
        if new_url and new_url != self.url:
            self.url = new_url
            self.demo_mode = False
            self.fixtures = None  # Reset calendar on URL change
            self.team_stats = None  # Reset results on URL change
            display_success(f"URL mise à jour !")
            self._load_data()
            if self.teams:
                self._run_prediction()
        else:
            display_info("URL inchangée.")

    def _load_calendar(self) -> None:
        """Charge le calendrier réel depuis le site FFF."""
        if not self.teams:
            display_error("Chargez d'abord le classement (option 5).")
            return

        console.print("\n[bold]📅 Chargement du calendrier...[/bold]\n")

        try:
            team_names = [t.name for t in self.teams]
            self.fixtures = scrape_calendar(self.url, team_names)

            if self.fixtures:
                summary = get_calendar_summary(self.fixtures)
                display_success(
                    f"Calendrier chargé : {summary['total_matches']} matchs "
                    f"({summary['played']} joués, {summary['remaining']} restants)"
                )
                display_calendar_summary(summary, has_fixtures=True)

                # Relancer la prédiction avec le vrai calendrier
                self._run_prediction()
            else:
                display_error("Aucun match trouvé dans le calendrier.")
        except Exception as e:
            display_error(f"Erreur lors du chargement du calendrier : {e}")

    def _show_calendar_info(self) -> None:
        """Affiche les infos du calendrier chargé et les matchs restants."""
        if not self.fixtures:
            display_calendar_summary({}, has_fixtures=False)
            return

        summary = get_calendar_summary(self.fixtures)
        display_calendar_summary(summary, has_fixtures=True)
        display_remaining_fixtures(self.fixtures)

    def _load_results(self) -> None:
        """Charge les résultats détaillés (scores) depuis le site FFF."""
        if not self.teams:
            display_error("Chargez d'abord le classement (option 5).")
            return

        console.print("\n[bold]📈 Chargement des résultats détaillés...[/bold]\n")
        console.print(
            "[dim]Cela peut prendre un moment (parcours de chaque journée)...[/dim]\n"
        )

        try:
            team_names = [t.name for t in self.teams]
            result_fixtures = scrape_results(self.url, team_names)

            if result_fixtures:
                played = [f for f in result_fixtures if f.played]
                self.team_stats = compute_team_stats(played, team_names)

                display_success(
                    f"Résultats chargés : {len(played)} matchs avec scores."
                )
                display_info(
                    f"Statistiques calculées pour {len(self.team_stats)} équipes "
                    f"(forme, domicile/extérieur)."
                )

                # Relancer la prédiction avec les nouvelles stats
                self._run_prediction()
            else:
                display_error("Aucun résultat trouvé.")
        except Exception as e:
            display_error(f"Erreur lors du chargement des résultats : {e}")

    def _show_form_stats(self) -> None:
        """Affiche les stats de forme et domicile/extérieur."""
        if not self.team_stats:
            display_info(
                "Chargez d'abord les résultats détaillés (option 10)."
            )
            return

        display_team_form_stats(self.team_stats, self.teams)


def main():
    """Point d'entrée du programme."""
    parser = argparse.ArgumentParser(
        description="IA Classement Foot - Prédiction des chances de montée"
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Utiliser les données de démonstration (sans scraping)",
    )
    parser.add_argument(
        "--url",
        type=str,
        default=COMPETITION_URL,
        help="URL de la page de classement FFF à analyser",
    )
    args = parser.parse_args()

    app = Application(demo_mode=args.demo, url=args.url)
    app.run()


if __name__ == "__main__":
    main()
