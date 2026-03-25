"""
Module d'affichage pour le projet IA Classement Foot.

Utilise la librairie Rich pour un affichage coloré et structuré
dans le terminal. Fournit des fonctions pour afficher le classement
actuel, les prédictions et les analyses détaillées.
"""

from typing import Dict, List, Optional

from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table
from rich.text import Text

from modules.config import (
    COMPETITION_NAME,
    COMPETITION_URL,
    PROMOTION_SPOTS,
    RELEGATION_SPOTS,
    THEME_DANGER,
    THEME_INFO,
    THEME_PRIMARY,
    THEME_SUCCESS,
    THEME_WARNING,
)
from modules.models import Fixture, PredictionResult, Team, TeamStats

# Console Rich globale
console = Console()


def _extract_competition_label(url: str) -> str:
    """
    Extrait un libellé court depuis l'URL FFF.
    Tente de récupérer l'id, la phase et la poule.
    """
    from urllib.parse import parse_qs, urlparse

    try:
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        comp_id = params.get("id", ["?"])[0]
        phase = params.get("phase", ["?"])[0]
        poule = params.get("poule", ["?"])[0]
        district = parsed.hostname or ""
        district = district.replace(".fff.fr", "").capitalize()
        return f"{district} • id={comp_id} • phase {phase} • poule {poule}"
    except Exception:
        return url[:60]


def display_header(url: str = COMPETITION_URL) -> None:
    """Affiche l'en-tête du programme."""
    title = Text()
    title.append("⚽ ", style="bold")
    title.append("IA CLASSEMENT FOOT", style="bold cyan")
    title.append(" ⚽", style="bold")

    label = _extract_competition_label(url)
    subtitle = Text()
    subtitle.append("Prédiction des chances de montée par simulation Monte Carlo\n")
    subtitle.append(f"Compétition : {label}", style="italic")

    panel = Panel(
        subtitle,
        title=title,
        border_style=THEME_PRIMARY,
        padding=(1, 2),
    )
    console.print(panel)
    console.print()


def display_current_ranking(teams: List[Team]) -> None:
    """
    Affiche le classement actuel sous forme de tableau.

    Args:
        teams: Liste des équipes triées par classement.
    """
    table = Table(
        title="📋 Classement Actuel",
        title_style="bold white",
        border_style=THEME_PRIMARY,
        show_lines=False,
        pad_edge=True,
    )

    # Colonnes
    table.add_column("Pl", justify="center", style="bold", width=4)
    table.add_column("Équipe", style="white", min_width=25)
    table.add_column("Pts", justify="center", style="bold yellow", width=5)
    table.add_column("Jo", justify="center", width=4)
    table.add_column("G", justify="center", style=THEME_SUCCESS, width=4)
    table.add_column("N", justify="center", style=THEME_WARNING, width=4)
    table.add_column("P", justify="center", style=THEME_DANGER, width=4)
    table.add_column("BP", justify="center", width=5)
    table.add_column("BC", justify="center", width=5)
    table.add_column("Diff", justify="center", width=5)

    n_teams = len(teams)

    for team in teams:
        # Couleur de la ligne selon la position
        if team.rank <= PROMOTION_SPOTS:
            row_style = "green"
            rank_display = f"🟢 {team.rank}"
        elif team.rank > n_teams - RELEGATION_SPOTS:
            row_style = "red"
            rank_display = f"🔴 {team.rank}"
        else:
            row_style = ""
            rank_display = f"   {team.rank}"

        # Différence de buts avec signe
        diff_str = f"+{team.goal_difference}" if team.goal_difference > 0 else str(team.goal_difference)

        table.add_row(
            rank_display,
            team.name,
            str(team.points),
            str(team.matches_played),
            str(team.wins),
            str(team.draws),
            str(team.losses),
            str(team.goals_for),
            str(team.goals_against),
            diff_str,
            style=row_style,
        )

    console.print(table)
    console.print()

    # Légende
    console.print("   🟢 Zone de montée    🔴 Zone de descente", style="dim")
    console.print()


def display_predictions(results: List[PredictionResult], season_progress: float) -> None:
    """
    Affiche les résultats des prédictions.

    Args:
        results: Liste des résultats de prédiction.
        season_progress: Pourcentage d'avancement de la saison.
    """
    # Info sur la simulation
    console.print(
        Panel(
            f"Avancement saison : [bold]{season_progress}%[/bold]  │  "
            f"Basé sur [bold]{len(results)}[/bold] équipes  │  "
            f"Top {PROMOTION_SPOTS} = montée, Derniers {RELEGATION_SPOTS} = descente",
            title="📊 Paramètres",
            border_style=THEME_INFO,
        )
    )
    console.print()

    # Tableau principal des prédictions
    table = Table(
        title="🔮 Prédictions de Fin de Saison",
        title_style="bold white",
        border_style="magenta",
        show_lines=False,
        pad_edge=True,
        expand=True,
    )

    table.add_column("Cl.", justify="center", style="bold", width=4)
    table.add_column("Équipe", style="white", ratio=1)
    table.add_column("Pts", justify="center", width=4)
    table.add_column("Préd.", justify="center", style="bold", width=5)
    table.add_column("Rest.", justify="center", width=5)
    table.add_column("Pos.", justify="center", width=5)
    table.add_column("Montée %", justify="center", width=10)
    table.add_column("Desc. %", justify="center", width=10)

    # Trier par classement actuel pour l'affichage
    sorted_results = sorted(results, key=lambda r: r.current_rank)

    for result in sorted_results:
        # Barre de progression pour la montée
        promo_bar = _make_probability_bar(result.promotion_probability, "green")
        releg_bar = _make_probability_bar(result.relegation_probability, "red")

        # Style de la ligne
        if result.promotion_probability >= 50:
            row_style = "green"
        elif result.relegation_probability >= 50:
            row_style = "red"
        else:
            row_style = ""

        table.add_row(
            str(result.current_rank),
            result.team_name,
            str(result.current_points),
            str(result.predicted_final_points),
            str(result.matches_remaining),
            str(result.avg_final_position),
            promo_bar,
            releg_bar,
            style=row_style,
        )

    console.print(table)
    console.print()


def _make_probability_bar(probability: float, color: str) -> str:
    """
    Crée une représentation textuelle d'une probabilité.

    Args:
        probability: Probabilité en pourcentage (0-100).
        color: Couleur Rich à utiliser.

    Returns:
        Chaîne formatée avec la probabilité.
    """
    if probability >= 80:
        style = f"bold {color}"
    elif probability >= 50:
        style = color
    else:
        style = f"dim {color}"

    # Barre visuelle
    filled = int(probability / 10)
    bar = "█" * filled + "░" * (10 - filled)

    return f"[{style}]{bar} {probability:5.1f}%[/{style}]"


def display_promotion_ranking(results: List[PredictionResult]) -> None:
    """
    Affiche le classement trié par probabilité de montée.

    Args:
        results: Liste des résultats de prédiction.
    """
    table = Table(
        title="🏆 Classement par Chances de Montée",
        title_style="bold white",
        border_style="green",
        show_lines=False,
        expand=True,
    )

    table.add_column("#", justify="center", width=4)
    table.add_column("Équipe", ratio=1)
    table.add_column("Chance Montée", justify="center", width=15)
    table.add_column("Cl. Act.", justify="center", width=8)
    table.add_column("Pos. Moy.", justify="center", width=10)

    # Déjà trié par probabilité de montée (décroissant)
    for i, result in enumerate(results, 1):
        promo = result.promotion_probability

        if promo >= 80:
            style = "bold green"
            indicator = "🟢"
        elif promo >= 50:
            style = "green"
            indicator = "🟡"
        elif promo >= 20:
            style = "yellow"
            indicator = "🟠"
        else:
            style = "dim"
            indicator = "🔴"

        table.add_row(
            str(i),
            f"{indicator} {result.team_name}",
            f"[{style}]{promo:.1f}%[/]",
            str(result.current_rank),
            str(result.avg_final_position),
        )

    console.print(table)
    console.print()


def display_team_detail(analysis: Dict, prediction: PredictionResult) -> None:
    """
    Affiche l'analyse détaillée d'une équipe.

    Args:
        analysis: Dictionnaire d'analyse (depuis predictor.get_team_analysis).
        prediction: Résultat de prédiction pour l'équipe.
    """
    if not analysis:
        console.print("[red]Équipe non trouvée.[/red]")
        return

    # En-tête
    panel_content = (
        f"[bold]Classement actuel :[/bold] {analysis['current_rank']}e\n"
        f"[bold]Points :[/bold] {analysis['points']} "
        f"({analysis['points_per_match']} pts/match)\n"
        f"[bold]Matchs joués :[/bold] {analysis['matches_played']} "
        f"(reste {analysis['matches_remaining']})\n"
        f"[bold]Points max possibles :[/bold] {analysis['max_possible_points']}\n"
        f"\n"
        f"[bold]Buts marqués/match :[/bold] {analysis['goals_per_match']}\n"
        f"[bold]Buts encaissés/match :[/bold] {analysis['goals_conceded_per_match']}\n"
        f"[bold]Taux de victoire :[/bold] {analysis['win_rate']}%\n"
        f"\n"
        f"[bold]Force offensive :[/bold] {analysis['attack_strength']} "
        f"({'⬆' if analysis['attack_strength'] > 1 else '⬇'} moyenne)\n"
        f"[bold]Force défensive :[/bold] {analysis['defense_strength']} "
        f"({'⬇ bien' if analysis['defense_strength'] < 1 else '⬆ à améliorer'})\n"
        f"[bold]Forme actuelle :[/bold] {analysis['form_rating']}\n"
    )

    # Ajouter les stats détaillées si disponibles
    if "form_label" in analysis:
        form_colored = ""
        for char in analysis["form_label"]:
            if char == "V":
                form_colored += "[green]V[/green]"
            elif char == "N":
                form_colored += "[yellow]N[/yellow]"
            elif char == "D":
                form_colored += "[red]D[/red]"
            else:
                form_colored += char

        panel_content += (
            f"\n[bold]── Statistiques détaillées ──[/bold]\n"
            f"[bold]Forme récente :[/bold] {form_colored} "
            f"(score: {analysis['form_score']})\n"
            f"[bold]Domicile :[/bold] {analysis['home_record']} │ "
            f"{analysis['home_goals']} │ {analysis['home_ppg']} pts/m\n"
            f"[bold]Extérieur :[/bold] {analysis['away_record']} │ "
            f"{analysis['away_goals']} │ {analysis['away_ppg']} pts/m\n"
        )
        if analysis.get("forfeits", 0) > 0:
            panel_content += (
                f"[bold red]Forfaits donnés :[/bold red] "
                f"{analysis['forfeits']}\n"
            )

    panel_content += (
        f"\n"
        f"[bold cyan]Probabilité de montée : {prediction.promotion_probability}%[/]\n"
        f"[bold red]Probabilité de descente : {prediction.relegation_probability}%[/]\n"
        f"[bold]Position finale prédite : {prediction.avg_final_position}e[/]\n"
        f"[bold]Points finaux prédits : {prediction.predicted_final_points}[/]"
    )

    console.print(
        Panel(
            panel_content,
            title=f"🔍 Analyse : {analysis['name']}",
            border_style=THEME_PRIMARY,
            padding=(1, 2),
        )
    )
    console.print()

    # Distribution des positions finales
    if prediction.position_probabilities:
        table = Table(
            title="Distribution des Positions Finales",
            border_style="dim",
            show_lines=False,
        )
        for i, prob in enumerate(prediction.position_probabilities, 1):
            table.add_column(f"{i}e", justify="center", width=7)

        table.add_row(
            *[f"{p:.1f}%" for p in prediction.position_probabilities]
        )

        console.print(table)
        console.print()


def create_progress_bar() -> Progress:
    """
    Crée une barre de progression Rich pour la simulation.

    Returns:
        Objet Progress configuré.
    """
    return Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]Simulation en cours...[/bold blue]"),
        BarColumn(bar_width=40),
        MofNCompleteColumn(),
        TextColumn("•"),
        TimeElapsedColumn(),
        console=console,
    )


def display_menu(
    url: str = COMPETITION_URL,
    calendar_loaded: bool = False,
    results_loaded: bool = False,
) -> str:
    """
    Affiche le menu principal et retourne le choix de l'utilisateur.

    Args:
        url: URL active de la compétition.
        calendar_loaded: True si le calendrier est chargé.
        results_loaded: True si les résultats détaillés sont chargés.

    Returns:
        Choix de l'utilisateur (chaîne).
    """
    label = _extract_competition_label(url)
    results_status = (
        "[green](chargés ✔)[/green]" if results_loaded else "[dim](non chargés)[/dim]"
    )
    console.print(
        Panel(
            f"[dim]URL active : {label}[/dim]\n\n"
            "[1] 📊 Voir le classement actuel\n"
            "[2] 🔮 Lancer la prédiction\n"
            "[3] 🏆 Classement par chances de montée\n"
            "[4] 🔍 Analyse détaillée d'une équipe\n"
            "[5] 🔄 Rafraîchir les données (re-scraper)\n"
            "[6] ⚙️  Modifier les paramètres\n"
            "[7] 🌐 Charger un autre lien de compétition\n"
            f"[8] 📅 Charger le calendrier {'[green](chargé ✔)[/green]' if calendar_loaded else '[dim](non chargé)[/dim]'}\n"
            "[9] 📅 Voir les matchs restants\n"
            f"[10] 📈 Charger les résultats détaillés {results_status}\n"
            "[11] 📈 Voir la forme des équipes\n"
            "[0] 🚪 Quitter",
            title="📌 Menu Principal",
            border_style=THEME_PRIMARY,
            padding=(1, 2),
        )
    )

    choice = console.input("\n[bold cyan]Votre choix → [/bold cyan]")
    return choice.strip()


def display_team_selector(teams: List[Team]) -> str:
    """
    Affiche la liste des équipes et retourne le choix de l'utilisateur.

    Args:
        teams: Liste des équipes.

    Returns:
        Nom de l'équipe choisie.
    """
    console.print("\n[bold]Choisissez une équipe :[/bold]\n")
    for i, team in enumerate(teams, 1):
        console.print(f"  [{i:2d}] {team.name}")

    console.print()
    choice = console.input("[bold cyan]Numéro de l'équipe → [/bold cyan]")

    try:
        index = int(choice.strip()) - 1
        if 0 <= index < len(teams):
            return teams[index].name
    except ValueError:
        pass

    return ""


def display_settings(settings: Dict) -> Dict:
    """
    Affiche et permet de modifier les paramètres.

    Args:
        settings: Dictionnaire des paramètres actuels.

    Returns:
        Dictionnaire des paramètres mis à jour.
    """
    console.print(
        Panel(
            f"[bold]Simulations :[/bold] {settings['n_simulations']}\n"
            f"[bold]Matchs totaux/équipe :[/bold] {settings['total_matches']}\n"
            f"[bold]Places de montée :[/bold] {settings['promotion_spots']}\n"
            f"[bold]Places de descente :[/bold] {settings['relegation_spots']}",
            title="⚙️  Paramètres Actuels",
            border_style=THEME_WARNING,
            padding=(1, 2),
        )
    )

    console.print("\nModifier un paramètre (Entrée pour garder la valeur actuelle) :\n")

    new_val = console.input(
        f"  Nombre de simulations [{settings['n_simulations']}] → "
    ).strip()
    if new_val:
        try:
            settings["n_simulations"] = max(100, int(new_val))
        except ValueError:
            pass

    new_val = console.input(
        f"  Matchs totaux par équipe [{settings['total_matches']}] → "
    ).strip()
    if new_val:
        try:
            settings["total_matches"] = max(1, int(new_val))
        except ValueError:
            pass

    new_val = console.input(
        f"  Places de montée [{settings['promotion_spots']}] → "
    ).strip()
    if new_val:
        try:
            settings["promotion_spots"] = max(1, int(new_val))
        except ValueError:
            pass

    new_val = console.input(
        f"  Places de descente [{settings['relegation_spots']}] → "
    ).strip()
    if new_val:
        try:
            settings["relegation_spots"] = max(0, int(new_val))
        except ValueError:
            pass

    console.print("\n[green]✅ Paramètres mis à jour ![/green]\n")
    return settings


def display_error(message: str) -> None:
    """Affiche un message d'erreur."""
    console.print(f"\n[bold red]❌ Erreur : {message}[/bold red]\n")


def display_success(message: str) -> None:
    """Affiche un message de succès."""
    console.print(f"\n[bold green]✅ {message}[/bold green]\n")


def display_info(message: str) -> None:
    """Affiche un message d'information."""
    console.print(f"\n[bold blue]ℹ️  {message}[/bold blue]\n")


def display_url_input(current_url: str) -> Optional[str]:
    """
    Demande à l'utilisateur de saisir une nouvelle URL de compétition.

    Args:
        current_url: URL actuellement utilisée.

    Returns:
        Nouvelle URL saisie, ou None si annulé.
    """
    console.print(
        Panel(
            f"[bold]URL actuelle :[/bold]\n{current_url}\n\n"
            "Collez le lien d'une page de classement FFF.\n"
            "Le lien doit contenir [bold]tab=ranking[/bold] dans l'URL.\n\n"
            "[dim]Exemples de liens valides :[/dim]\n"
            "  https://gironde.fff.fr/competitions?tab=ranking&id=435749&phase=1&poule=1&type=ch\n"
            "  https://paris-idf.fff.fr/competitions?tab=ranking&id=123456&phase=1&poule=1&type=ch\n\n"
            "[dim]Appuyez sur Entrée sans rien saisir pour annuler.[/dim]",
            title="🌐 Charger un Nouveau Lien",
            border_style=THEME_INFO,
            padding=(1, 2),
        )
    )

    new_url = console.input("\n[bold cyan]Nouveau lien → [/bold cyan]").strip()

    if not new_url:
        return None

    # Validation basique
    if "fff.fr" not in new_url or "tab=ranking" not in new_url:
        # Tenter d'ajouter tab=ranking si l'utilisateur a collé un lien sans
        if "fff.fr" in new_url and "competitions" in new_url:
            if "tab=ranking" not in new_url:
                if "?" in new_url:
                    new_url = new_url.split("?")[0] + "?tab=ranking&" + new_url.split("?")[1]
                else:
                    new_url += "?tab=ranking"
            console.print(f"[yellow]⚠️  URL ajustée : {new_url}[/yellow]")
        else:
            display_error(
                "Le lien ne semble pas être une page de classement FFF valide.\n"
                "   Vérifiez qu'il contient 'fff.fr' et 'tab=ranking'."
            )
            return None

    return new_url


def display_remaining_fixtures(fixtures: List[Fixture]) -> None:
    """
    Affiche les matchs restants regroupés par journée.

    Args:
        fixtures: Liste des matchs restants (non joués).
    """
    remaining = [f for f in fixtures if not f.played]

    if not remaining:
        display_info("Aucun match restant trouvé dans le calendrier.")
        return

    table = Table(
        title=f"📅 Matchs Restants ({len(remaining)} matchs)",
        title_style="bold white",
        border_style=THEME_INFO,
        show_lines=False,
        expand=True,
    )

    table.add_column("J.", justify="center", width=4)
    table.add_column("Date", style="dim", width=20)
    table.add_column("Domicile", ratio=1)
    table.add_column("", justify="center", width=3)
    table.add_column("Extérieur", ratio=1)

    current_md = 0
    for fixture in sorted(remaining, key=lambda f: (f.matchday, f.date)):
        md_display = str(fixture.matchday) if fixture.matchday != current_md else ""
        if fixture.matchday != current_md:
            current_md = fixture.matchday
            if current_md > remaining[0].matchday:
                table.add_row("", "", "", "", "", style="dim")

        # Extraire date courte
        short_date = fixture.date[:30] if fixture.date else "À planifier"

        table.add_row(
            md_display,
            short_date,
            fixture.home_team,
            "vs",
            fixture.away_team,
        )

    console.print(table)
    console.print()


def display_team_form_stats(
    team_stats: Dict[str, TeamStats], teams: List[Team]
) -> None:
    """
    Affiche un tableau résumant la forme et les stats dom/ext de chaque équipe.

    Args:
        team_stats: Dictionnaire nom -> TeamStats.
        teams: Liste des équipes (pour l'ordre du classement).
    """
    if not team_stats:
        display_info("Aucune statistique détaillée disponible.")
        return

    table = Table(
        title="📈 Forme & Performances Domicile/Extérieur",
        title_style="bold white",
        border_style=THEME_INFO,
        show_lines=False,
        expand=True,
    )

    table.add_column("Cl.", justify="center", width=4)
    table.add_column("Équipe", min_width=18, no_wrap=True)
    table.add_column("Forme", justify="center", width=7)
    table.add_column("Série", justify="center", width=7)
    table.add_column("Dom. G/N/P", justify="center", width=9)
    table.add_column("Dom. BP/BC", justify="center", width=8)
    table.add_column("Ext. G/N/P", justify="center", width=9)
    table.add_column("Ext. BP/BC", justify="center", width=8)

    for team in teams:
        stats = team_stats.get(team.name)
        if not stats:
            continue

        # Coloriser la forme
        form_label = stats.form_label
        colored_form = ""
        for char in form_label:
            if char == "V":
                colored_form += "[green]V[/green]"
            elif char == "N":
                colored_form += "[yellow]N[/yellow]"
            elif char == "D":
                colored_form += "[red]D[/red]"
            else:
                colored_form += char

        # Score de forme (0-3) → indicateur visuel
        fs = stats.form_score
        if fs >= 2.2:
            form_indicator = f"[bold green]{fs:.1f} ⬆[/bold green]"
        elif fs >= 1.2:
            form_indicator = f"[yellow]{fs:.1f} ─[/yellow]"
        else:
            form_indicator = f"[red]{fs:.1f} ⬇[/red]"

        # Dom/Ext
        home_gnp = f"{stats.home_wins}/{stats.home_draws}/{stats.home_losses}"
        home_goals = f"{stats.home_goals_for}/{stats.home_goals_against}"
        away_gnp = f"{stats.away_wins}/{stats.away_draws}/{stats.away_losses}"
        away_goals = f"{stats.away_goals_for}/{stats.away_goals_against}"

        table.add_row(
            str(team.rank),
            team.name,
            form_indicator,
            colored_form,
            home_gnp,
            home_goals,
            away_gnp,
            away_goals,
        )

    console.print(table)
    console.print()
    console.print(
        "   [green]V[/green]=Victoire  [yellow]N[/yellow]=Nul  "
        "[red]D[/red]=Défaite  │  Forme = score pondéré (0=pire, 3=meilleur)",
        style="dim",
    )
    console.print()


def display_calendar_summary(summary: dict, has_fixtures: bool) -> None:
    """
    Affiche un résumé du calendrier chargé.

    Args:
        summary: Dictionnaire de stats (depuis get_calendar_summary).
        has_fixtures: True si des fixtures sont chargées.
    """
    if not has_fixtures:
        console.print(
            Panel(
                "[dim]Le calendrier n'a pas encore été chargé.\n"
                "Utilisez l'option [bold]8[/bold] pour le charger.[/dim]",
                title="📅 Calendrier",
                border_style="dim",
            )
        )
        return

    content = (
        f"[bold]Journées totales :[/bold] {summary['total_matchdays']}\n"
        f"[bold]Journée actuelle :[/bold] {summary['current_matchday']}\n"
        f"[bold]Matchs totaux :[/bold] {summary['total_matches']}\n"
        f"[bold green]Matchs joués :[/bold green] {summary['played']}\n"
        f"[bold yellow]Matchs restants :[/bold yellow] {summary['remaining']}"
    )

    console.print(
        Panel(
            content,
            title="📅 Calendrier Chargé",
            border_style=THEME_SUCCESS,
            padding=(1, 2),
        )
    )
    console.print()
