"""
IA Classement Foot - Application Streamlit
===========================================
Dashboard de prédictions de montée/descente par simulation Monte Carlo.
"""

import streamlit as st
import pandas as pd

from modules.config import (
    COMPETITIONS,
    N_SIMULATIONS,
    PROMOTION_SPOTS,
    RELEGATION_SPOTS,
    TOTAL_MATCHES_PER_TEAM,
)
from modules.scraper import (
    scrape_competition,
    compute_team_stats,
    get_remaining_fixtures,
    get_calendar_summary,
)
from modules.predictor import PromotionPredictor

# ─── Config page ──────────────────────────────────────────────
st.set_page_config(
    page_title="IA Classement Foot",
    page_icon="⚽",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ─── CSS custom (dark theme cohérent) ────────────────────────
st.markdown("""
<style>
    /* Badges forme V/N/D */
    .form-badge {
        display: inline-flex; align-items: center; justify-content: center;
        width: 26px; height: 26px; border-radius: 5px;
        font-weight: 700; font-size: 0.75rem; margin: 0 1px;
    }
    .form-V { background: rgba(25,135,84,0.3); color: #3fb950; }
    .form-N { background: rgba(255,193,7,0.3); color: #f0c000; }
    .form-D { background: rgba(220,53,69,0.3); color: #f85149; }

    /* Ligne promotion / relegation */
    .promo-row { border-left: 3px solid #198754; }
    .releg-row { border-left: 3px solid #dc3545; }

    /* Tabs styling */
    .stTabs [data-baseweb="tab-list"] { gap: 8px; }
    .stTabs [data-baseweb="tab"] { padding: 8px 20px; font-weight: 600; }

    /* Responsive table */
    .dataframe { font-size: 0.85rem !important; }
</style>
""", unsafe_allow_html=True)


# ─── Session state init ──────────────────────────────────────
def _init_state():
    if "data" not in st.session_state:
        st.session_state.data = {}
    if "loaded" not in st.session_state:
        st.session_state.loaded = set()

_init_state()


# ─── Fonctions de chargement (avec cache Streamlit) ──────────

@st.cache_data(ttl=1800, show_spinner=False)
def load_competition(key: str, url: str):
    """Charge une compétition complète (classement + résultats + calendrier)."""
    teams, result_fixtures, calendar_fixtures = scrape_competition(url)
    return teams, result_fixtures, calendar_fixtures


def get_comp_data(key: str):
    """Retourne les données d'une compétition (depuis session_state)."""
    return st.session_state.data.get(key, {})


def load_and_store(key: str):
    """Charge et stocke les données d'une compétition dans le session_state."""
    comp = COMPETITIONS[key]
    teams, result_fixtures, calendar_fixtures = load_competition(key, comp["url"])

    data = {"teams": teams, "result_fixtures": result_fixtures,
            "calendar_fixtures": calendar_fixtures,
            "team_stats": None, "predictions": None, "predictor": None}

    if teams:
        team_names = [t.name for t in teams]

        # Auto detect total matches
        n = len(teams)
        max_played = max(t.matches_played for t in teams)
        single = n - 1
        double = 2 * (n - 1)
        total_matches = double if max_played > single else single

        # Team stats
        if result_fixtures:
            played = [f for f in result_fixtures if f.played]
            data["team_stats"] = compute_team_stats(played, team_names)

        # Prediction
        real_fixtures = None
        if calendar_fixtures:
            real_fixtures = get_remaining_fixtures(calendar_fixtures)

        predictor = PromotionPredictor(
            teams=teams,
            total_matches=total_matches,
            n_simulations=N_SIMULATIONS,
            promotion_spots=PROMOTION_SPOTS,
            relegation_spots=RELEGATION_SPOTS,
            fixtures=real_fixtures,
            team_stats=data["team_stats"],
        )
        data["predictions"] = predictor.simulate()
        data["predictor"] = predictor

    st.session_state.data[key] = data
    st.session_state.loaded.add(key)


# ─── Compétition switcher ────────────────────────────────────
comp_keys = list(COMPETITIONS.keys())
comp_names = [COMPETITIONS[k]["name"] for k in comp_keys]

cols = st.columns(len(comp_keys) + 2)
cols[0].markdown("### ⚽ IA Classement Foot")

selected_key = st.session_state.get("comp_key", comp_keys[0])
for i, k in enumerate(comp_keys):
    if cols[i + 1].button(
        COMPETITIONS[k]["name"],
        key=f"btn_{k}",
        type="primary" if k == selected_key else "secondary",
        use_container_width=True,
    ):
        st.session_state.comp_key = k
        selected_key = k

key = selected_key

# ─── Chargement auto au premier accès ────────────────────────
if key not in st.session_state.loaded:
    with st.spinner(f"Chargement de {COMPETITIONS[key]['name']}... (peut prendre 1-2 min au premier accès)"):
        load_and_store(key)

data = get_comp_data(key)
teams = data.get("teams", [])
predictions = data.get("predictions")
team_stats = data.get("team_stats")
predictor = data.get("predictor")
calendar_fixtures = data.get("calendar_fixtures")

# ─── Bouton rafraîchir ───────────────────────────────────────
with st.sidebar:
    st.header("Actions")
    if st.button("🔄 Rafraîchir les données", use_container_width=True):
        load_competition.clear()
        st.session_state.loaded.discard(key)
        st.rerun()
    st.divider()
    st.caption(f"Simulations: {N_SIMULATIONS:,}")
    st.caption(f"Montées: {PROMOTION_SPOTS} | Descentes: {RELEGATION_SPOTS}")

# ─── Si pas de données ───────────────────────────────────────
if not teams:
    st.error("Impossible de charger les données. Le scraping a échoué.")
    st.info("Réessayez dans quelques instants ou vérifiez que le site FFF est accessible.")
    st.stop()

# ─── Onglets principaux ──────────────────────────────────────
tab_classement, tab_forme, tab_calendrier = st.tabs([
    "📊 Classement & Prédictions", "📈 Forme", "📅 Calendrier"
])


# ═══════════════════════════════════════════════════════════════
# ONGLET : CLASSEMENT & PRÉDICTIONS
# ═══════════════════════════════════════════════════════════════
with tab_classement:
    # Stats rapides
    season_progress = predictor.get_season_progress() if predictor else 0.0
    calendar_summary = get_calendar_summary(calendar_fixtures) if calendar_fixtures else None

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Équipes", len(teams))
    c2.metric("Saison", f"{season_progress:.0f}%")
    c3.metric("Montées", PROMOTION_SPOTS)
    c4.metric("Descentes", RELEGATION_SPOTS)

    if calendar_summary:
        st.caption(
            f"📅 Calendrier : {calendar_summary['played']} joués / "
            f"{calendar_summary['remaining']} restants "
            f"(J{calendar_summary['current_matchday']}/{calendar_summary['total_matchdays']})"
        )

    # Tableau classement
    pred_map = {}
    if predictions:
        for p in predictions:
            pred_map[p.team_name] = p

    rows = []
    for team in teams:
        pred = pred_map.get(team.name)
        ts = team_stats.get(team.name) if team_stats else None

        row = {
            "#": team.rank,
            "Équipe": team.name,
            "Pts": team.points,
            "MJ": team.matches_played,
            "V": team.wins,
            "N": team.draws,
            "D": team.losses,
            "Diff": team.goal_difference,
        }

        if predictions:
            row["Montée %"] = f"{pred.promotion_probability:.1f}" if pred else "-"
            row["Desc. %"] = f"{pred.relegation_probability:.1f}" if pred else "-"
            row["Pos moy"] = f"{pred.avg_final_position:.1f}" if pred else "-"

        if team_stats and ts:
            form_html = ""
            for r in ts.recent_results[-5:]:
                form_html += f'<span class="form-badge form-{r}">{r}</span>'
            row["Forme"] = form_html
        elif team_stats:
            row["Forme"] = "-"

        rows.append(row)

    df = pd.DataFrame(rows)

    # Style conditionnel
    def highlight_rows(row):
        styles = [""] * len(row)
        rank = row["#"]
        n_teams = len(teams)
        if rank <= PROMOTION_SPOTS:
            styles = [f"background-color: rgba(25,135,84,0.15); border-left: 3px solid #198754"] * len(row)
        elif rank > n_teams - RELEGATION_SPOTS:
            styles = [f"background-color: rgba(220,53,69,0.15); border-left: 3px solid #dc3545"] * len(row)
        return styles

    # Formatter les colonnes numériques
    def color_diff(val):
        try:
            v = int(val)
            if v > 0:
                return "color: #3fb950"
            elif v < 0:
                return "color: #f85149"
        except (ValueError, TypeError):
            pass
        return "color: #8b949e"

    def color_montee(val):
        try:
            v = float(val)
            if v >= 70:
                return "color: #3fb950; font-weight: 700"
            elif v >= 40:
                return "color: #f0c000; font-weight: 600"
        except (ValueError, TypeError):
            pass
        return "color: #8b949e"

    def color_descente(val):
        try:
            v = float(val)
            if v >= 40:
                return "color: #f85149; font-weight: 700"
            elif v >= 15:
                return "color: #f0c000; font-weight: 600"
        except (ValueError, TypeError):
            pass
        return "color: #8b949e"

    styled = df.style.apply(highlight_rows, axis=1)
    styled = styled.map(color_diff, subset=["Diff"])
    if "Montée %" in df.columns:
        styled = styled.map(color_montee, subset=["Montée %"])
        styled = styled.map(color_descente, subset=["Desc. %"])

    # Afficher avec HTML pour les badges de forme
    if "Forme" in df.columns:
        st.markdown(
            df.to_html(escape=False, index=False, classes="dataframe"),
            unsafe_allow_html=True,
        )
    else:
        st.dataframe(styled, use_container_width=True, hide_index=True)

    # Légende
    st.markdown("""
    <div style="font-size: 0.8rem; color: #8b949e; margin-top: 0.5rem;">
        <span style="border-left: 3px solid #198754; padding-left: 6px;">Zone de montée</span>
        &nbsp;&nbsp;
        <span style="border-left: 3px solid #dc3545; padding-left: 6px;">Zone de descente</span>
        &nbsp;&nbsp;
        <span class="form-badge form-V">V</span> Victoire
        <span class="form-badge form-N">N</span> Nul
        <span class="form-badge form-D">D</span> Défaite
    </div>
    """, unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════
# ONGLET : FORME
# ═══════════════════════════════════════════════════════════════
with tab_forme:
    st.subheader("📈 Forme des équipes")

    if not team_stats:
        st.warning("Les statistiques détaillées ne sont pas disponibles.")
    else:
        forme_rows = []
        for team in teams:
            ts = team_stats.get(team.name)
            if not ts:
                continue

            form_html = ""
            for r in ts.recent_results[-5:]:
                form_html += f'<span class="form-badge form-{r}">{r}</span>'

            forme_rows.append({
                "#": team.rank,
                "Équipe": team.name,
                "Forme": form_html,
                "Score": f"{ts.form_score:.2f}",
                "Dom (V-N-D)": f"{ts.home_wins}-{ts.home_draws}-{ts.home_losses}",
                "Ext (V-N-D)": f"{ts.away_wins}-{ts.away_draws}-{ts.away_losses}",
                "PPM Dom": f"{ts.home_ppg:.2f}",
                "PPM Ext": f"{ts.away_ppg:.2f}",
            })

        if forme_rows:
            df_forme = pd.DataFrame(forme_rows)
            st.markdown(
                df_forme.to_html(escape=False, index=False, classes="dataframe"),
                unsafe_allow_html=True,
            )

            st.caption(
                "**Score de forme** : pondéré de 0 (mauvais) à 3 (excellent). "
                "**PPM** = Points par match."
            )


# ═══════════════════════════════════════════════════════════════
# ONGLET : CALENDRIER
# ═══════════════════════════════════════════════════════════════
with tab_calendrier:
    st.subheader("📅 Calendrier complet")

    if not calendar_fixtures:
        st.warning("Le calendrier n'est pas disponible.")
    else:
        calendar_summary = get_calendar_summary(calendar_fixtures)
        c1, c2, c3 = st.columns(3)
        c1.metric("Journée actuelle", f"{calendar_summary['current_matchday']}/{calendar_summary['total_matchdays']}")
        c2.metric("Matchs joués", calendar_summary["played"])
        c3.metric("Matchs restants", calendar_summary["remaining"])

        # Grouper par journée
        fixtures_sorted = sorted(calendar_fixtures, key=lambda f: (f.matchday, f.date))
        current_md = 0

        for fixture in fixtures_sorted:
            if fixture.matchday != current_md:
                current_md = fixture.matchday
                st.markdown(f"**Journée {current_md}**")

            if fixture.played and fixture.home_goals is not None and fixture.away_goals is not None:
                score = f"**{fixture.home_goals} - {fixture.away_goals}**"
                style = "opacity: 0.6;"
            elif fixture.played:
                score = "Terminé"
                style = "opacity: 0.6;"
            elif fixture.date:
                score = f"*{fixture.date}*"
                style = ""
            else:
                score = "vs"
                style = ""

            st.markdown(
                f'<div style="display: flex; justify-content: space-between; '
                f'padding: 4px 8px; border-bottom: 1px solid #21262d; {style}">'
                f'<span style="flex: 1; text-align: right;">{fixture.home_team}</span>'
                f'<span style="flex: 0 0 120px; text-align: center;">{score}</span>'
                f'<span style="flex: 1;">{fixture.away_team}</span>'
                f'</div>',
                unsafe_allow_html=True,
            )
