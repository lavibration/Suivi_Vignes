"""
Page Analyse Détaillée d'une Parcelle
Avec mode debug et détails complets
Fichier : pages/1_Analyse_Detaillee.py
"""

import streamlit as st
import sys
import os
from datetime import datetime
import io
from contextlib import redirect_stdout
import pandas as pd

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mildiou_prevention import SystemeDecision

st.set_page_config(page_title="Analyse Détaillée", page_icon="🔍", layout="wide")

# Style
st.markdown("""
<style>
    .metric-card {
        background-color: #f0f2f6;
        padding: 1.5rem;
        border-radius: 0.5rem;
        margin: 0.5rem 0;
    }
    .debug-box {
        background-color: #263238;
        color: #aed581;
        padding: 1rem;
        border-radius: 0.5rem;
        font-family: monospace;
        font-size: 0.9rem;
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
    .unified-decision ul {
        margin-bottom: 0;
        padding-left: 20px;
    }
    .unified-decision li {
        margin-bottom: 0.25rem;
    }
</style>
""", unsafe_allow_html=True)

# --- Fonctions helper copiées depuis app.py ---
def get_urgence_color(urgence):
    colors = {'haute': '🔴', 'moyenne': '🟠', 'faible': '🟢'}
    return colors.get(urgence, '⚪')

def get_alert_class(urgence):
    classes = {'haute': 'alert-high', 'moyenne': 'alert-medium', 'faible': 'alert-low'}
    return classes.get(urgence, 'alert-low')
# -----------------------------------------------------

# Header
st.title("🔍 Analyse Détaillée d'une Parcelle")

# Initialiser le système
@st.cache_resource
def init_systeme_v2():
    return SystemeDecision()

try:
    systeme = init_systeme_v2()

    # Sidebar
    with st.sidebar:
        st.subheader("📍 Sélection Parcelle")
        parcelle_names = [p['nom'] for p in systeme.config.parcelles]
        parcelle_selectionnee = st.selectbox(
            "Choisir une parcelle",
            parcelle_names,
            key="parcelle_select"
        )
        st.markdown("---")
        st.subheader("⚙️ Options d'Analyse")
        utiliser_ipi = st.checkbox("Activer modèle IPI", value=True)
        mode_debug = st.checkbox("Mode Debug", value=False,
                                help="Affiche les calculs détaillés")
        st.markdown("---")
        if st.button("🔄 Actualiser l'analyse", type="primary"):
            st.cache_resource.clear()
            st.rerun()

    # Analyse
    if parcelle_selectionnee:
        # Onglets principaux
        tab1, tab2, tab3 = st.tabs(["📊 Synthèse", "🔬 Détails Techniques", "📅 Historique"])

        # Récupérer l'analyse (en capturant le debug si besoin)
        debug_output = ""
        if mode_debug:
            with st.spinner("Recalcul avec traces debug..."):
                f = io.StringIO()
                with redirect_stdout(f):
                    # On ne sauvegarde pas l'historique lors d'une vue détaillée
                    # pour économiser les quotas GSheets
                    analyse = systeme.analyser_parcelle(
                        parcelle_selectionnee,
                        utiliser_ipi=utiliser_ipi,
                        debug=True,
                        sauvegarder_historique=False
                    )
                debug_output = f.getvalue()
        else:
            analyse = systeme.analyser_parcelle(
                parcelle_selectionnee,
                utiliser_ipi=utiliser_ipi,
                debug=False,
                sauvegarder_historique=False
            )

        if 'erreur' in analyse:
            st.error(f"❌ {analyse['erreur']}")
            st.stop()

        # ==============================================================================
        # --- TAB 1 : Synthèse (MODIFIÉ AVEC OÏDIUM ET GDD) ---
        # ==============================================================================
        with tab1:
            parcelle_obj = next(p for p in systeme.config.parcelles if p['nom'] == parcelle_selectionnee)
            col_info1, col_info2, col_info3 = st.columns(3)
            with col_info1:
                st.markdown("### 📍 Parcelle")
                st.markdown(f"**Nom :** {parcelle_obj['nom']}")
                st.markdown(f"**Surface :** {parcelle_obj['surface_ha']} ha")
            with col_info2:
                st.markdown("### 🍇 Cépages")
                for cepage in parcelle_obj['cepages']:
                    st.markdown(f"- {cepage}")
            with col_info3:
                st.markdown("### 🌱 Stade Actuel (Manuel)")
                descriptions_stades = {
                    'repos': '🛌 Repos hivernal',
                    'bourgeon_hiver': '❄️ Bourgeon d\'hiver (A/01)',
                    'bourgeon_coton': '☁️ Bourgeon dans le coton (B/05)',
                    'pointe_verte': '🌱 Pointe verte (C/09)',
                    'sorties_feuilles': '🍃 Sorties des feuilles (D/11)',
                    'feuilles_etalees': '🌿 Feuilles étalées (E/13)',
                    'grappes_visibles': '🍇 Grappes visibles (F/53)',
                    'boutons_agglomeres': '🟢 Boutons agglomérés (G/55)',
                    'boutons_separes': '🟡 Boutons séparés (H/57)',
                    'floraison': '💐 Floraison (I/65)',
                    'nouaison': '🫐 Nouaison (J/71)',
                    'petits_pois': '🟢 Petits pois (K/75)',
                    'fermeture_grappe': '🍇 Fermeture de grappe (L/77)',
                    'veraison': '🎨 Véraison (M/81)',
                    'maturite': '🍷 Maturité (N/89)'
                }
                st.markdown(f"**{descriptions_stades.get(parcelle_obj['stade_actuel'], parcelle_obj['stade_actuel'])}**")
                coef_stade = systeme.config.COEF_STADES.get(parcelle_obj['stade_actuel'], 0)
                coef_pousse = systeme.traitements.COEF_POUSSE.get(parcelle_obj['stade_actuel'], 0)
                st.caption(f"Coef. risque : {coef_stade}")
                st.caption(f"Coef. pousse : {coef_pousse}")
                if parcelle_obj.get('date_debourrement'):
                    st.caption(f"Biofix GDD : {parcelle_obj['date_debourrement']}")

            st.markdown("---")

            # --- BLOC GDD ---
            st.subheader("📈 Suivi Phénologique (GDD)")
            gdd_info = analyse.get('gdd', {})

            if gdd_info.get('mode_calcul') == 'En dormance (calcul GDD inactif)':
                st.info("😴 Calcul GDD inactif. Le stade manuel de la parcelle est 'repos'.")
            else:
                col_gdd1, col_gdd2, col_gdd3 = st.columns(3)
                with col_gdd1:
                    st.metric("🌡️ GDD Cumulés (base 10°C)", f"{gdd_info.get('cumul', 0)} GDD",
                              help=f"Calcul basé sur : {gdd_info.get('mode_calcul')}")
                with col_gdd2:
                    stade_estime_key = gdd_info.get('stade_estime', 'N/A')
                    st.metric("🌱 Stade Estimé (GDD)", descriptions_stades.get(stade_estime_key, stade_estime_key))
                with col_gdd3:
                    alerte_stade = gdd_info.get('alerte_stade', '')
                    if "dans" in alerte_stade:
                         st.info(f"**{alerte_stade}**")
                    else:
                        st.caption(alerte_stade)

            st.markdown("---")

            # Métriques principales
            st.subheader("📊 Évaluation Actuelle")
            col_m1, col_m2, col_m3 = st.columns(3)
            risque_m = analyse['risque_infection']
            risque_o = analyse['risque_oidium']
            protection = analyse['protection_actuelle']
            decision = analyse['decision']
            bilan_h = analyse['bilan_hydrique'] # <-- NOUVEAU

            with col_m1:
                risque_m_color = "🔴" if risque_m['score'] >= 7 else ("🟠" if risque_m['score'] >= 4 else "🟢")
                st.metric(
                    f"{risque_m_color} Risque Mildiou",
                    f"{risque_m['score']}/10",
                    delta=risque_m['niveau'],
                    help="Basé sur météo 48h + stade + sensibilité"
                )
                risque_o_color = "🔴" if risque_o['score'] >= 7 else ("🟠" if risque_o['score'] >= 4 else "🟢")
                st.metric(
                    f"{risque_o_color} Risque Oïdium",
                    f"{risque_o['score']}/10",
                    delta=risque_o['niveau'],
                    help="Basé sur météo 7j (T° optimales, T° létales, humidité)"
                )

            with col_m2:
                prot_color = "🟢" if protection['score'] >= 7 else ("🟠" if protection['score'] >= 4 else "🔴")
                st.metric(
                    f"{prot_color} Protection Résiduelle",
                    f"{protection['score']}/10",
                    delta=f"Limité par : {protection.get('facteur_limitant', 'N/A')}",
                    delta_color="off"
                )

                # --- NOUVEAU BILAN HYDRIQUE ---
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
                # ------------------------------

            with col_m3:
                dec_color = "🔴" if decision['urgence'] == 'haute' else ("🟠" if decision['urgence'] == 'moyenne' else "🟢")
                st.metric(
                    f"{dec_color} Score Décision (Mildiou)",
                    f"{decision['score']}/10",
                    delta=decision['urgence'].upper(),
                    help="Risque Mildiou - Protection"
                )
                if utiliser_ipi and risque_m['ipi'] is not None:
                    st.metric(
                        "IPI (Mildiou)",
                        f"{risque_m['ipi']}/100",
                        delta=risque_m.get('ipi_niveau', 'N/A'),
                        help="Évalue la sévérité si infection Mildiou"
                    )

            # --- MODIFIÉ : Bandeau de Décision Unifié ---
            st.markdown("---")
            st.subheader("➜ Recommandation")

            urgence_mildiou = decision['urgence']
            urgence_oidium = 'faible'
            if "FORT" in decision['alerte_oidium']: urgence_oidium = 'haute'
            elif "MOYEN" in decision['alerte_oidium']: urgence_oidium = 'moyenne'

            urgence_hydrique = 'faible'
            if "STRESS FORT" in bilan_h['niveau']: urgence_hydrique = 'haute'
            elif "SURVEILLANCE" in bilan_h['niveau']: urgence_hydrique = 'moyenne'

            urgences_map = {'haute': 3, 'moyenne': 2, 'faible': 1}
            urgence_globale_str = 'faible'

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
            <div class="{alert_class} unified-decision">
                <strong>{urgence_icon} Decision Unifiée</strong>
                <ul>
                    <li><strong>Mildiou :</strong> {message_mildiou}</li>
                    <li><strong>Oïdium :</strong> {message_oidium}</li>
                    <li><strong>Hydrique :</strong> {message_hydrique}</li>
                </ul>
            </div>
            """, unsafe_allow_html=True)

            # --- NOUVEAU BLOC : GRAPHIQUE BILAN HYDRIQUE ---
            st.markdown("---")
            st.subheader("💧 Évolution du Bilan Hydrique (RFU)")

            if bilan_h.get('historique_pct'):
                df_rfu = pd.DataFrame.from_dict(bilan_h['historique_pct'], orient='index', columns=['RFU (%)'])
                df_rfu.index = pd.to_datetime(df_rfu.index)

                # Ajouter les seuils pour le contexte
                df_rfu['Seuil Stress (30%)'] = 30.0
                df_rfu['Seuil Surveillance (60%)'] = 60.0

                st.line_chart(df_rfu, color=['#0068C9', '#FF4B4B', '#FFA500']) # Bleu, Rouge, Orange
            else:
                st.info("Historique du bilan hydrique non disponible.")
            # ---------------------------------------------

            # Météo actuelle
            st.markdown("---")
            st.subheader("🌤️ Conditions Météorologiques")
            meteo = analyse['meteo_actuelle']
            col_w1, col_w2, col_w3, col_w4 = st.columns(4) # Ajout ETP
            with col_w1:
                st.metric("Température",
                         f"{meteo.get('temp_moy', 0):.1f}°C",
                         delta=f"Min: {meteo.get('temp_min', 0):.1f}°C | Max: {meteo.get('temp_max', 0):.1f}°C")
            with col_w2:
                st.metric("Précipitations", f"{meteo.get('precipitation', 0):.1f} mm")
            with col_w3:
                st.metric("Humidité", f"{meteo.get('humidite', 0):.0f}%")
            with col_w4:
                st.metric("ETP (Évaporation)", f"{meteo.get('etp', 0):.1f} mm")

            # Prévisions
            if analyse['previsions_3j']:
                st.markdown("---")
                st.subheader("📅 Prévisions 3 Jours")
                prev = analyse['previsions_3j']
                st.info(f"💧 Pluie prévue : **{prev['pluie_totale']} mm**")
                if prev['details']:
                    cols_prev = st.columns(len(prev['details']))
                    for idx, (date, meteo_prev) in enumerate(prev['details'].items()):
                        with cols_prev[idx]:
                            st.caption(f"**{date}**")
                            st.caption(f"🌡️ {meteo_prev.get('temp_moy', 'N/A'):.1f}°C")
                            st.caption(f"💧 {meteo_prev.get('precipitation', 'N/A'):.1f}mm")
                            etp = meteo_prev.get('etp')
                            if not isinstance(etp, (int, float)):
                                # fallback FAO très simplifié
                                tmax = meteo_prev.get('temp_max')
                                tmin = meteo_prev.get('temp_min')
                                if isinstance(tmax, (int, float)) and isinstance(tmin, (int, float)):
                                    etp = max(0.1, (tmax - tmin) * 0.12)  # approximation acceptable
                                else:
                                    etp = None

                            etp_fmt = f"{etp:.1f} mm" if isinstance(etp, (int, float)) else "N/A"
                            st.caption(f"☀️ ETP: {etp_fmt}")

        # ==============================================================================
        # --- TAB 2 : Détails Techniques (MODIFIÉ POUR ALIGNEMENT) ---
        # ==============================================================================
        with tab2:
            st.subheader("🔬 Détails des Calculs")

            col_tech1, col_tech2 = st.columns(2)

            with col_tech1:
                st.markdown("### 🦠 Modèle Mildiou (Simple)")
                st.markdown(f"""
                **Score calculé :** {risque_m['score']}/10
                **Facteurs pris en compte :**
                - Pluie 48h
                - Température (optimum 20-25°C)
                - Humidité relative
                - Coefficient stade : {coef_stade}
                - Sensibilité cépages
                **Résultat :** {risque_m['niveau']}
                """)

                st.markdown("---")

                st.markdown("### 🍄 Modèle Oïdium")
                st.markdown(f"""
                **Score calculé :** {risque_o['score']}/10
                **Facteurs pris en compte (7 jours) :**
                - T° optimales (20-28°C) avec Humidité > 60%
                - T° favorables (15-30°C) avec Humidité > 50%
                - T° létales (> 33°C) (score négatif)
                - Pluie > 5mm (effet lessivant, score négatif)
                **Résultat :** {risque_o['niveau']}
                """)

            with col_tech2:
                st.markdown("### 📊 Modèle Mildiou (IPI)")
                if utiliser_ipi and risque_m['ipi'] is not None:
                    st.markdown(f"""
                    **IPI calculé :** {risque_m['ipi']}/100
                    **Méthode :**
                    - Interpolation bilinéaire
                    - Température vs Durée humectation
                    - Table Lalancette et al.
                    **Niveau :** {risque_m.get('ipi_niveau', 'N/A')}

                    💡 *L'IPI évalue la sévérité potentielle si infection.*
                    """)
                elif utiliser_ipi:
                    st.info("IPI non calculé (voir conditions Mildiou Simple).")
                else:
                    st.info("Le modèle IPI n'est pas activé (voir options dans la barre latérale).")

                st.markdown("---")

                # --- NOUVEAU BLOC BILAN HYDRIQUE ---
                st.markdown("### 💧 Modèle Bilan Hydrique")
                st.markdown(f"""
                **RFU Max (Réglage) :** {bilan_h['rfu_max_mm']} mm
                **Calcul Agronomique (FAO-56) :**
                - `Kc` dynamique indexé sur les GDD (vigueur foliaire).
                - `Ks` (Stress) : régulation si RFU < 50%.
                - `ETc = ET0 x Kc x Ks`
                - Plafonnée entre 0 et {bilan_h['rfu_max_mm']} mm.
                - **ETP :** *et0_fao_evapotranspiration* (Penman-Monteith)
                **Résultat :** {bilan_h['rfu_pct']}% ({bilan_h['niveau']})
                **Indice de stress actuel (Ks) :** {bilan_h.get('ks_actuel', 1.0):.2f}
                """)
                # ------------------------------------

            st.markdown("---")

            # Protection détaillée
            st.markdown("### 🛡️ Analyse de la Protection")
            if protection['dernier_traitement']:
                dt = protection['dernier_traitement']
                carac = dt['caracteristiques']
                col_prot1, col_prot2 = st.columns(2)
                with col_prot1:
                    st.markdown(f"""
                    **Traitement actif :**
                    - Date : {dt['date']}
                    - Produit : {carac.get('nom', 'N/A')}
                    - Type : {carac.get('type', 'N/A')}
                    """)
                with col_prot2:
                    st.markdown(f"""
                    **Caractéristiques :**
                    - Persistance : {carac.get('persistance_jours', 0)} jours
                    - Seuil lessivage : {carac.get('lessivage_seuil_mm', 0)} mm
                    - Dose appliquée : {dt.get('dose_kg_ha', 'N/A')} kg/ha
                    """)

                facteur = protection.get('facteur_limitant', 'Inconnu')
                if 'Pousse' in facteur:
                    st.warning(f"⚠️ **Facteur limitant : {facteur}**\n\nLa croissance végétale dilue la protection.")
                elif 'Lessivage' in facteur:
                    st.error(f"🌧️ **Facteur limitant : {facteur}**\n\nProtection lessivée. Traitement nécessaire.")
                else:
                    st.info(f"ℹ️ **Facteur limitant : {facteur}**")

            # Mode debug
            if mode_debug:
                st.markdown("---")
                st.subheader("🐛 Mode Debug")
                st.markdown("Affichage des calculs internes (GDD, Mildiou, Oïdium) :")
                st.markdown('<div class="debug-box">', unsafe_allow_html=True)
                st.code(debug_output, language="text")
                st.markdown('</div>', unsafe_allow_html=True)

        # ==============================================================================
        # --- TAB 3 : Historique (INCHANGÉ) ---
        # ==============================================================================
        with tab3:
            st.subheader("📅 Historique des Traitements")

            traitements_parcelle = [
                t for t in systeme.traitements.historique.get('traitements', [])
                if t['parcelle'] == parcelle_selectionnee
            ]

            if traitements_parcelle:
                traitements_parcelle.sort(key=lambda x: x['date'], reverse=True)

                df_data = []
                for t in traitements_parcelle:
                    df_data.append({
                        'Date': t['date'],
                        'Produit': t['caracteristiques'].get('nom', t['produit']),
                        'Type': t['caracteristiques'].get('type', 'N/A'),
                        'Dose (kg/ha)': t.get('dose_kg_ha', 'N/A'),
                        'Persistance (j)': t['caracteristiques'].get('persistance_jours', 0)
                    })
                df = pd.DataFrame(df_data)
                st.dataframe(df, use_container_width=True, hide_index=True)

                st.markdown("---")
                col_stat1, col_stat2, col_stat3 = st.columns(3)
                with col_stat1:
                    st.metric("Total traitements", len(traitements_parcelle))
                with col_stat2:
                    dernier = traitements_parcelle[0]
                    jours_depuis = (datetime.now() - datetime.strptime(dernier['date'], '%Y-%m-%d')).days
                    st.metric("Dernier traitement", f"Il y a {jours_depuis}j")
                with col_stat3:
                    produits = [t['caracteristiques'].get('nom', 'N/A') for t in traitements_parcelle]
                    if produits:
                        produit_freq = max(set(produits), key=produits.count)
                        st.metric("Produit principal", produit_freq)
                    else:
                        st.metric("Produit principal", "N/A")
            else:
                st.info("📝 Aucun traitement enregistré pour cette parcelle")
                st.markdown("Utilisez la page **Gestion Traitements** pour ajouter un traitement.")

except Exception as e:
    st.error(f"❌ Erreur : {str(e)}")
    import traceback
    with st.expander("Détails de l'erreur"):
        st.code(traceback.format_exc())
