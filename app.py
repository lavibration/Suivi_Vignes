"""
Application Web Streamlit - Système de Prévision Mildiou & Oïdium
Page d'accueil : Vue d'ensemble + Gestion stades phénologiques
"""

import streamlit as st
from datetime import datetime
import sys
import os
import json
from storage import DataManager

# Ajouter le répertoire parent au path pour importer mildiou_prevention
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from mildiou_prevention import SystemeDecision

# Configuration de la page
st.set_page_config(
    page_title="Synthèse Exploitation",
    page_icon="🍇",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Style CSS personnalisé
st.markdown("""
<style>
    .main-header {
        font-size: 3rem;
        font-weight: bold;
        text-align: center;
        color: #2E7D32;
        margin-bottom: 1rem;
    }
    .alert-high {
        background-color: rgba(198, 40, 40, 0.15);
        border-left: 4px solid #c62828;
        padding: 0.75rem;
        border-radius: 0.5rem;
        margin: 0.5rem 0;
    }
    .alert-medium {
        background-color: rgba(239, 108, 0, 0.15);
        border-left: 4px solid #ef6c00;
        padding: 0.75rem;
        border-radius: 0.5rem;
        margin: 0.5rem 0;
    }
    .alert-low {
        background-color: rgba(46, 125, 50, 0.15);
        border-left: 4px solid #2e7d32;
        padding: 0.75rem;
        border-radius: 0.5rem;
        margin: 0.5rem 0;
    }
    /* Style pour le bandeau de décision unifié */
    .unified-decision ul {
        margin-bottom: 0;
        padding-left: 20px;
    }
    .unified-decision li {
        margin-bottom: 0.25rem;
    }
</style>
""", unsafe_allow_html=True)

# Initialisation du système (avec cache pour performance)
@st.cache_resource
def init_systeme_v2():
    return SystemeDecision()

# Fonction pour sauvegarder le stade d'une parcelle
def sauvegarder_stade(parcelle_nom, nouveau_stade, date_debourrement=None):
    """Sauvegarde le nouveau stade via DataManager"""
    storage = DataManager()
    try:
        config = storage.load_data('config_vignoble')

        for parcelle in config['parcelles']:
            if parcelle['nom'] == parcelle_nom:
                parcelle['stade_actuel'] = nouveau_stade
                if nouveau_stade == 'debourrement' and date_debourrement:
                    parcelle['date_debourrement'] = date_debourrement
                elif nouveau_stade == 'repos':
                    parcelle['date_debourrement'] = None
                break

        storage.save_data('config_vignoble', config)
        return True
    except Exception as e:
        st.error(f"Erreur lors de la sauvegarde : {e}")
        return False

# Fonction pour obtenir la couleur selon l'urgence
def get_urgence_color(urgence):
    colors = {
        'haute': '🔴',
        'moyenne': '🟠',
        'faible': '🟢'
    }
    return colors.get(urgence, '⚪')

# Fonction pour obtenir la classe CSS selon l'urgence
def get_alert_class(urgence):
    classes = {
        'haute': 'alert-high',
        'moyenne': 'alert-medium',
        'faible': 'alert-low'
    }
    return classes.get(urgence, 'alert-low')

# Header
st.markdown('<p class="main-header">🍇 Outil d\'Aide à la Décision Vigne</p>', unsafe_allow_html=True)

# Sidebar
with st.sidebar:
    st.title("⚙️ Navigation")
    st.markdown("---")

    try:
        systeme = init_systeme_v2()
        systeme.config.load_config()
        st.success(f"✅ {len(systeme.config.parcelles)} parcelles configurées")
        st.success(f"✅ {systeme.config.surface_totale:.1f} ha total")
    except Exception as e:
        st.error(f"❌ Erreur de chargement : {e}")
        st.stop()

    st.markdown("---")
    st.subheader("🎨 Affichage")
    afficher_ipi = st.checkbox("Afficher IPI", value=True)
    afficher_meteo = st.checkbox("Afficher météo", value=True)

    st.markdown("---")
    if st.button("🔄 Forcer Rechargement GSheets", use_container_width=True):
        st.cache_data.clear()
        st.cache_resource.clear()
        st.rerun()

# Main content
try:
    systeme = init_systeme_v2()

    col_date, col_refresh = st.columns([3, 1])
    with col_date:
        st.caption(f"📅 Dernière mise à jour : {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    with col_refresh:
        if st.button("🔄 Actualiser"):
            st.cache_resource.clear()
            st.rerun()

    st.markdown("---")

    # --- SECTION GESTION STADES (MODIFIÉE AVEC GDD ET BIOFIX) ---
    with st.expander("🌱 Gestion des Stades Phénologiques", expanded=False):
        st.subheader("Mise à jour manuelle et suivi GDD (DJC)")

        stades_disponibles = list(systeme.config.COEF_STADES.keys())
        descriptions_stades = {
            'repos': '🛌 Repos hivernal', 'debourrement': '🌱 Débourrement',
            'pousse_10cm': '📏 Pousse active (>10cm)', 'pre_floraison': '🌸 Pré-floraison',
            'floraison': '💐 Floraison', 'nouaison': '🫐 Nouaison',
            'fermeture_grappe': '🍇 Fermeture de la grappe', 'veraison': '🎨 Véraison',
            'maturation': '🍷 Maturation'
        }

        # Analyser toutes les parcelles une seule fois pour obtenir les GDD
        analyses_parcelles = {}
        with st.spinner("Calcul des Risques et GDD (DJC)..."):
            for parcelle in systeme.config.parcelles:
                # On lance l'analyse complète (nécessaire pour les alertes)
                analyses_parcelles[parcelle['nom']] = systeme.analyser_parcelle(parcelle['nom'], utiliser_ipi=afficher_ipi, debug=False)

        cols_stades = st.columns(len(systeme.config.parcelles))

        for idx, parcelle in enumerate(systeme.config.parcelles):
            with cols_stades[idx]:
                st.markdown(f"**{parcelle['nom']}**")

                analyse_parcelle = analyses_parcelles.get(parcelle['nom'], {})
                gdd_info = analyse_parcelle.get('gdd', {})
                stade_estime = gdd_info.get('stade_estime', 'N/A')
                cumul_gdd = gdd_info.get('cumul', 0)
                mode_calcul_gdd = gdd_info.get('mode_calcul', '')

                stade_actuel = parcelle['stade_actuel']
                st.caption(f"Stade actuel (Manuel) : {descriptions_stades.get(stade_actuel, stade_actuel)}")

                if stade_actuel != 'repos':
                    st.caption(f"Stade estimé (GDD) : {stade_estime} ({cumul_gdd} GDD)")
                    st.caption(f"Base calcul : {mode_calcul_gdd}")
                    if gdd_info.get('alerte_stade') and "dans" in gdd_info.get('alerte_stade'):
                        st.info(f"{gdd_info.get('alerte_stade')}")
                else:
                    st.caption(f"Calcul GDD inactif (stade 'repos')")

                index_actuel = stades_disponibles.index(stade_actuel) if stade_actuel in stades_disponibles else 0

                nouveau_stade = st.selectbox(
                    "Nouveau stade manuel",
                    stades_disponibles,
                    index=index_actuel,
                    format_func=lambda x: descriptions_stades.get(x, x),
                    key=f"stade_{parcelle['nom']}"
                )

                date_debourrement = None
                if nouveau_stade == 'debourrement' and parcelle['stade_actuel'] != 'debourrement':
                    date_debourrement = st.date_input(
                        "🗓️ Date du débourrement (Biofix)",
                        value=datetime.now(),
                        key=f"date_biofix_{parcelle['nom']}"
                    )
                    date_debourrement = date_debourrement.strftime('%Y-%m-%d')

                if st.button(f"💾 Sauvegarder Stade", key=f"save_{parcelle['nom']}", type="primary"):
                    if sauvegarder_stade(parcelle['nom'], nouveau_stade, date_debourrement):
                        st.success(f"✅ Stade mis à jour !")
                        st.cache_resource.clear()
                        st.rerun()

    st.markdown("---")

    # ==============================================================================
    # --- SECTION ALERTES URGENTES (MODIFIÉE AVEC BILAN HYDRIQUE) ---
    # ==============================================================================
    st.subheader("🚨 Alertes et Recommandations")

    toutes_alertes = []

    for parcelle in systeme.config.parcelles:
        analyse = analyses_parcelles.get(parcelle['nom'])

        if not analyse or 'erreur' in analyse:
            continue

        decision = analyse['decision']
        risque_o = analyse['risque_oidium']
        bilan_h = analyse['bilan_hydrique'] # <-- NOUVEAU

        # Alerte Mildiou
        if decision['urgence'] in ['haute', 'moyenne']:
            toutes_alertes.append({
                'parcelle': parcelle['nom'],
                'urgence': decision['urgence'],
                'message': f"🦠 {decision['action']}",
                'details': decision.get('alerte_preventive', '')
            })

        # Alerte Oïdium
        if risque_o['niveau'] in ['FORT', 'MOYEN']:
            urgence_oidium = 'haute' if risque_o['niveau'] == 'FORT' else 'moyenne'
            toutes_alertes.append({
                'parcelle': parcelle['nom'],
                'urgence': urgence_oidium,
                'message': f"🍄 RISQUE OÏDIUM {risque_o['niveau']}",
                'details': f"Score : {risque_o['score']}/10. Vérifier la protection."
            })

        # --- NOUVELLE ALERTE HYDRIQUE ---
        if "STRESS FORT" in bilan_h.get('niveau', ''):
            toutes_alertes.append({
                'parcelle': parcelle['nom'],
                'urgence': 'haute', # Stress hydrique fort est une alerte haute
                'message': f"💧 STRESS HYDRIQUE FORT",
                'details': f"Réserve utile (RFU) estimée à {bilan_h['rfu_pct']}%."
            })
        elif "SURVEILLANCE" in bilan_h.get('niveau', ''):
             toutes_alertes.append({
                'parcelle': parcelle['nom'],
                'urgence': 'moyenne',
                'message': f"💧 STRESS HYDRIQUE EN COURS",
                'details': f"Réserve utile (RFU) estimée à {bilan_h['rfu_pct']}%."
            })

    if toutes_alertes:
        toutes_alertes.sort(key=lambda x: (x['urgence'] != 'haute', x['urgence'] != 'moyenne'))

        for alerte in toutes_alertes:
            alert_class = get_alert_class(alerte['urgence'])
            urgence_icon = get_urgence_color(alerte['urgence'])

            st.markdown(f"""
            <div class="{alert_class}">
                <strong>{urgence_icon} {alerte['parcelle']}</strong><br>
                ➜ {alerte['message']}<br>
                {alerte['details'] if alerte['details'] else ''}
            </div>
            """, unsafe_allow_html=True)
    else:
        st.markdown("""
        <div class="alert-low">
            <strong>🟢 Aucune alerte</strong><br>
            Toutes vos parcelles sont sous contrôle.
        </div>
        """, unsafe_allow_html=True)

    st.markdown("---")

    # ==============================================================================
    # --- SECTION VUE D'ENSEMBLE (MODIFIÉE AVEC BILAN HYDRIQUE) ---
    # ==============================================================================
    st.subheader("📊 Vue d'Ensemble des Parcelles")

    nb_parcelles = len(systeme.config.parcelles)
    cols = st.columns(min(nb_parcelles, 3))

    for idx, parcelle in enumerate(systeme.config.parcelles):
        col = cols[idx % min(nb_parcelles, 3)]

        with col:
            analyse = analyses_parcelles.get(parcelle['nom'])
            if not analyse or 'erreur' in analyse:
                st.error(f"Erreur analyse {parcelle['nom']}")
                continue

            with st.container(border=True):
                st.markdown(f"### 🍇 {parcelle['nom']}")

                # Infos parcelles (INCHANGÉ)
                col_info1, col_info2 = st.columns(2)
                with col_info1:
                    st.caption(f"🌱 {', '.join(parcelle['cepages'][:2])}")
                    if len(parcelle['cepages']) > 2: st.caption(f"   +{len(parcelle['cepages'])-2} autres")
                with col_info2:
                    st.caption(f"📏 {parcelle.get('surface_ha', 'N/A')} ha")
                    st.caption(f"🌿 {parcelle['stade_actuel']}")

                st.markdown("---")

                # Métriques principales
                risque_m = analyse['risque_infection']
                risque_o = analyse['risque_oidium']
                protection = analyse['protection_actuelle']
                decision = analyse['decision']
                bilan_h = analyse['bilan_hydrique'] # <-- NOUVEAU

                col_m1, col_m2 = st.columns(2)

                # --- BLOC 1: RISQUES ---
                with col_m1:
                    st.metric(
                        "🦠 Risque Mildiou",
                        f"{risque_m['score']}/10",
                        delta=risque_m['niveau'],
                    )
                    st.metric(
                        "🍄 Risque Oïdium",
                        f"{risque_o['score']}/10",
                        delta=risque_o['niveau']
                    )

                # --- BLOC 2: PROTECTION & ETAT ---
                with col_m2:
                    st.metric(
                        "🛡️ Protection",
                        f"{protection['score']}/10",
                        delta=f"Limité par: {protection.get('facteur_limitant', 'N/A')}",
                        delta_color="off"
                    )

                    # --- NOUVELLE MÉTRIQUE BILAN HYDRIQUE ---
                    rfu_color = "🔴" if "STRESS FORT" in bilan_h['niveau'] else ("🟠" if "SURVEILLANCE" in bilan_h['niveau'] else "🟢")
                    st.metric(
                        f"{rfu_color} Bilan Hydrique (RFU)",
                        f"{bilan_h['rfu_pct']}%",
                        delta=bilan_h['niveau'],
                        delta_color="off"
                    )

                    st.metric(
                        "📉 Indice Stress (Ks)",
                        f"{bilan_h.get('ks_actuel', 1.0):.2f}",
                        help="1.0 = pas de stress, < 1.0 = régulation stomatique"
                    )

                # IPI (Si activé, sous les blocs)
                if afficher_ipi and risque_m['ipi'] is not None:
                    st.metric(
                        "📊 IPI (Mildiou)",
                        f"{risque_m['ipi']}/100",
                        delta=risque_m.get('ipi_niveau', 'N/A'),
                    )

                # ==========================================================
                # --- BANDEAU DE DÉCISION UNIFIÉ (MIS À JOUR) ---
                # ==========================================================

                urgence_mildiou = decision['urgence']
                urgence_oidium = 'faible'
                if "FORT" in decision['alerte_oidium']: urgence_oidium = 'haute'
                elif "MOYEN" in decision['alerte_oidium']: urgence_oidium = 'moyenne'

                urgence_hydrique = 'faible'
                if "STRESS FORT" in bilan_h['niveau']: urgence_hydrique = 'haute'
                elif "SURVEILLANCE" in bilan_h['niveau']: urgence_hydrique = 'moyenne'

                urgences_map = {'haute': 3, 'moyenne': 2, 'faible': 1}
                urgence_globale_str = 'faible'

                # Choisir l'urgence la plus élevée
                if urgences_map[urgence_mildiou] > urgences_map[urgence_globale_str]:
                    urgence_globale_str = urgence_mildiou
                if urgences_map[urgence_oidium] > urgences_map[urgence_globale_str]:
                    urgence_globale_str = urgence_oidium
                if urgences_map[urgence_hydrique] > urgences_map[urgence_globale_str]:
                    urgence_globale_str = urgence_hydrique

                message_mildiou = decision['action']
                message_oidium = decision['alerte_oidium'] if decision['alerte_oidium'] else "Risque faible"
                ks_val = bilan_h.get('ks_actuel', 1.0)
                ks_msg = f" (Ks: {ks_val:.2f})" if ks_val < 1.0 else ""
                message_hydrique = f"RFU à {bilan_h['rfu_pct']}% ({bilan_h['niveau']}){ks_msg}"

                alert_class = get_alert_class(urgence_globale_str)
                urgence_icon = get_urgence_color(urgence_globale_str)

                st.markdown(f"""
                <div class="{alert_class} unified-decision" style="margin-top: 10px; margin-bottom: 10px;">
                    <strong>{urgence_icon} Decision Unifiée</strong>
                    <ul>
                        <li><strong>Mildiou :</strong> {message_mildiou}</li>
                        <li><strong>Oïdium :</strong> {message_oidium}</li>
                        <li><strong>Hydrique :</strong> {message_hydrique}</li>
                    </ul>
                </div>
                """, unsafe_allow_html=True)

                # Bouton détails
                if st.button(f"🔍 Voir Détails", key=f"details_{parcelle['nom']}", use_container_width=True):
                    st.switch_page("pages/1_Analyse_Detaillee.py")

    st.markdown("---")

    # Section Météo (si activée)
    if afficher_meteo:
        st.subheader("🌤️ Conditions Météorologiques")
        meteo_data = systeme.meteo.get_meteo_data(days_past=1, days_future=3) # Appel API court ici
        if meteo_data:
            date_actuelle = datetime.now().strftime('%Y-%m-%d')
            meteo_actuelle = meteo_data.get(date_actuelle, {})
            col_m1, col_m2, col_m3, col_m4 = st.columns(4)
            with col_m1:
                st.metric(
                    "🌡️ Température",
                    f"{meteo_actuelle.get('temp_moy', 0):.1f}°C",
                    delta=f"{meteo_actuelle.get('temp_max', 0) - meteo_actuelle.get('temp_min', 0):.1f}°C écart"
                )
            with col_m2:
                st.metric(
                    "💧 Précipitations",
                    f"{meteo_actuelle.get('precipitation', 0):.1f} mm",
                )
            with col_m3:
                st.metric(
                    "💨 Humidité",
                    f"{meteo_actuelle.get('humidite', 0):.0f}%",
                )
            with col_m4:
                dates_futures = sorted([d for d in meteo_data.keys() if d > date_actuelle])[:3]
                pluie_prevue = sum(meteo_data.get(d, {}).get('precipitation', 0) for d in dates_futures)
                st.metric(
                    "🌧️ Pluie prévue 3j",
                    f"{pluie_prevue:.1f} mm",
                )
        else:
            st.warning("⚠️ Impossible de récupérer les données météo")

    st.markdown("---")

    # Section Statistiques Globales
    st.subheader("📈 Statistiques Globales")
    col_s1, col_s2, col_s3, col_s4 = st.columns(4)
    nb_alertes_haute = len([a for a in toutes_alertes if a['urgence'] == 'haute'])
    nb_alertes_moyenne = len([a for a in toutes_alertes if a['urgence'] == 'moyenne'])
    date_debut_mois = datetime.now().replace(day=1).strftime('%Y-%m-%d')
    date_fin = datetime.now().strftime('%Y-%m-%d')
    traitements_mois = [
        t for t in systeme.traitements.historique.get('traitements', [])
        if date_debut_mois <= t['date'] <= date_fin
    ]
    with col_s1:
        st.metric("🚨 Alertes Urgentes", nb_alertes_haute)
    with col_s2:
        st.metric("⚠️ Alertes Moyennes", nb_alertes_moyenne)
    with col_s3:
        st.metric("💊 Traitements ce mois", len(traitements_mois))
    with col_s4:
        annee = datetime.now().year
        ift = systeme.traitements.calculer_ift_periode(
            f"{annee}-01-01",
            date_fin,
            systeme.config.surface_totale
        )
        st.metric("🧾 IFT Année", f"{ift['ift_total']:.1f}")

    st.markdown("---")

    # Footer
    st.caption("🍇 Système Mildiou, Oïdium & Hydrique v1.3")

except Exception as e:
    st.error(f"""
    ❌ **Erreur lors du chargement**

    {str(e)}

    Vérifiez que :
    - Le fichier `config_vignoble.json` existe et est correct
    - Le fichier `mildiou_prevention.py` est présent
    - Vous avez une connexion internet pour la météo
    """)
    st.exception(e)
    st.stop()
