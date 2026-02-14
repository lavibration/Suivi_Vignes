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

    tab1, tab2 = st.tabs(["➕ Nouvel Apport", "📊 Historique et Suivi"])

    # ==============================================================================
    # TAB 1 : NOUVEL APPORT
    # ==============================================================================
    with tab1:
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
                        st.success(f"✅ Apport enregistré : {apport['u_n']} unités N, {apport['u_p']} unités P, {apport['u_k']} unités K.")
                        st.cache_resource.clear()
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
    with tab2:
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

except Exception as e:
    st.error(f"❌ Erreur : {str(e)}")
    import traceback
    st.code(traceback.format_exc())
