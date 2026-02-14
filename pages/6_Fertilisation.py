"""
Page Fertilisation et Amendement
Enregistrement des apports et suivi N-P-K
Fichier : pages/6_Fertilisation.py
"""

import streamlit as st
import sys
import os
import pandas as pd
from datetime import datetime, date
import plotly.graph_objects as go
import plotly.express as px

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mildiou_prevention import SystemeDecision, GestionFertilisation
from storage import DataManager

st.set_page_config(page_title="Fertilisation", page_icon="🌱", layout="wide")

st.title("🌱 Fertilisation et Amendements")

# Initialiser les composants
@st.cache_resource
def init_systeme_v2():
    return SystemeDecision()

try:
    systeme = init_systeme_v2()
    # On utilise directement GestionFertilisation
    gestion_fert = GestionFertilisation()

    # Gérer la navigation par onglets via session_state
    tab_titles = ["➕ Nouvel Apport", "📊 Historique et Suivi", "🎯 Pilotage & Objectifs"]
    if "active_tab_fert" not in st.session_state:
        st.session_state.active_tab_fert = tab_titles[0]

    selected_tab = st.radio("Navigation", tab_titles, index=tab_titles.index(st.session_state.active_tab_fert), horizontal=True, label_visibility="collapsed")
    st.session_state.active_tab_fert = selected_tab

    st.markdown("---")

    # ==============================================================================
    # TAB 1 : NOUVEL APPORT
    # ==============================================================================
    if selected_tab == tab_titles[0]:
        st.subheader("📝 Enregistrer un apport (Sol ou Foliaire)")

        col_form, col_info = st.columns([2, 1])

        with col_form:
            with st.form("form_apport", clear_on_submit=True):
                # Parcelle
                parcelle_names = [p['nom'] for p in systeme.config.parcelles]
                parcelle = st.selectbox("📍 Parcelle *", parcelle_names)

                col1, col2 = st.columns(2)
                apport_date = col1.date_input("📅 Date *", value=date.today())

                # Produits - filtrer pour engrais/amendements
                produits_dict = systeme.traitements.charger_produits()
                engrais_ids = [k for k, v in produits_dict.items() if v.get('type') in ["engrais solide", "engrais foliaire", "amendement"]]

                if not engrais_ids:
                    st.warning("⚠️ Aucun engrais ou amendement trouvé dans la bibliothèque de produits. Allez dans 'Paramètres' pour en ajouter.")
                    produit_selectionne = None
                else:
                    engrais_noms = [produits_dict[k]['nom'] for k in engrais_ids]
                    nom_selectionne = col2.selectbox("🧪 Produit *", engrais_noms)
                    produit_id = engrais_ids[engrais_noms.index(nom_selectionne)]
                    produit_info = produits_dict[produit_id]

                    qty = st.number_input("⚖️ Quantité par hectare (kg/ha ou L/ha) *", min_value=0.0, value=float(produit_info.get('dose_reference_kg_ha', 0.0)), step=1.0)

                    st.info(f"**Composition :** N:{produit_info.get('n', 0)}% - P:{produit_info.get('p', 0)}% - K:{produit_info.get('k', 0)}% | **Application :** {produit_info.get('type_application', 'Sol')}")

                submit_apport = st.form_submit_button("✅ Enregistrer l'Apport", type="primary", use_container_width=True)

                if submit_apport and nom_selectionne is not None:
                    if qty > 0:
                        apport = gestion_fert.ajouter_apport(
                            parcelle=parcelle,
                            date_apport=apport_date.strftime('%Y-%m-%d'),
                            produit_id=produit_id,
                            produit_info=produit_info,
                            quantite_ha=qty
                        )
                        st.cache_resource.clear()
                        st.cache_data.clear()
                        st.success(f"✅ Apport enregistré : {apport['u_n']} unités N, {apport['u_p']} unités P, {apport['u_k']} unités K.")
                        st.session_state.active_tab_fert = tab_titles[1] # Aller à l'historique
                        st.rerun()
                    else:
                        st.error("⚠️ La quantité doit être supérieure à 0.")

        with col_info:
            st.info("""
            **Calcul des Unités Fertilisantes**

            Les unités sont calculées automatiquement :
            `Unités = Quantité (kg/ha) * Teneur (%) / 100`

            Exemple : 300 kg/ha d'un engrais 8-4-12 apporte :
            - 24 unités d'Azote (N)
            - 12 unités de Phosphore (P)
            - 36 unités de Potasse (K)
            """)

    # ==============================================================================
    # TAB 2 : HISTORIQUE ET SUIVI
    # ==============================================================================
    elif selected_tab == tab_titles[1]:
        st.subheader("📊 Récapitulatif Annuel par Parcelle")

        annee_sel = st.selectbox("Année", sorted(list(set([datetime.strptime(a['date'], '%Y-%m-%d').year for a in gestion_fert.donnees['apports']] + [datetime.now().year])), reverse=True))

        bilan = gestion_fert.get_bilan_annuel(annee_sel)

        if not bilan:
            st.info(f"Aucun apport enregistré pour l'année {annee_sel}.")
        else:
            # Préparer données pour tableau et graphique
            data_bilan = []
            for p_nom, stats in bilan.items():
                # Vérifier si fertilisée l'année précédente
                has_prev = False
                for a in gestion_fert.donnees['apports']:
                    d = datetime.strptime(a['date'], '%Y-%m-%d')
                    if d.year == annee_sel - 1 and a['parcelle'] == p_nom:
                        has_prev = True
                        break

                data_bilan.append({
                    'Parcelle': p_nom,
                    'N (Azote)': stats['n'],
                    'P (Phosphore)': stats['p'],
                    'K (Potasse)': stats['k'],
                    'Passages': stats['nb_passages'],
                    'Fertilisée {annee_sel-1}'.format(annee_sel=annee_sel): "✅" if has_prev else "❌"
                })

            df_bilan = pd.DataFrame(data_bilan)
            st.dataframe(df_bilan, use_container_width=True, hide_index=True)

            st.markdown("---")
            st.subheader("📈 Comparatif N-P-K (Unités / Ha)")

            fig = go.Figure()
            fig.add_trace(go.Bar(x=df_bilan['Parcelle'], y=df_bilan['N (Azote)'], name='N (Azote)', marker_color='#2ca02c'))
            fig.add_trace(go.Bar(x=df_bilan['Parcelle'], y=df_bilan['P (Phosphore)'], name='P (Phosphore)', marker_color='#ff7f0e'))
            fig.add_trace(go.Bar(x=df_bilan['Parcelle'], y=df_bilan['K (Potasse)'], name='K (Potasse)', marker_color='#1f77b4'))

            fig.update_layout(barmode='group', template="plotly_dark", height=400)
            st.plotly_chart(fig, use_container_width=True)

        st.markdown("---")
        st.subheader("📜 Historique détaillé")
        if gestion_fert.donnees['apports']:
            df_hist = pd.DataFrame(gestion_fert.donnees['apports'])
            df_hist = df_hist.sort_values('date', ascending=False)

            # Formater les colonnes
            cols_show = {
                'date': 'Date',
                'parcelle': 'Parcelle',
                'produit_nom': 'Produit',
                'quantite_ha': 'Qté/ha',
                'u_n': 'U. N',
                'u_p': 'U. P',
                'u_k': 'U. K',
                'type_application': 'Type',
                'bio': 'Bio'
            }
            st.dataframe(df_hist[list(cols_show.keys())].rename(columns=cols_show), use_container_width=True, hide_index=True)

            if st.button("🗑️ Vider l'historique de fertilisation"):
                if st.checkbox("Confirmer la suppression totale"):
                    gestion_fert.donnees['apports'] = []
                    gestion_fert.sauvegarder()
                    st.success("Historique vidé.")
                    st.rerun()
        else:
            st.info("Aucun historique disponible.")

    # ==============================================================================
    # TAB 3 : PILOTAGE & OBJECTIFS
    # ==============================================================================
    elif selected_tab == tab_titles[2]:
        st.subheader("🎯 Pilotage des Besoins Nutritionnels")

        # Sélection parcelle
        parcelle_pilot = st.selectbox("📍 Sélectionner une parcelle pour le pilotage", [p['nom'] for p in systeme.config.parcelles], key="sel_pilot")
        annee_pilot = st.selectbox("Année", sorted(list(set([datetime.strptime(a['date'], '%Y-%m-%d').year for a in gestion_fert.donnees['apports']] + [datetime.now().year])), reverse=True), key="annee_pilot")

        # Calcul du bilan
        bilan_pilot = gestion_fert.calculer_bilan_pilotage(parcelle_pilot, annee_pilot, systeme.config)

        if not bilan_pilot:
            st.warning("⚠️ Impossible de calculer le bilan de pilotage.")
        else:
            obj = bilan_pilot['objectif_hl_ha']
            besoins = bilan_pilot['besoins']
            apports = bilan_pilot['apports']
            soldes = bilan_pilot['soldes']
            couv = bilan_pilot['couverture_pct']

            st.markdown(f"**Objectif de Production :** {obj} hl/ha")

            # --- GAUGES ---
            col_g1, col_g2, col_g3 = st.columns(3)

            def create_gauge(val, name, color):
                fig = go.Figure(go.Indicator(
                    mode = "gauge+number",
                    value = val,
                    title = {'text': f"Couverture {name} (%)"},
                    domain = {'x': [0, 1], 'y': [0, 1]},
                    gauge = {
                        'axis': {'range': [0, 150]},
                        'bar': {'color': color},
                        'steps': [
                            {'range': [0, 80], 'color': "rgba(255, 0, 0, 0.1)"},
                            {'range': [80, 120], 'color': "rgba(0, 255, 0, 0.1)"},
                            {'range': [120, 150], 'color': "rgba(255, 165, 0, 0.1)"}
                        ],
                        'threshold': {
                            'line': {'color': "black", 'width': 4},
                            'thickness': 0.75,
                            'value': 100
                        }
                    }
                ))
                fig.update_layout(height=250, margin=dict(l=20, r=20, t=50, b=20), template="plotly_dark")
                return fig

            col_g1.plotly_chart(create_gauge(couv['n'], "N (Azote)", "#2ca02c"), use_container_width=True)
            col_g2.plotly_chart(create_gauge(couv['p'], "P (Phosphore)", "#ff7f0e"), use_container_width=True)
            col_g3.plotly_chart(create_gauge(couv['k'], "K (Potasse)", "#1f77b4"), use_container_width=True)

            # --- DETAILS TABLE ---
            st.markdown("### 📋 Détail du Bilan (Unités / Ha)")
            data_pilot = [
                {'Élément': 'N (Azote)', 'Besoin': besoins['n'], 'Apporté': apports['n'], 'Solde': soldes['n'], 'Couverture': f"{couv['n']}%"},
                {'Élément': 'P (Phosphore)', 'Besoin': besoins['p'], 'Apporté': apports['p'], 'Solde': soldes['p'], 'Couverture': f"{couv['p']}%"},
                {'Élément': 'K (Potasse)', 'Besoin': besoins['k'], 'Apporté': apports['k'], 'Solde': soldes['k'], 'Couverture': f"{couv['k']}%"}
            ]
            st.table(pd.DataFrame(data_pilot))

            # --- ALERTS ---
            st.markdown("### ⚠️ Alertes de Pilotage")

            alerts_found = False

            # Alerte N > 120% (spécial Grenache)
            parcelle_obj = next(p for p in systeme.config.parcelles if p['nom'] == parcelle_pilot)
            if couv['n'] > 120:
                if "Grenache" in parcelle_obj['cepages']:
                    st.error(f"🔴 **ALERTE VIGUEUR EXTRÊME (Grenache) :** Couverture Azote à {couv['n']}%. Risque élevé de coulure et de sensibilité aux maladies.")
                    alerts_found = True
                else:
                    st.warning(f"🟠 **Surplus Azote :** Couverture à {couv['n']}%. Surveillez la vigueur de la végétation.")
                    alerts_found = True

            # Alerte K < 50% pour gros objectifs
            if couv['k'] < 50 and obj >= 60:
                st.error(f"🔴 **ALERTE CARENCE POTASSE :** Couverture K à {couv['k']}% pour un objectif ambitieux de {obj} hl/ha. Risque de blocage de maturité.")
                alerts_found = True
            elif couv['k'] < 50:
                st.warning(f"🟠 **Carence Potasse potentielle :** Couverture K à {couv['k']}%.")
                alerts_found = True

            if not alerts_found:
                st.success("✅ Équilibre nutritionnel satisfaisant.")

except Exception as e:
    st.error(f"❌ Erreur : {str(e)}")
    import traceback
    st.code(traceback.format_exc())
