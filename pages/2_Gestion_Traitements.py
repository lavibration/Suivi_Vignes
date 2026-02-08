"""
Page Gestion des Traitements
Ajout, visualisation et suppression des traitements
Fichier : pages/2_Gestion_Traitements.py
"""

import streamlit as st
import sys
import os
from datetime import datetime, timedelta
import pandas as pd

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mildiou_prevention import SystemeDecision

st.set_page_config(page_title="Gestion Traitements", page_icon="💊", layout="wide")

st.title("💊 Gestion des Traitements")

# Initialiser le système
@st.cache_resource
def init_systeme():
    return SystemeDecision()

try:
    systeme = init_systeme()

    # Onglets
    tab1, tab2, tab3 = st.tabs(["➕ Ajouter un Traitement", "📋 Historique Complet", "📊 Statistiques"])

    # TAB 1 : Ajouter traitement
    with tab1:
        st.subheader("Enregistrer un Nouveau Traitement")

        col_form1, col_form2 = st.columns([2, 1])

        with col_form1:
            # SANS st.form() pour permettre la mise à jour dynamique

            # Sélection parcelle
            parcelle_names = [p['nom'] for p in systeme.config.parcelles]
            parcelle = st.selectbox(
                "📍 Parcelle *",
                parcelle_names,
                help="Sélectionnez la parcelle traitée",
                key="select_parcelle"
            )

            # Date
            date_traitement = st.date_input(
                "📅 Date du traitement *",
                value=datetime.now(),
                max_value=datetime.now(),
                help="Date d'application du traitement",
                key="date_trait"
            )

            # Produit - MISE À JOUR DYNAMIQUE
            produits = list(systeme.traitements.FONGICIDES.keys())
            produits_noms = [systeme.traitements.FONGICIDES[p]['nom'] for p in produits]

            produit_selectionne = st.selectbox(
                "💊 Produit *",
                produits_noms,
                help="Fongicide utilisé",
                key="select_produit"
            )

            # Retrouver la clé du produit
            produit_key = produits[produits_noms.index(produit_selectionne)]
            produit_info = systeme.traitements.FONGICIDES[produit_key]

            # Afficher infos produit - SE MET À JOUR AUTOMATIQUEMENT
            st.info(f"""
            **Type :** {produit_info['type'].capitalize()}  
            **Persistance :** {produit_info['persistance_jours']} jours  
            **Seuil lessivage :** {produit_info['lessivage_seuil_mm']} mm  
            **Dose référence :** {produit_info['dose_reference_kg_ha']} kg/ha
            """)

            # Dose - Valeur par défaut change selon le produit
            dose = st.number_input(
                "⚖️ Dose appliquée (kg/ha)",
                min_value=0.0,
                max_value=10.0,
                value=produit_info['dose_reference_kg_ha'],
                step=0.1,
                help="Dose réelle appliquée",
                key=f"dose_{produit_key}"  # Clé unique par produit
            )

            # Notes optionnelles
            notes = st.text_area(
                "📝 Notes (optionnel)",
                placeholder="Conditions d'application, observations...",
                height=100,
                key="notes_trait"
            )

            # Bouton soumission (hors form)
            if st.button("✅ Enregistrer le Traitement", type="primary", use_container_width=True):
                try:
                    # Ajouter le traitement
                    systeme.traitements.ajouter_traitement(
                        parcelle=parcelle,
                        date=date_traitement.strftime('%Y-%m-%d'),
                        produit=produit_key,
                        dose_kg_ha=dose
                    )

                    st.success(f"""
                    ✅ **Traitement enregistré avec succès !**
                    
                    - Parcelle : {parcelle}
                    - Date : {date_traitement.strftime('%d/%m/%Y')}
                    - Produit : {produit_selectionne}
                    - Dose : {dose} kg/ha
                    """)

                    # Rafraîchir le cache
                    st.cache_resource.clear()

                    # Recharger pour afficher dans l'historique
                    st.rerun()

                except Exception as e:
                    st.error(f"❌ Erreur lors de l'enregistrement : {str(e)}")

        with col_form2:
            st.subheader("💡 Conseils")

            st.info("""
            **Bonnes pratiques :**
            
            1. Enregistrez immédiatement après le traitement
            
            2. Notez la dose exacte appliquée
            
            3. Ajoutez des notes si conditions particulières
            
            4. Vérifiez la parcelle sélectionnée
            """)

            st.success("""
            **Impact :**
            
            ✅ Protection recalculée automatiquement
            
            ✅ Pris en compte pour l'IFT
            
            ✅ Visible dans les graphiques
            """)

    # TAB 2 : Historique complet
    with tab2:
        st.subheader("📋 Historique de Tous les Traitements")

        traitements = systeme.traitements.historique.get('traitements', [])

        if traitements:
            # Filtres
            col_filter1, col_filter2, col_filter3 = st.columns(3)

            with col_filter1:
                # Filtre parcelle
                parcelles_filtre = ["Toutes"] + [p['nom'] for p in systeme.config.parcelles]
                parcelle_filtre = st.selectbox("Filtrer par parcelle", parcelles_filtre)

            with col_filter2:
                # Filtre date
                date_debut = st.date_input(
                    "Date début",
                    value=datetime.now() - timedelta(days=90),
                    max_value=datetime.now()
                )

            with col_filter3:
                date_fin = st.date_input(
                    "Date fin",
                    value=datetime.now(),
                    max_value=datetime.now()
                )

            # Appliquer filtres
            traitements_filtres = traitements.copy()

            if parcelle_filtre != "Toutes":
                traitements_filtres = [t for t in traitements_filtres if t['parcelle'] == parcelle_filtre]

            traitements_filtres = [
                t for t in traitements_filtres
                if date_debut.strftime('%Y-%m-%d') <= t['date'] <= date_fin.strftime('%Y-%m-%d')
            ]

            # Tri
            traitements_filtres.sort(key=lambda x: x['date'], reverse=True)

            if traitements_filtres:
                # Créer DataFrame
                df_data = []
                for t in traitements_filtres:
                    df_data.append({
                        'Date': t['date'],
                        'Parcelle': t['parcelle'],
                        'Produit': t['caracteristiques'].get('nom', t['produit']),
                        'Type': t['caracteristiques'].get('type', 'N/A'),
                        'Dose (kg/ha)': f"{t.get('dose_kg_ha', 0):.2f}",
                        'Persistance': f"{t['caracteristiques'].get('persistance_jours', 0)}j"
                    })

                df = pd.DataFrame(df_data)

                # Affichage
                st.dataframe(
                    df,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "Date": st.column_config.DateColumn("Date", format="DD/MM/YYYY"),
                        "Parcelle": st.column_config.TextColumn("Parcelle", width="medium"),
                        "Produit": st.column_config.TextColumn("Produit", width="large"),
                    }
                )

                st.caption(f"**{len(traitements_filtres)}** traitements affichés")

                # Export CSV
                st.markdown("---")
                csv = df.to_csv(index=False).encode('utf-8')
                st.download_button(
                    label="📥 Télécharger en CSV",
                    data=csv,
                    file_name=f"traitements_{datetime.now().strftime('%Y%m%d')}.csv",
                    mime="text/csv"
                )

            else:
                st.info("Aucun traitement ne correspond aux filtres sélectionnés")

        else:
            st.info("📝 Aucun traitement enregistré pour le moment")
            st.markdown("Utilisez l'onglet **Ajouter un Traitement** pour commencer.")

    # TAB 3 : Statistiques
    with tab3:
        st.subheader("📊 Statistiques des Traitements")

        traitements = systeme.traitements.historique.get('traitements', [])

        if traitements:
            # Période d'analyse
            col_period1, col_period2 = st.columns(2)

            with col_period1:
                annee = st.selectbox(
                    "Année",
                    list(range(datetime.now().year, datetime.now().year - 5, -1)),
                    index=0
                )

            with col_period2:
                periode = st.selectbox(
                    "Période",
                    ["Année complète", "1er semestre", "2ème semestre", "Personnalisée"]
                )

            # Définir dates selon période
            if periode == "Année complète":
                date_debut = f"{annee}-01-01"
                date_fin = f"{annee}-12-31"
            elif periode == "1er semestre":
                date_debut = f"{annee}-01-01"
                date_fin = f"{annee}-06-30"
            elif periode == "2ème semestre":
                date_debut = f"{annee}-07-01"
                date_fin = f"{annee}-12-31"
            else:
                col_custom1, col_custom2 = st.columns(2)
                with col_custom1:
                    date_debut = st.date_input("Date début", value=datetime(annee, 1, 1)).strftime('%Y-%m-%d')
                with col_custom2:
                    date_fin = st.date_input("Date fin", value=datetime.now()).strftime('%Y-%m-%d')

            # Filtrer traitements
            traitements_periode = [
                t for t in traitements
                if date_debut <= t['date'] <= date_fin
            ]

            if traitements_periode:
                # Métriques principales
                st.markdown("---")
                col_stat1, col_stat2, col_stat3, col_stat4 = st.columns(4)

                with col_stat1:
                    st.metric("Total Traitements", len(traitements_periode))

                with col_stat2:
                    # IFT
                    ift = systeme.traitements.calculer_ift_periode(
                        date_debut, date_fin, systeme.config.surface_totale
                    )
                    st.metric("IFT Total", f"{ift['ift_total']:.2f}")

                with col_stat3:
                    # IFT par hectare
                    ift_ha = ift['ift_total'] / systeme.config.surface_totale
                    st.metric("IFT / ha", f"{ift_ha:.2f}")

                with col_stat4:
                    # Coût estimé (si on avait les prix)
                    st.metric("Parcelles traitées",
                             len(set(t['parcelle'] for t in traitements_periode)))

                st.markdown("---")

                # Graphiques
                col_graph1, col_graph2 = st.columns(2)

                with col_graph1:
                    st.subheader("Répartition par Parcelle")

                    # Compter traitements par parcelle
                    parcelles_count = {}
                    for t in traitements_periode:
                        parcelles_count[t['parcelle']] = parcelles_count.get(t['parcelle'], 0) + 1

                    df_parcelles = pd.DataFrame(list(parcelles_count.items()),
                                               columns=['Parcelle', 'Traitements'])
                    st.bar_chart(df_parcelles.set_index('Parcelle'))

                with col_graph2:
                    st.subheader("Répartition par Produit")

                    # Compter par produit
                    produits_count = {}
                    for t in traitements_periode:
                        prod = t['caracteristiques'].get('nom', t['produit'])
                        produits_count[prod] = produits_count.get(prod, 0) + 1

                    df_produits = pd.DataFrame(list(produits_count.items()),
                                              columns=['Produit', 'Utilisations'])
                    st.bar_chart(df_produits.set_index('Produit'))

                # Timeline
                st.markdown("---")
                st.subheader("📅 Timeline des Traitements")

                # Créer un graphique timeline
                df_timeline = pd.DataFrame([{
                    'Date': datetime.strptime(t['date'], '%Y-%m-%d'),
                    'Parcelle': t['parcelle'],
                    'Produit': t['caracteristiques'].get('nom', t['produit'])[:20]
                } for t in traitements_periode])

                if not df_timeline.empty:
                    df_timeline['Mois'] = df_timeline['Date'].dt.strftime('%Y-%m')
                    timeline_count = df_timeline.groupby('Mois').size()

                    st.line_chart(timeline_count)
                    st.caption("Nombre de traitements par mois")

                # Tableau récapitulatif IFT
                st.markdown("---")
                st.subheader("🧾 Détail IFT par Traitement")

                df_ift = pd.DataFrame(ift['details'])
                st.dataframe(df_ift, use_container_width=True, hide_index=True)

            else:
                st.info(f"Aucun traitement enregistré pour la période {date_debut} à {date_fin}")

        else:
            st.info("📝 Aucune donnée statistique disponible")

except Exception as e:
    st.error(f"❌ Erreur : {str(e)}")
    import traceback
    with st.expander("Détails de l'erreur"):
        st.code(traceback.format_exc())