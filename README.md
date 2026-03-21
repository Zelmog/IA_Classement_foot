# ⚽ IA Classement Foot

Prédiction des chances de montée et de descente pour les équipes de football à partir du classement actuel, grâce à la **simulation Monte Carlo** et la **distribution de Poisson**.

## 📖 Description

Ce projet récupère automatiquement le classement d'une compétition de football depuis le site de la **Fédération Française de Football (FFF)**, puis utilise une intelligence artificielle statistique pour prédire les chances de montée (et descente) de chaque équipe en fin de saison.

**Compétition par défaut :** SENIORS DÉPARTEMENTAL 3 — District de la Gironde

## ✨ Fonctionnalités

- 🌐 **Scraping automatique** du classement depuis le site FFF (Selenium)
- 🤖 **Simulation Monte Carlo** (10 000 scénarios par défaut)
- ⚽ **Modèle de Poisson** pour des scores réalistes
- 📊 **Force offensive/défensive** calculée pour chaque équipe
- 🏆 **Classement par chances de montée**
- 🔍 **Analyse détaillée** par équipe (forme, statistiques, distribution des positions)
- 💾 **Sauvegarde automatique** des données scrapées (fallback si le site est inaccessible)
- 🎨 **Interface terminal enrichie** avec Rich
- ⚙️ **Paramètres personnalisables** (nombre de simulations, places de montée, etc.)

## 🧠 Comment ça marche ?

### 1. Collecte des données
Le scraper charge la page du classement FFF en utilisant un navigateur headless (Chrome) pour gérer le rendu JavaScript, puis extrait le tableau (points, matchs joués, victoires, buts, etc.).

### 2. Calcul de la force des équipes
Pour chaque équipe, on calcule :
- **Force offensive** = (buts marqués / match) ÷ (moyenne de la ligue)
- **Force défensive** = (buts encaissés / match) ÷ (moyenne de la ligue)

Une régression vers la moyenne est appliquée pour les équipes ayant joué peu de matchs.

### 3. Simulation Monte Carlo
Pour chaque simulation (×10 000) :
1. Les matchs restants sont générés aléatoirement
2. Chaque match est simulé avec la **distribution de Poisson** : les buts attendus dépendent de la force offensive de l'attaquant et de la force défensive du défenseur
3. Les points sont attribués (3-1-0)
4. Le classement final est calculé

### 4. Résultats
On obtient pour chaque équipe :
- La **probabilité de montée** (% de simulations où l'équipe finit dans les places de montée)
- La **probabilité de descente**
- La **position finale moyenne** prédite
- Les **points finaux prédits**

## 🚀 Installation

### Prérequis
- **Python 3.9+**
- **Google Chrome** installé (pour le scraping Selenium)

### Étapes

```bash
# 1. Cloner le projet
git clone <url-du-repo>
cd IA_classement_foot

# 2. Créer un environnement virtuel (recommandé)
python -m venv venv
venv\Scripts\activate  # Windows
# source venv/bin/activate  # Linux/Mac

# 3. Installer les dépendances
pip install -r requirements.txt
```

## ▶️ Utilisation

```bash
python main.py
```

### Menu interactif
```
[1] 📊 Voir le classement actuel
[2] 🔮 Lancer la prédiction
[3] 🏆 Classement par chances de montée
[4] 🔍 Analyse détaillée d'une équipe
[5] 🔄 Rafraîchir les données (re-scraper)
[6] ⚙️  Modifier les paramètres
[0] 🚪 Quitter
```

Au démarrage, le programme :
1. Scrape automatiquement le classement (ou charge les données de démonstration)
2. Lance une première simulation
3. Affiche les résultats et le menu interactif

## 📁 Structure du Projet

```
IA_classement_foot/
├── main.py                  # Point d'entrée principal
├── modules/
│   ├── __init__.py          # Initialisation du package
│   ├── config.py            # Configuration et constantes
│   ├── models.py            # Classes de données (Team, PredictionResult)
│   ├── scraper.py           # Scraping du classement FFF
│   ├── predictor.py         # Moteur de simulation Monte Carlo
│   └── display.py           # Affichage terminal avec Rich
├── data/                    # Données sauvegardées (auto-généré)
│   └── dernier_classement.json
├── requirements.txt         # Dépendances Python
├── .gitignore               # Fichiers à ignorer par Git
└── README.md                # Ce fichier
```

## ⚙️ Configuration

Les paramètres par défaut sont dans `modules/config.py` :

| Paramètre | Valeur par défaut | Description |
|---|---|---|
| `N_SIMULATIONS` | 10 000 | Nombre de scénarios simulés |
| `TOTAL_MATCHES_PER_TEAM` | 22 | Matchs totaux par équipe (auto-détecté) |
| `PROMOTION_SPOTS` | 2 | Nombre de places de montée |
| `RELEGATION_SPOTS` | 2 | Nombre de places de descente |

Ces paramètres peuvent aussi être modifiés via le menu interactif (option 6).

## 📦 Dépendances

| Package | Usage |
|---|---|
| `numpy` | Calculs statistiques et distribution de Poisson |
| `rich` | Affichage terminal enrichi (tableaux, couleurs, barres) |
| `selenium` | Scraping web (navigateur headless) |
| `webdriver-manager` | Gestion automatique du ChromeDriver |
| `beautifulsoup4` | Parsing HTML |

## 🔬 Précision du modèle

Le modèle est une **approximation statistique** basée sur les performances actuelles. Sa précision augmente au fil de la saison :
- **Début de saison** (< 30% joué) : prédictions très incertaines
- **Mi-saison** (~50% joué) : tendances fiables
- **Fin de saison** (> 75% joué) : prédictions précises

Les limites du modèle :
- Ne prend pas en compte les transferts, blessures ou suspensions
- Ne connaît pas le calendrier exact des matchs restants
- Les confrontations directes ne sont pas modélisées précisément
- Les conditions météo, le terrain, le public ne sont pas intégrés

## 📄 Licence

Projet réalisé à des fins éducatives. Les données proviennent du site de la FFF.
