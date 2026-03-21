"""
Module de scraping pour récupérer le classement depuis le site de la FFF.

Utilise Selenium pour charger la page (rendu JavaScript nécessaire),
puis BeautifulSoup pour parser le tableau HTML.
Propose un fallback via fichier JSON ou saisie manuelle.
"""

import json
import os
import re
import time
import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from bs4 import BeautifulSoup

from modules.config import (
    COMPETITION_URL,
    DATA_BACKUP_FILE,
    SCRAPER_TIMEOUT,
)
from modules.models import Fixture, Team, TeamStats


def _log(msg: str) -> None:
    """Print avec gestion des erreurs d'encodage (emojis sur Windows cp1252)."""
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode("ascii", errors="replace").decode("ascii"))


def scrape_ranking(url: str = COMPETITION_URL) -> List[Team]:
    """
    Récupère le classement depuis le site de la FFF.

    Tente d'abord le scraping web avec Selenium.
    En cas d'échec, charge les données depuis le fichier de sauvegarde.

    Args:
        url: URL de la page de classement.

    Returns:
        Liste d'objets Team triés par classement.

    Raises:
        RuntimeError: Si aucune méthode de récupération ne fonctionne.
    """
    # Tentative 1 : Scraping web
    teams = _scrape_with_selenium(url)
    if teams:
        _save_backup(teams)
        return teams

    # Tentative 2 : Chargement depuis le fichier de sauvegarde
    _log("\n⚠️  Scraping échoué. Tentative de chargement depuis la sauvegarde...")
    teams = load_from_backup()
    if teams:
        _log("✅ Données chargées depuis la sauvegarde.")
        return teams

    # Tentative 3 : Données de démonstration
    _log("\n⚠️  Aucune sauvegarde trouvée. Chargement des données de démonstration...")
    return _get_demo_data()


def _scrape_with_selenium(url: str) -> Optional[List[Team]]:
    """
    Scrape le classement en utilisant Selenium (Chrome headless).

    Args:
        url: URL de la page à scraper.

    Returns:
        Liste de Team ou None si échec.
    """
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.chrome.service import Service
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.support.ui import WebDriverWait
        from webdriver_manager.chrome import ChromeDriverManager
    except ImportError:
        _log("⚠️  Selenium ou webdriver-manager non installé.")
        _log("   Installez avec : pip install selenium webdriver-manager")
        return None

    driver = None
    try:
        _log("🌐 Lancement du navigateur headless...")
        options = Options()
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--log-level=3")
        # Supprimer les messages de log inutiles
        options.add_experimental_option("excludeSwitches", ["enable-logging"])

        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)

        _log(f"📡 Chargement de la page...")
        driver.get(url)

        # Gérer le bandeau de cookies (cliquer sur "Accepter" si présent)
        _handle_cookies(driver)

        # Attendre que le tableau de classement soit chargé
        _log("⏳ Attente du chargement du classement...")
        WebDriverWait(driver, SCRAPER_TIMEOUT).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "table"))
        )

        # Petit délai supplémentaire pour laisser les données charger
        time.sleep(2)

        # Récupérer le HTML et parser
        html = driver.page_source
        teams = _parse_ranking_html(html)

        if teams:
            _log(f"✅ {len(teams)} équipes récupérées avec succès !")
        else:
            _log("❌ Aucune équipe trouvée dans le tableau.")

        return teams

    except Exception as e:
        _log(f"❌ Erreur lors du scraping : {e}")
        return None

    finally:
        if driver:
            driver.quit()


def _handle_cookies(driver) -> None:
    """Tente de fermer le bandeau de cookies s'il est présent."""
    try:
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.support.ui import WebDriverWait

        # Chercher et cliquer sur le bouton "Accepter" du bandeau Didomi
        accept_btn = WebDriverWait(driver, 5).until(
            EC.element_to_be_clickable(
                (By.CSS_SELECTOR, "#didomi-notice-agree-button, .didomi-continue-without-agreeing, [aria-label='Agree and close']")
            )
        )
        accept_btn.click()
        time.sleep(1)
    except Exception:
        # Le bandeau n'est pas présent ou a déjà été fermé
        pass


def _parse_ranking_html(html: str) -> Optional[List[Team]]:
    """
    Parse le HTML de la page pour extraire le classement.

    Args:
        html: Code HTML de la page.

    Returns:
        Liste de Team ou None si le parsing échoue.
    """
    soup = BeautifulSoup(html, "html.parser")
    teams = []

    # Chercher le tableau de classement
    tables = soup.find_all("table")

    for table in tables:
        rows = table.find_all("tr")
        for row in rows:
            cells = row.find_all("td")
            if len(cells) >= 12:
                try:
                    team = Team(
                        rank=_parse_int(cells[0].get_text(strip=True)),
                        name=cells[1].get_text(strip=True),
                        points=_parse_int(cells[2].get_text(strip=True)),
                        matches_played=_parse_int(cells[3].get_text(strip=True)),
                        wins=_parse_int(cells[4].get_text(strip=True)),
                        draws=_parse_int(cells[5].get_text(strip=True)),
                        losses=_parse_int(cells[6].get_text(strip=True)),
                        forfeits=_parse_int(cells[7].get_text(strip=True)),
                        goals_for=_parse_int(cells[8].get_text(strip=True)),
                        goals_against=_parse_int(cells[9].get_text(strip=True)),
                        penalties=_parse_int(cells[10].get_text(strip=True)),
                        goal_difference=_parse_int(cells[11].get_text(strip=True)),
                    )
                    teams.append(team)
                except (ValueError, IndexError) as e:
                    continue

    # Trier par classement
    if teams:
        teams.sort(key=lambda t: t.rank)

    return teams if teams else None


def _parse_int(value: str) -> int:
    """Parse une chaîne en entier, gère les cas spéciaux."""
    value = value.strip().replace("\xa0", "").replace(" ", "")
    if not value or value == "-":
        return 0
    # Gérer les nombres négatifs
    return int(value)


def _save_backup(teams: List[Team]) -> None:
    """Sauvegarde les données scrapées dans un fichier JSON."""
    try:
        backup_path = Path(DATA_BACKUP_FILE)
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


def load_from_backup(path: str = DATA_BACKUP_FILE) -> Optional[List[Team]]:
    """
    Charge les données depuis un fichier JSON de sauvegarde.

    Args:
        path: Chemin vers le fichier JSON.

    Returns:
        Liste de Team ou None si le fichier n'existe pas.
    """
    try:
        if not os.path.exists(path):
            return None

        with open(path, "r", encoding="utf-8") as f:
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
    Retourne les données de démonstration (classement du 21 mars 2026).
    Utilisé comme dernier recours si le scraping et la sauvegarde échouent.
    """
    demo_teams = [
        Team(1, "MERIGNACAIS SA 3", 28, 15, 9, 2, 4, 0, 48, 25, 1, 23),
        Team(2, "MACAUDAISE SJ 2", 27, 13, 8, 3, 2, 0, 27, 17, 0, 10),
        Team(3, "MEDOC OCEAN FC 2", 23, 12, 6, 5, 1, 0, 27, 17, 0, 10),
        Team(4, "BLANQUEFORTAISE ES 3", 22, 14, 6, 4, 4, 0, 34, 30, 0, 4),
        Team(5, "MAZERES ROAILLAN ES", 21, 14, 6, 3, 5, 0, 24, 25, 0, -1),
        Team(6, "PAYS AUROSSAIS FC 2", 18, 13, 5, 4, 4, 0, 30, 26, 1, 4),
        Team(7, "CASTETS EN DORTHE CA 2", 18, 12, 5, 3, 4, 0, 22, 24, 0, -2),
        Team(8, "LANTONNAIS CS 2", 15, 13, 4, 4, 4, 1, 25, 25, 0, 0),
        Team(9, "APIS FOOTBALL", 15, 11, 5, 0, 6, 0, 21, 25, 0, -4),
        Team(10, "GRAVES FC 4", 10, 13, 2, 4, 7, 0, 29, 36, 0, -7),
        Team(11, "PAUILLAC ST LAURENT", 9, 11, 2, 3, 6, 0, 25, 35, 0, -10),
        Team(12, "TEICHOISE JS 2", 6, 15, 1, 3, 11, 0, 24, 51, 0, -27),
    ]
    _log(f"✅ {len(demo_teams)} équipes chargées (données du 21/03/2026).")
    return demo_teams


# ============================================================
# Scraping du calendrier / matchs restants
# ============================================================


def _extract_poule_from_url(url: str) -> Optional[str]:
    """
    Extrait la valeur du paramètre 'poule' depuis une URL FFF.

    Args:
        url: URL de la compétition.

    Returns:
        Valeur du paramètre poule (ex: '1', '5') ou None.
    """
    parsed = urlparse(url)
    params = parse_qs(parsed.query, keep_blank_values=True)
    poule_values = params.get("poule", [])
    return poule_values[0] if poule_values else None


def _select_correct_poule(driver, original_url: str, team_names: Optional[List[str]] = None) -> None:
    """
    Sélectionne la bonne poule dans le dropdown de la page FFF.

    Le site FFF ne respecte pas toujours le paramètre 'poule' de l'URL
    sur les onglets calendrier/résultats. Cette fonction force la sélection
    de la poule correspondant aux équipes connues.

    Stratégie :
    1. Essaie d'abord de matcher par noms d'équipe (dropdown 'equipe')
    2. Si pas de team_names, utilise le paramètre poule de l'URL

    Args:
        driver: Instance Selenium WebDriver.
        original_url: URL d'origine (pour extraire le param poule).
        team_names: Noms d'équipes du classement pour identifier la bonne poule.
    """
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import Select

    try:
        poule_select = driver.find_element(
            By.CSS_SELECTOR, "select[name='poule-competition']"
        )
    except Exception:
        _log("  ℹ️  Pas de sélecteur de poule trouvé.")
        return

    sel = Select(poule_select)
    current_value = sel.first_selected_option.get_attribute("value")
    _log(f"  📋 Poule actuelle: {sel.first_selected_option.text} (value={current_value})")

    # Stratégie 1 : si on a des noms d'équipes, parcourir chaque poule
    # pour trouver celle qui contient nos équipes.
    if team_names:
        normalized_known = {_normalize_name(n) for n in team_names}
        _log(f"  🔍 Recherche parmi {len(normalized_known)} équipes connues")
        _log(f"     Exemples: {list(normalized_known)[:3]}")
        poule_options = [
            o.get_attribute("value")
            for o in sel.options
            if o.get_attribute("value").strip()
        ]
        _log(f"  📋 {len(poule_options)} poules disponibles: {poule_options}")

        for poule_val in poule_options:
            # Sélectionner cette poule
            sel.select_by_value(poule_val)
            time.sleep(1)

            # Cliquer Valider si présent
            _click_valider(driver)
            time.sleep(2)

            # Regarder les équipes dans le dropdown 'equipe'
            try:
                equipe_select = driver.find_element(
                    By.CSS_SELECTOR, "select[name='equipe']"
                )
                equipe_options = [
                    o.text.strip()
                    for o in equipe_select.find_elements(By.TAG_NAME, "option")
                    if o.text.strip()
                ]
                # Normaliser et comparer
                page_teams = {_normalize_name(n) for n in equipe_options}
                matches = normalized_known & page_teams

                poule_text = sel.first_selected_option.text
                _log(f"  🔸 Poule {poule_text} (val={poule_val}): {len(equipe_options)} équipes, {len(matches)} correspondances")
                if equipe_options:
                    _log(f"     Exemples page: {equipe_options[:3]}")
                    _log(f"     Normalisés page: {list(page_teams)[:3]}")
                if len(matches) >= 3:  # Au moins 3 équipes en commun
                    _log(f"  ✅ Poule détectée : {poule_text} ({len(matches)} équipes correspondent)")
                    return
            except Exception as e:
                _log(f"  ❌ Erreur dropdown equipe pour poule {poule_val}: {e}")

        # Aucune poule n'a matché → fallback sur le paramètre URL
        _log("  ⚠️  Aucune poule ne correspond parfaitement aux équipes.")

    # Stratégie 2 : utiliser le paramètre poule de l'URL
    # Toujours forcer la sélection et cliquer Valider (même si la valeur
    # semble déjà correcte) car l'itération de la Stratégie 1 peut avoir
    # laissé le dropdown sur une autre poule.
    target_poule = _extract_poule_from_url(original_url)
    if target_poule:
        _log(f"  📋 Sélection de la poule {target_poule} depuis l'URL...")
        sel = Select(driver.find_element(
            By.CSS_SELECTOR, "select[name='poule-competition']"
        ))
        sel.select_by_value(target_poule)
        time.sleep(1)
        _click_valider(driver)
        time.sleep(2)
        _log(f"  ✅ Poule {target_poule} sélectionnée et validée.")
    else:
        _log("  ℹ️  Pas de paramètre poule dans l'URL, poule par défaut utilisée.")


def _click_valider(driver) -> None:
    """
    Clique sur le bouton 'Valider' s'il est présent sur la page.
    """
    from selenium.webdriver.common.by import By
    try:
        for btn in driver.find_elements(By.CSS_SELECTOR, "button"):
            text = btn.text.strip().lower()
            if "valid" in text or "valider" in text:
                btn.click()
                return
    except Exception:
        pass


def _build_calendar_url(ranking_url: str) -> str:
    """
    Transforme une URL de classement en URL de calendrier.

    Remplace tab=ranking par tab=calendar dans l'URL.

    Args:
        ranking_url: URL de la page de classement.

    Returns:
        URL de la page calendrier.
    """
    parsed = urlparse(ranking_url)
    params = parse_qs(parsed.query, keep_blank_values=True)
    params["tab"] = ["calendar"]
    new_query = urlencode(params, doseq=True)
    return urlunparse(parsed._replace(query=new_query))


def scrape_calendar(
    url: str = COMPETITION_URL,
    team_names: Optional[List[str]] = None,
) -> Optional[List[Fixture]]:
    """
    Récupère le calendrier complet depuis le site de la FFF.

    Args:
        url: URL de la page de classement (sera convertie en URL calendrier).
        team_names: Liste des noms d'équipes connus (pour le matching).

    Returns:
        Liste de Fixture ou None si échec.
    """
    calendar_url = _build_calendar_url(url)
    fixtures = _scrape_calendar_selenium(calendar_url, team_names, original_url=url)

    if fixtures:
        return fixtures

    # Fallback : données de démonstration
    _log("⚠️  Impossible de scraper le calendrier.")
    return None


def _scrape_calendar_selenium(
    url: str,
    team_names: Optional[List[str]] = None,
    original_url: str = COMPETITION_URL,
) -> Optional[List[Fixture]]:
    """
    Scrape le calendrier via Selenium.

    Args:
        url: URL de la page calendrier.
        team_names: Noms d'équipes pour le matching.
        original_url: URL de classement d'origine (pour extraire la poule).

    Returns:
        Liste de Fixture ou None.
    """
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.chrome.service import Service
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.support.ui import WebDriverWait
        from webdriver_manager.chrome import ChromeDriverManager
    except ImportError:
        _log("⚠️  Selenium non installé.")
        return None

    driver = None
    try:
        _log("🌐 Lancement du navigateur pour le calendrier...")
        options = Options()
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--log-level=3")
        options.add_experimental_option("excludeSwitches", ["enable-logging"])

        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)

        _log("📅 Chargement du calendrier...")
        driver.get(url)

        _handle_cookies(driver)

        # Attendre que le contenu soit chargé
        WebDriverWait(driver, SCRAPER_TIMEOUT).until(
            EC.presence_of_element_located((By.TAG_NAME, "h3"))
        )
        time.sleep(2)

        # Sélectionner la bonne poule (le site FFF peut defaulter sur POULE A)
        _select_correct_poule(driver, original_url, team_names)

        # Après _select_correct_poule, le clic sur "Valider" peut faire
        # basculer Angular vers l'onglet classement. On re-navigue vers
        # l'URL calendrier pour s'assurer d'être sur le bon onglet.
        _log("  🔄 Retour sur l'onglet calendrier...")
        driver.get(url)
        time.sleep(3)
        _handle_cookies(driver)
        WebDriverWait(driver, SCRAPER_TIMEOUT).until(
            EC.presence_of_element_located((By.TAG_NAME, "h3"))
        )
        time.sleep(2)

        # Attendre qu'au moins un h3 de journée apparaisse
        _log("📜 Chargement de toutes les journées...")
        for _ in range(15):
            h3_check = driver.find_elements(By.TAG_NAME, "h3")
            if any(re.search(r"JOURN", h.text, re.IGNORECASE) for h in h3_check):
                break
            time.sleep(1)

        # Scroll progressif pour charger toutes les journées (lazy loading)
        last_h3_count = -1
        max_scrolls = 60   # sécurité
        for _ in range(max_scrolls):
            driver.execute_script(
                "window.scrollBy(0, window.innerHeight * 2);"
            )
            time.sleep(0.5)

            h3_elements = driver.find_elements(By.TAG_NAME, "h3")
            current_h3_count = len(h3_elements)

            # Si on n'a plus de nouveaux h3 après quelques scrolls, on arrête
            if current_h3_count == last_h3_count:
                # Un dernier scroll + attente pour être sûr
                driver.execute_script(
                    "window.scrollTo(0, document.body.scrollHeight);"
                )
                time.sleep(1)
                h3_elements = driver.find_elements(By.TAG_NAME, "h3")
                if len(h3_elements) == current_h3_count:
                    break
            last_h3_count = current_h3_count

        # Compter les journées trouvées
        journee_count = sum(
            1 for h3 in h3_elements
            if re.search(r"JOURN", h3.text, re.IGNORECASE)
        )
        _log(f"📅 {journee_count} journées détectées")

        html = driver.page_source
        fixtures = _parse_calendar_html(html, team_names)

        if fixtures:
            played = sum(1 for f in fixtures if f.played)
            remaining = sum(1 for f in fixtures if not f.played)
            _log(f"✅ Calendrier récupéré : {len(fixtures)} matchs ({played} joués, {remaining} restants)")
        else:
            _log("❌ Aucun match trouvé dans le calendrier.")

        return fixtures

    except Exception as e:
        _log(f"❌ Erreur scraping calendrier : {e}")
        return None

    finally:
        if driver:
            driver.quit()


def _parse_calendar_html(
    html: str,
    team_names: Optional[List[str]] = None,
) -> Optional[List[Fixture]]:
    """
    Parse le HTML du calendrier pour extraire les matchs.

    Le calendrier FFF est structuré en journées (h3 "Journée X")
    avec des div.confrontation contenant :
    - <div class="equipe1"> avec <div class="name">
    - <div class="equipe2"> avec <div class="name">
    - <div class="score_match"> avec images (si joué)
    - <div class="date">

    Args:
        html: Code source HTML.
        team_names: Noms connus des équipes pour le matching.

    Returns:
        Liste de Fixture ou None.
    """
    soup = BeautifulSoup(html, "html.parser")
    fixtures = []

    known_teams_map = {}
    if team_names:
        for name in team_names:
            known_teams_map[_normalize_name(name)] = name

    # Approche 1 : utiliser les div.confrontation (structure HTML)
    confrontations = soup.find_all("div", class_="confrontation")
    if confrontations:
        fixtures = _parse_calendar_confrontations(soup, confrontations, known_teams_map)
        if fixtures:
            return fixtures

    # Approche 2 (fallback) : parser le texte brut
    body_text = soup.get_text("\n", strip=True)
    fixtures = _parse_calendar_text(body_text, team_names)

    return fixtures if fixtures else None


def _parse_calendar_confrontations(
    soup: BeautifulSoup,
    confrontations,
    known_teams_map: dict,
) -> List[Fixture]:
    """
    Parse les matchs du calendrier depuis les div.confrontation.

    Associe chaque confrontation à sa journée en remontant dans le DOM
    pour trouver le h3 "Journée X" le plus proche.

    Args:
        soup: Objet BeautifulSoup.
        confrontations: Liste des div.confrontation.
        known_teams_map: Dict nom normalisé -> nom original.

    Returns:
        Liste de Fixture.
    """
    fixtures = []

    # Construire une map journée -> liste de confrontation divs
    # Stratégie : parcourir tous les éléments dans l'ordre du document,
    # et associer chaque confrontation au dernier h3 "Journée X" rencontré.
    current_matchday = 0
    all_elements = soup.find_all(True)  # Tous les tags dans l'ordre du DOM
    confrontation_matchday = {}

    for el in all_elements:
        # Vérifier si c'est un header de journée
        if el.name == "h3":
            text = el.get_text(strip=True)
            m = re.search(r"(?:JOURN[ÉEÉÈ]+E|Journ[ée]+e)\s+(\d+)", text, re.IGNORECASE)
            if m:
                current_matchday = int(m.group(1))

        # Vérifier si c'est une confrontation
        if el.name == "div" and el.get("class") and "confrontation" in el.get("class", []):
            confrontation_matchday[id(el)] = current_matchday

    for conf in confrontations:
        matchday = confrontation_matchday.get(id(conf), 0)
        if matchday == 0:
            continue

        try:
            # Équipes
            eq1_div = conf.find("div", class_="equipe1")
            eq2_div = conf.find("div", class_="equipe2")

            if not eq1_div or not eq2_div:
                continue

            name1_raw = eq1_div.find("div", class_="name")
            name2_raw = eq2_div.find("div", class_="name")

            if not name1_raw or not name2_raw:
                continue

            name1_text = name1_raw.get_text(strip=True)
            name2_text = name2_raw.get_text(strip=True)

            # Matcher avec les noms d'équipes connus
            # Fallback sur le nom brut si le matching échoue
            home_team = (
                _match_team_name(name1_text, known_teams_map)
                if known_teams_map
                else None
            ) or name1_text
            away_team = (
                _match_team_name(name2_text, known_teams_map)
                if known_teams_map
                else None
            ) or name2_text

            # Date
            date_div = conf.find("div", class_="date")
            date_str = date_div.get_text(strip=True) if date_div else ""

            # Score (si joué)
            score_div = conf.find("div", class_="score_match")
            home_goals = None
            away_goals = None
            played = False

            if score_div:
                imgs = score_div.find_all("img", class_="number")
                if len(imgs) >= 2:
                    home_goals = _extract_score_from_img(imgs[0])
                    away_goals = _extract_score_from_img(imgs[1])
                    if home_goals is not None and away_goals is not None:
                        played = True

            # Fallback : est-ce que la date est passée ?
            if not played and date_str:
                match_date = _parse_french_date(date_str)
                if match_date and match_date < datetime.date.today():
                    played = True

            fixture = Fixture(
                matchday=matchday,
                date=date_str,
                home_team=home_team,
                away_team=away_team,
                home_goals=home_goals,
                away_goals=away_goals,
                played=played,
            )
            fixtures.append(fixture)

        except Exception:
            continue

    return fixtures


def _parse_calendar_text(
    text: str,
    team_names: Optional[List[str]] = None,
) -> List[Fixture]:
    """
    Parse le calendrier à partir du texte brut extrait de la page.

    Le texte (issu de BeautifulSoup get_text) sépare les éléments ligne par ligne :
        Journée 1
        dimanche 21 septembre 2025 - 12H45
        LANTONNAIS CS
        2
        -
        PAYS AUROSSAIS FC
        2

    Chaque match commence par une date, suivi de :
    - Lignes de l'équipe domicile (nom + éventuellement numéro)
    - Un séparateur "-"
    - Lignes de l'équipe extérieure (nom + éventuellement numéro)

    Args:
        text: Texte brut de la page.
        team_names: Noms d'équipes connus.

    Returns:
        Liste de Fixture.
    """
    fixtures = []

    known_teams_map = {}
    if team_names:
        for name in team_names:
            known_teams_map[_normalize_name(name)] = name

    if not known_teams_map:
        return fixtures

    lines = text.split("\n")
    current_matchday = 0
    current_date = ""
    match_lines: List[str] = []  # lignes du match en cours

    date_re = re.compile(
        r"^(?:lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)"
        r"\s+\d{1,2}\s+\w+\s+\d{4}\s*-\s*\d{1,2}H\d{2}",
        re.IGNORECASE,
    )

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        # Détecter un header de journée
        journee = re.search(r"JOURN[ÉEÉÈ]+E\s+(\d+)", stripped, re.IGNORECASE)
        if journee:
            # Finaliser le match en cours
            if match_lines and current_matchday > 0:
                f = _parse_match_block(
                    match_lines, current_matchday, current_date, known_teams_map
                )
                if f:
                    fixtures.append(f)
                match_lines = []
            current_matchday = int(journee.group(1))
            continue

        # Détecter une ligne de date
        if date_re.match(stripped):
            # Finaliser le match précédent
            if match_lines and current_matchday > 0:
                f = _parse_match_block(
                    match_lines, current_matchday, current_date, known_teams_map
                )
                if f:
                    fixtures.append(f)
            current_date = stripped
            match_lines = []
            continue

        # Sinon, c'est une ligne du match en cours
        if current_matchday > 0 and current_date:
            match_lines.append(stripped)

    # Ne pas oublier le dernier match
    if match_lines and current_matchday > 0:
        f = _parse_match_block(
            match_lines, current_matchday, current_date, known_teams_map
        )
        if f:
            fixtures.append(f)

    return fixtures


def _parse_match_block(
    lines: List[str],
    matchday: int,
    date: str,
    known_teams_map: dict,
) -> Optional[Fixture]:
    """
    Parse un bloc de lignes correspondant à un match.

    Format typique :
        TEAM_NAME        (ex: LANTONNAIS CS)
        [NUMBER]         (ex: 2 - numéro d'équipe, optionnel)
        -                (séparateur)
        TEAM_NAME        (ex: PAYS AUROSSAIS FC)
        [NUMBER]         (ex: 2 - optionnel)

    Args:
        lines: Lignes entre la date et la prochaine date/journée.
        matchday: Numéro de journée.
        date: Texte de la date.
        known_teams_map: Dict nom normalisé -> nom original.

    Returns:
        Fixture ou None.
    """
    # Trouver le séparateur "-"
    separator_idx = None
    for i, line in enumerate(lines):
        if line.strip() == "-":
            separator_idx = i
            break

    if separator_idx is None:
        return None

    # Reconstruire les noms domicile / extérieur
    home_text = " ".join(lines[:separator_idx]).strip()
    away_text = " ".join(lines[separator_idx + 1 :]).strip()

    if not home_text or not away_text:
        return None

    home_team = _match_team_name(home_text, known_teams_map) or home_text
    away_team = _match_team_name(away_text, known_teams_map) or away_text

    # Déterminer si joué à partir de la date
    match_date = _parse_french_date(date)
    played = match_date < datetime.date.today() if match_date else False

    return Fixture(
        matchday=matchday,
        date=date,
        home_team=home_team,
        away_team=away_team,
        played=played,
    )


def _match_team_name(text: str, known_teams_map: dict) -> Optional[str]:
    """
    Essaie de faire correspondre un texte à un nom d'équipe connu.

    Teste d'abord un match exact (normalisé), puis un match partiel.

    Args:
        text: Texte reconstruit (ex: "LANTONNAIS CS 2").
        known_teams_map: Dict nom normalisé -> nom original.

    Returns:
        Nom original de l'équipe ou None.
    """
    normalized = _normalize_name(text)

    # Match exact
    if normalized in known_teams_map:
        return known_teams_map[normalized]

    # Match partiel : le texte contient le nom d'équipe ou vice versa
    best_match = None
    best_len = 0
    for norm_name, original in known_teams_map.items():
        if norm_name in normalized or normalized in norm_name:
            if len(norm_name) > best_len:
                best_match = original
                best_len = len(norm_name)

    return best_match


def _parse_french_date(date_str: str) -> Optional[datetime.date]:
    """
    Parse une date française FFF (ex: 'DIMANCHE 21 SEPTEMBRE 2025 - 15H00').

    Returns:
        datetime.date ou None.
    """
    months = {
        "janvier": 1, "fevrier": 2, "mars": 3, "avril": 4,
        "mai": 5, "juin": 6, "juillet": 7, "aout": 8,
        "septembre": 9, "octobre": 10, "novembre": 11, "decembre": 12,
    }

    m = re.search(r"(\d{1,2})\s+(\w+)\s+(\d{4})", date_str, re.IGNORECASE)
    if not m:
        return None

    day = int(m.group(1))
    month_name = _normalize_name(m.group(2))
    year = int(m.group(3))
    month = months.get(month_name, 0)

    if month:
        try:
            return datetime.date(year, month, day)
        except ValueError:
            return None

    return None


def _try_parse_match_line(
    line: str,
    matchday: int,
    date: str,
    known_teams_map: dict,
) -> Optional[Fixture]:
    """
    Tente de parser une ligne comme un match.

    Stratégie : on essaie de reconnaître 2 noms d'équipe connus dans la ligne,
    séparés par un score ("X - Y") ou juste un tiret.

    Args:
        line: Ligne de texte.
        matchday: Journée actuelle.
        date: Date du match.
        known_teams_map: Dict normalisé -> nom original.

    Returns:
        Fixture ou None.
    """
    normalized_line = _normalize_name(line)

    # Trouver toutes les équipes présentes dans la ligne
    found_teams = []
    for norm_name, original_name in known_teams_map.items():
        if norm_name in normalized_line:
            # Stocker la position pour trier gauche -> droite (domicile vs extérieur)
            pos = normalized_line.find(norm_name)
            found_teams.append((pos, original_name, norm_name))

    if len(found_teams) < 2:
        return None

    # Résoudre les ambiguïtés (un nom court peut être contenu dans un plus long)
    found_teams = _resolve_team_ambiguity(found_teams)

    if len(found_teams) < 2:
        return None

    # Trier par position dans la ligne : le premier = domicile
    found_teams.sort(key=lambda x: x[0])
    home_team = found_teams[0][1]
    away_team = found_teams[1][1]

    # Chercher un score entre les deux noms d'équipe
    home_norm = found_teams[0][2]
    away_norm = found_teams[1][2]

    # Extraire la partie entre les deux noms
    home_end = normalized_line.find(home_norm) + len(home_norm)
    away_start = normalized_line.find(away_norm)
    between = normalized_line[home_end:away_start].strip()

    # Essayer de trouver un score "X - Y" ou "X-Y"
    score_match = re.search(r"(\d+)\s*-\s*(\d+)", between)

    if score_match:
        return Fixture(
            matchday=matchday,
            date=date,
            home_team=home_team,
            away_team=away_team,
            home_goals=int(score_match.group(1)),
            away_goals=int(score_match.group(2)),
            played=True,
        )
    else:
        # Match pas encore joué
        return Fixture(
            matchday=matchday,
            date=date,
            home_team=home_team,
            away_team=away_team,
            played=False,
        )


def _resolve_team_ambiguity(
    found_teams: List[Tuple[int, str, str]],
) -> List[Tuple[int, str, str]]:
    """
    Résout les ambiguïtés quand un nom d'équipe court est contenu dans un plus long.

    Ex: "GRAVES FC 4" contient "GRAVES FC" — on garde le plus long.
    On vérifie le chevauchement réel des positions dans la ligne.
    """
    resolved = []
    found_teams_sorted = sorted(found_teams, key=lambda x: -len(x[2]))

    for pos, original, norm in found_teams_sorted:
        is_subset = False
        for r_pos, r_original, r_norm in resolved:
            # Vérifier si un nom est un sous-ensemble textuel de l'autre
            if norm in r_norm and norm != r_norm:
                is_subset = True
                break

            # Vérifier le chevauchement réel des plages de caractères
            end_new = pos + len(norm)
            end_existing = r_pos + len(r_norm)
            ranges_overlap = not (end_new <= r_pos or end_existing <= pos)

            if ranges_overlap and len(norm) < len(r_norm):
                is_subset = True
                break

        if not is_subset:
            resolved.append((pos, original, norm))

    return resolved


def _normalize_name(name: str) -> str:
    """Normalise un nom d'équipe pour la comparaison."""
    import unicodedata

    # Retirer les accents
    name = unicodedata.normalize("NFD", name)
    name = "".join(c for c in name if unicodedata.category(c) != "Mn")
    # Minuscules, retirer les espaces multiples
    name = name.lower().strip()
    name = re.sub(r"\s+", " ", name)
    # Supprimer l'espace avant un chiffre de suffixe en fin de nom
    # Ex: "graves fc 4" et "graves fc4" → "graves fc4"
    name = re.sub(r"\s+(\d+)$", r"\1", name)
    return name


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
# Scraping des résultats (scores) depuis l'onglet Résultats
# ============================================================


def _build_results_url(ranking_url: str) -> str:
    """Transforme une URL de classement en URL de résultats."""
    parsed = urlparse(ranking_url)
    params = parse_qs(parsed.query, keep_blank_values=True)
    params["tab"] = ["results"]
    new_query = urlencode(params, doseq=True)
    return urlunparse(parsed._replace(query=new_query))


def scrape_results(
    url: str = COMPETITION_URL,
    team_names: Optional[List[str]] = None,
    max_journee: int = 22,
) -> Optional[List[Fixture]]:
    """
    Scrape les résultats (avec scores) de toutes les journées jouées.

    Le site FFF affiche les scores sous forme d'images dans l'URL :
    /img/scores/origin/X.png → score = X

    Args:
        url: URL de la page classement (sera convertie en résultats).
        team_names: Liste des noms d'équipes connus.
        max_journee: Nombre max de journées à scraper.

    Returns:
        Liste de Fixture avec les scores remplis, ou None.
    """
    results_url = _build_results_url(url)

    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.chrome.service import Service
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.support.ui import Select, WebDriverWait
        from webdriver_manager.chrome import ChromeDriverManager
    except ImportError:
        _log("⚠️  Selenium non installé.")
        return None

    driver = None
    all_fixtures: List[Fixture] = []

    try:
        _log("🌐 Lancement du navigateur pour les résultats...")
        options = Options()
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--log-level=3")
        options.add_experimental_option("excludeSwitches", ["enable-logging"])

        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)

        driver.get(results_url)
        time.sleep(3)
        _handle_cookies(driver)

        # Sélectionner la bonne poule (le site FFF peut defaulter sur POULE A)
        _select_correct_poule(driver, url, team_names)

        # Trouver le dropdown de journée et les journées disponibles
        select_elem = WebDriverWait(driver, SCRAPER_TIMEOUT).until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, "select[name='journee']")
            )
        )
        sel = Select(select_elem)
        journees = [
            o.get_attribute("value")
            for o in sel.options
            if o.get_attribute("value").strip()
        ]
        _log(f"📊 {len(journees)} journées disponibles")

        # Scraper chaque journée
        empty_streak = 0  # Journées vides consécutives
        for j_val in journees:
            j_num = int(j_val)
            if j_num > max_journee:
                break

            # Sélectionner la journée
            select_elem = driver.find_element(
                By.CSS_SELECTOR, "select[name='journee']"
            )
            Select(select_elem).select_by_value(j_val)
            time.sleep(0.5)

            # Cliquer sur Valider
            for btn in driver.find_elements(By.CSS_SELECTOR, "button"):
                if "valid" in btn.text.strip().lower():
                    btn.click()
                    break
            time.sleep(2)

            # Parser les résultats de cette journée
            soup = BeautifulSoup(driver.page_source, "html.parser")
            j_fixtures = _parse_results_html(soup, j_num, team_names)
            scored = [f for f in j_fixtures if f.played]
            all_fixtures.extend(j_fixtures)

            if scored:
                _log(f"  J{j_num}: {len(scored)} matchs avec score")
                empty_streak = 0
            else:
                _log(f"  J{j_num}: pas de résultats")
                empty_streak += 1
                # Arrêter après 3 journées vides consécutives
                if empty_streak >= 3:
                    _log("  (3 journées vides consécutives, arrêt)")
                    break

        if all_fixtures:
            played = sum(1 for f in all_fixtures if f.played)
            _log(
                f"✅ Résultats récupérés : {len(all_fixtures)} matchs, "
                f"{played} avec score"
            )
        else:
            _log("❌ Aucun résultat trouvé.")

        return all_fixtures if all_fixtures else None

    except Exception as e:
        _log(f"❌ Erreur scraping résultats : {e}")
        return all_fixtures if all_fixtures else None

    finally:
        if driver:
            driver.quit()


def _parse_results_html(
    soup: BeautifulSoup,
    matchday: int,
    team_names: Optional[List[str]] = None,
) -> List[Fixture]:
    """
    Parse les résultats d'une journée depuis le HTML.

    Chaque match est dans un <div class="confrontation"> contenant :
    - <div class="equipe1"> avec <div class="name">
    - <div class="equipe2"> avec <div class="name">
    - <div class="score_match"> avec des <img class="number" src="...X.png">
    - <div class="date"> avec la date

    Args:
        soup: Objet BeautifulSoup de la page.
        matchday: Numéro de la journée.
        team_names: Noms d'équipes connus.

    Returns:
        Liste de Fixture.
    """
    fixtures = []
    known_teams_map = {}
    if team_names:
        for name in team_names:
            known_teams_map[_normalize_name(name)] = name

    confrontations = soup.find_all("div", class_="confrontation")

    for conf in confrontations:
        try:
            # Équipes
            eq1_div = conf.find("div", class_="equipe1")
            eq2_div = conf.find("div", class_="equipe2")

            if not eq1_div or not eq2_div:
                continue

            name1_raw = eq1_div.find("div", class_="name")
            name2_raw = eq2_div.find("div", class_="name")

            if not name1_raw or not name2_raw:
                continue

            name1_text = name1_raw.get_text(strip=True)
            name2_text = name2_raw.get_text(strip=True)

            # Matcher avec les noms d'équipes connus
            # Fallback sur le nom brut si le matching échoue
            home_team = (
                _match_team_name(name1_text, known_teams_map)
                if known_teams_map
                else None
            ) or name1_text
            away_team = (
                _match_team_name(name2_text, known_teams_map)
                if known_teams_map
                else None
            ) or name2_text

            # Date
            date_div = conf.find("div", class_="date")
            date_str = date_div.get_text(strip=True) if date_div else ""

            # Score : les buts sont dans les images du score_match
            score_div = conf.find("div", class_="score_match")
            home_goals = None
            away_goals = None
            played = False

            if score_div:
                imgs = score_div.find_all("img", class_="number")
                if len(imgs) >= 2:
                    home_goals = _extract_score_from_img(imgs[0])
                    away_goals = _extract_score_from_img(imgs[1])
                    if home_goals is not None and away_goals is not None:
                        played = True

            # Vérifier les forfaits
            forfeit1 = eq1_div.find("div", class_="forfeit")
            forfeit2 = eq2_div.find("div", class_="forfeit")
            has_forfeit = False
            if forfeit1 and forfeit1.get_text(strip=True):
                has_forfeit = True
            if forfeit2 and forfeit2.get_text(strip=True):
                has_forfeit = True

            fixture = Fixture(
                matchday=matchday,
                date=date_str,
                home_team=home_team,
                away_team=away_team,
                home_goals=home_goals,
                away_goals=away_goals,
                played=played,
            )
            fixtures.append(fixture)

        except Exception:
            continue

    return fixtures


def _extract_score_from_img(img_tag) -> Optional[int]:
    """
    Extrait le score depuis une balise <img>.

    Le site FFF encode les scores dans le nom du fichier image :
    /wp-content/themes/fff/inc/frontOffice/img/scores/origin/3.png → 3

    Args:
        img_tag: Balise <img> BeautifulSoup.

    Returns:
        Score (int) ou None.
    """
    src = img_tag.get("src", "")
    # Extraire le chiffre du nom de fichier
    match = re.search(r"/(\d+)\.png", src)
    if match:
        return int(match.group(1))
    return None


# ============================================================
# Calcul des statistiques détaillées par équipe
# ============================================================


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
    # Collecter les résultats par équipe dans l'ordre chronologique
    # On utilise la date réelle du match (pas le numéro de journée)
    # car certains matchs sont décalés/reportés
    team_results: Dict[str, List[Tuple[datetime.date, int, str]]] = defaultdict(list)

    # Fonction de tri : par date réelle si disponible, sinon par journée
    def _sort_key(f: Fixture):
        parsed = _parse_french_date(f.date) if f.date else None
        # date réelle en priorité ; sinon date lointaine + journée pour garder l'ordre
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
        match_date = _parse_french_date(fixture.date) if fixture.date else None
        # Fallback : date fictive basée sur la journée si pas de date parsable
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
