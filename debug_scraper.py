"""
Script de debug : dump le HTML des pages calendrier et résultats FFF
pour diagnostiquer les problèmes de parsing.
"""
import time
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from modules.config import COMPETITION_URL, SCRAPER_TIMEOUT
from modules.scraper import _build_calendar_url, _build_results_url, _handle_cookies

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select, WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager


def get_driver():
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--log-level=3")
    options.add_experimental_option("excludeSwitches", ["enable-logging"])
    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=options)


def dump_calendar():
    print("=" * 60)
    print("DUMP CALENDRIER")
    print("=" * 60)

    url = _build_calendar_url(COMPETITION_URL)
    print(f"URL: {url}")

    driver = get_driver()
    try:
        driver.get(url)
        time.sleep(3)
        _handle_cookies(driver)

        WebDriverWait(driver, SCRAPER_TIMEOUT).until(
            EC.presence_of_element_located((By.TAG_NAME, "h3"))
        )
        time.sleep(2)

        # Scroll
        for _ in range(30):
            driver.execute_script("window.scrollBy(0, window.innerHeight * 2);")
            time.sleep(0.3)

        html = driver.page_source

        # Save full HTML
        with open("data/debug_calendar.html", "w", encoding="utf-8") as f:
            f.write(html)
        print(f"HTML sauvé: data/debug_calendar.html ({len(html)} chars)")

        # Extract text
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text("\n", strip=True)

        with open("data/debug_calendar_text.txt", "w", encoding="utf-8") as f:
            f.write(text)
        print(f"Texte sauvé: data/debug_calendar_text.txt ({len(text)} chars)")

        # Show first 3000 chars of text
        print("\n--- EXTRAIT TEXTE (3000 premiers chars) ---")
        print(text[:3000])
        print("--- FIN EXTRAIT ---\n")

        # Show h3 elements
        h3s = soup.find_all("h3")
        print(f"\n{len(h3s)} éléments h3:")
        for h3 in h3s[:5]:
            print(f"  h3: '{h3.get_text(strip=True)}'")

        # Show confrontation divs
        confrontations = soup.find_all("div", class_="confrontation")
        print(f"\n{len(confrontations)} div.confrontation")

        # Show some relevant divs
        for cls in ["match", "equipe", "rencontre", "game", "fixture"]:
            divs = soup.find_all("div", class_=lambda c: c and cls in str(c).lower())
            if divs:
                print(f"\ndiv contenant '{cls}': {len(divs)}")
                if divs:
                    print(f"  Premier: {str(divs[0])[:300]}")

    finally:
        driver.quit()


def dump_results():
    print("\n" + "=" * 60)
    print("DUMP RÉSULTATS (J1)")
    print("=" * 60)

    url = _build_results_url(COMPETITION_URL)
    print(f"URL: {url}")

    driver = get_driver()
    try:
        driver.get(url)
        time.sleep(3)
        _handle_cookies(driver)

        # Select J1
        select_elem = WebDriverWait(driver, SCRAPER_TIMEOUT).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "select[name='journee']"))
        )
        sel = Select(select_elem)
        journees = [o.get_attribute("value") for o in sel.options if o.get_attribute("value").strip()]
        print(f"Journées: {journees[:5]}...")

        # Sélectionner J1
        Select(select_elem).select_by_value(journees[0])
        time.sleep(0.5)

        # Cliquer Valider
        for btn in driver.find_elements(By.CSS_SELECTOR, "button"):
            if "valid" in btn.text.strip().lower():
                btn.click()
                break
        time.sleep(3)

        html = driver.page_source

        with open("data/debug_results.html", "w", encoding="utf-8") as f:
            f.write(html)
        print(f"HTML sauvé: data/debug_results.html ({len(html)} chars)")

        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")

        # Show confrontation divs
        confrontations = soup.find_all("div", class_="confrontation")
        print(f"\n{len(confrontations)} div.confrontation")

        if confrontations:
            print(f"\nPremier confrontation:")
            print(str(confrontations[0])[:1000])
        else:
            # Chercher d'autres structures
            print("\nRecherche d'autres structures...")
            for cls in ["match", "score", "rencontre", "game", "equipe", "team"]:
                divs = soup.find_all(lambda tag: tag.name and tag.get("class") and any(cls in c.lower() for c in tag.get("class", [])))
                if divs:
                    print(f"\n  Éléments avec classe contenant '{cls}': {len(divs)}")
                    print(f"    Premier: {str(divs[0])[:400]}")

            # Show text extract
            text = soup.get_text("\n", strip=True)
            with open("data/debug_results_text.txt", "w", encoding="utf-8") as f:
                f.write(text)
            print(f"\nTexte sauvé: data/debug_results_text.txt ({len(text)} chars)")
            print("\n--- EXTRAIT TEXTE (2000 premiers chars) ---")
            print(text[:2000])
            print("--- FIN EXTRAIT ---")

    finally:
        driver.quit()


if __name__ == "__main__":
    os.makedirs("data", exist_ok=True)
    dump_calendar()
    dump_results()
    print("\n✅ Debug terminé.")
