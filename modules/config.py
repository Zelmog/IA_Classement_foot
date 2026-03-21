"""
Configuration du projet IA Classement Foot.
Contient les constantes et paramètres du projet.
"""

# ============================================================
# URL de la compétition à scraper
# ============================================================
COMPETITION_URL = (
    "https://gironde.fff.fr/competitions"
    "?tab=ranking&id=435749&phase=1&poule=1&type=ch"
)

COMPETITION_NAME = "SENIORS DÉPARTEMENTAL 3 - Gironde"

# ============================================================
# Compétitions multiples (Équipe A et Équipe B)
# ============================================================
COMPETITIONS = {
    "A": {
        "name": "Équipe A",
        "url": (
            "https://gironde.fff.fr/competitions"
            "?tab=ranking&id=435747&phase=1&poule=1&type=ch"
        ),
    },
    "B": {
        "name": "Équipe B",
        "url": (
            "https://gironde.fff.fr/competitions"
            "?tab=ranking&id=435749&phase=1&poule=1&type=ch"
        ),
    },
}

# ============================================================
# Paramètres de simulation Monte Carlo
# ============================================================

# Nombre de simulations à effectuer (plus = plus précis mais plus lent)
N_SIMULATIONS = 50_000

# Nombre total de matchs par équipe dans la saison
# Double aller-retour pour 12 équipes : 2 × (12-1) = 22 matchs
TOTAL_MATCHES_PER_TEAM = 22

# Nombre d'équipes promues (montée)
PROMOTION_SPOTS = 2

# Nombre d'équipes reléguées (descente)
RELEGATION_SPOTS = 2

# ============================================================
# Système de points
# ============================================================
WIN_POINTS = 3
DRAW_POINTS = 1
LOSS_POINTS = 0

# ============================================================
# Paramètres du scraper
# ============================================================

# Temps d'attente maximum (secondes) pour le chargement de la page
SCRAPER_TIMEOUT = 15

# Fichier de sauvegarde des données scrapées (fallback)
DATA_BACKUP_FILE = "data/dernier_classement.json"

# ============================================================
# Paramètres d'affichage
# ============================================================

# Couleurs du thème
THEME_PRIMARY = "cyan"
THEME_SUCCESS = "green"
THEME_WARNING = "yellow"
THEME_DANGER = "red"
THEME_INFO = "blue"
