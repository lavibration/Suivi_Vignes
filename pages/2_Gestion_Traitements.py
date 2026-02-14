"""
Page Gestion des Traitements
Ajout, visualisation et suppression des traitements
Adapté aux exigences légales du Registre Phytosanitaire
Fichier : pages/2_Gestion_Traitements.py
"""

import streamlit as st
import sys
import os
from datetime import datetime, timedelta
import pandas as pd
import io

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mildiou_prevention import SystemeDecision

st.set_page_config(page_title="Gestion Traitements", page_icon="💊", layout="wide")

st.title("💊 Gestion des Traitements & Registre")

# Initialiser le système
@st.cache_resource
def init_systeme_v2():
    return SystemeDecision()

def get_parcel_surface(systeme, parcel_name):
    for p in systeme.config.parcelles:
        if p['nom'] == parcel_name:
            return p.get('surface_ha', 0.0)
    return 0.0

try:
    systeme = init_systeme_v2()
    # Forcer le rafraîchissement des produits
    if hasattr(systeme.traitements, 'charger_produits'):
        systeme.traitements.FONGICIDES = systeme.traitements.charger_produits()

    # Gérer la navigation par onglets via session_state pour éviter les resets
    tab_titles = ["➕ Ajouter un Traitement", "📋 Registre & Historique", "📊 Statistiques"]
    if "active_tab_traitements" not in st.session_state:
        st.session_state.active_tab_traitements = tab_titles[0]

    selected_tab = st.radio("Navigation", tab_titles, index=tab_titles.index(st.session_state.active_tab_traitements), horizontal=True, label_visibility="collapsed")
    st.session_state.active_tab_traitements = selected_tab

    st.markdown("---")

    # TAB 1 : Ajouter traitement
    if selected_tab == tab_titles[0]:
        st.subheader("Enregistrer un Nouveau Traitement (Données Légales)")

        col_form1, col_form2 = st.columns([2, 1])

        with col_form1:
            # Sélection parcelle
            parcelle_names = [p['nom'] for p in systeme.config.parcelles]
            parcelle = st.selectbox(
                "📍 Parcelle *",
                parcelle_names,
                help="Sélectionnez la parcelle traitée",
                key="select_parcelle"
            )

            p_surface = get_parcel_surface(systeme, parcelle)

            col1, col2 = st.columns(2)
            with col1:
                date_traitement = st.date_input(
                    "📅 Date du traitement *",
                    value=datetime.now(),
                    max_value=datetime.now(),
                    key="date_trait"
                )
            with col2:
                heure_traitement = st.time_input(
                    "🕒 Heure du traitement *",
                    value=datetime.now().time(),
                    key="heure_trait"
                )

            # Produit
            produits_dict = systeme.traitements.FONGICIDES
            # Filtrer pour n'afficher que les produits phytosanitaires
            phyto_ids = [k for k, v in produits_dict.items() if v.get('type') in ["contact", "penetrant", "systemique", "autre"]]

            if not phyto_ids:
                st.warning("⚠️ Aucun produit phytosanitaire trouvé. Allez dans 'Paramètres' pour en ajouter.")
                produits_noms = []
            else:
                produits_noms = [produits_dict[p]['nom'] for p in phyto_ids]

            produit_selectionne = st.selectbox(
                "💊 Produit *",
                produits_noms,
                key="select_produit"
            )

            produit_key = phyto_ids[produits_noms.index(produit_selectionne)] if phyto_ids else None
            produit_info = produits_dict[produit_key] if produit_key else {}

            st.info(f"**N° AMM :** {produit_info.get('n_amm', 'N/A')} | **Type :** {produit_info.get('type', 'N/A')} | **Dose réf :** {produit_info.get('dose_reference_kg_ha', 0)} kg/ha")

            col3, col4 = st.columns(2)
            with col3:
                # Utiliser la dose de référence par défaut
                dose = st.number_input(
                    "⚖️ Quantité / ha (kg ou L) *",
                    min_value=0.0,
                    value=float(produit_info.get('dose_reference_kg_ha', 1.0)),
                    step=0.1,
                    key=f"dose_{produit_key}"
                )
                surface_t = st.number_input(
                    "📏 Surface traitée (ha) *",
                    min_value=0.0,
                    value=p_surface,
                    step=0.01,
                    key="surf_trait"
                )
            with col4:
                mouillage = st.number_input(
                    "💧 Mouillage (% de PPP) *",
                    min_value=0.0,
                    max_value=100.0,
                    value=100.0,
                    help="Hurricane dose standard 0.1%",
                    key="mouillage"
                )
                type_u = st.selectbox(
                    "🚜 Type d'utilisation *",
                    ["Pulvérisation", "Aérien", "Localisé"],
                    key="type_u"
                )

            with st.expander("Informations Complémentaires (Optionnel)"):
                col5, col6 = st.columns(2)
                with col5:
                    cible = st.text_input("🎯 Cible (Bioagresseur)", value="Mildiou / Oïdium")
                    applicateur = st.text_input("👤 Nom de l'applicateur", value="")
                    culture = st.text_input("🌿 Culture", value="Vigne")
                with col6:
                    sys_culture = st.selectbox("🏗️ Système de culture", ["PC (Plein Champ)", "SA (Sous Abris)", "HS (Hors Sol)"], index=0)
                    meteo_cond = st.text_area("☁️ Conditions climatiques", placeholder="Ex: 18°C, Vent faible < 10km/h, Humidité 60%", height=68)

            # Bouton soumission
            if st.button("✅ Enregistrer au Registre", type="primary", use_container_width=True):
                try:
                    systeme.traitements.ajouter_traitement(
                        parcelle=parcelle,
                        date=date_traitement.strftime('%Y-%m-%d'),
                        produit=produit_key,
                        dose_kg_ha=dose,
                        heure=heure_traitement.strftime('%H:%M'),
                        mouillage_pct=mouillage,
                        surface_traitee=surface_t,
                        type_utilisation=type_u,
                        cible=cible,
                        conditions_meteo=meteo_cond,
                        applicateur=applicateur,
                        systeme_culture=sys_culture.split(' ')[0],
                        culture=culture
                    )

                    st.success(f"✅ Traitement enregistré pour {parcelle}")
                    st.cache_resource.clear()
                    st.rerun()

                except Exception as e:
                    st.error(f"❌ Erreur : {str(e)}")

        with col_form2:
            st.subheader("📋 Rappel Légal")
            st.warning("""
            Le **Registre Phytosanitaire** est obligatoire.
            Toutes les colonnes marquées d'un * doivent être renseignées.
            """)
            st.info("""
            **Données conservées :**
            - Nom de parcelle & Culture
            - Produit & N° AMM
            - Date & Heure
            - Dose & Surface
            - Conditions & Applicateur
            """)

    # TAB 2 : Registre & Historique
    elif selected_tab == tab_titles[1]:
        st.subheader("📋 Registre Phytosanitaire Officiel")

        traitements = systeme.traitements.historique.get('traitements', [])

        if traitements:
            df_full = pd.DataFrame(traitements)

            # Formater pour affichage
            df_display = []
            for t in traitements:
                carac = t.get('caracteristiques', {})
                df_display.append({
                    'Parcelle': t['parcelle'],
                    'Culture': t.get('culture', 'Vigne'),
                    'Système': t.get('systeme_culture', 'PC'),
                    'Produit': carac.get('nom', t['produit']),
                    'N° AMM': carac.get('n_amm', 'N/A'),
                    'Date': t['date'],
                    'Heure': t.get('heure', '10:00'),
                    'Quantité/ha': t.get('dose_kg_ha', 0),
                    'Mouillage %': t.get('mouillage_pct', 100),
                    'Surface (ha)': t.get('surface_traitee', 0),
                    'Type': t.get('type_utilisation', 'Plein champ'),
                    'Cible': t.get('cible', 'Mildiou'),
                    'Météo': t.get('conditions_meteo', ''),
                    'Applicateur': t.get('applicateur', '')
                })

            df_final = pd.DataFrame(df_display)
            df_final = df_final.sort_values(by='Date', ascending=False)

            st.dataframe(df_final, use_container_width=True, hide_index=True)

            # Export EXCEL (Format Officiel)
            st.markdown("---")

            col_ex1, col_ex2 = st.columns([1, 1])
            with col_ex1:
                # Bouton pour générer l'Excel
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                    df_final.to_excel(writer, index=False, sheet_name='Registre_Phyto')
                    # On pourrait ajouter du style ici avec openpyxl si besoin

                st.download_button(
                    label="📂 Télécharger Registre Phytosanitaire (Excel)",
                    data=output.getvalue(),
                    file_name=f"Registre_Phytosanitaire_{datetime.now().year}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )

            with col_ex2:
                 csv = df_final.to_csv(index=False).encode('utf-8')
                 st.download_button(
                    label="📥 Télécharger en CSV",
                    data=csv,
                    file_name=f"traitements_{datetime.now().strftime('%Y%m%d')}.csv",
                    mime="text/csv"
                )

        else:
            st.info("📝 Aucun traitement enregistré")

    # TAB 3 : Statistiques
    elif selected_tab == tab_titles[2]:
        st.subheader("📊 Statistiques & IFT")
        # Garder la logique de stats existante (simplifiée ici pour la démo)
        traitements = systeme.traitements.historique.get('traitements', [])
        if traitements:
            annee = st.selectbox("Année de référence", list(range(datetime.now().year, 2020, -1)))
            date_debut = f"{annee}-01-01"
            date_fin = f"{annee}-12-31"

            traitements_annee = [t for t in traitements if date_debut <= t['date'] <= date_fin]

            if traitements_annee:
                ift = systeme.traitements.calculer_ift_periode(date_debut, date_fin, systeme.config.surface_totale)

                col_s1, col_s2, col_s3 = st.columns(3)
                col_s1.metric("Traitements", len(traitements_annee))
                col_s2.metric("IFT Annuel Total", f"{ift['ift_total']:.2f}")
                col_s3.metric("IFT moyen / ha", f"{ift['ift_total']/systeme.config.surface_totale:.2f}")

                st.markdown("---")
                st.subheader("Détail des calculs IFT")
                st.dataframe(pd.DataFrame(ift['details']), use_container_width=True, hide_index=True)
            else:
                st.info(f"Aucune donnée pour l'année {annee}")

except Exception as e:
    st.error(f"❌ Erreur : {str(e)}")
    import traceback
    st.code(traceback.format_exc())
