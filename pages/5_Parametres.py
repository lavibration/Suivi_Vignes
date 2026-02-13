"""
Page Paramètres
Configuration du vignoble et gestion de la liste des produits
Fichier : pages/5_Parametres.py
"""

import streamlit as st
import sys
import os
import pandas as pd
import json
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mildiou_prevention import ConfigVignoble, GestionTraitements
from storage import DataManager

st.set_page_config(page_title="Paramètres", page_icon="⚙️", layout="wide")

st.title("⚙️ Paramètres de l'Exploitation")

# Initialiser les composants
storage = DataManager()
config_vignoble = ConfigVignoble()
gestion_traitements = GestionTraitements()

tab1, tab2 = st.tabs(["🍇 Configuration Vignoble", "💊 Liste Produits"])

# ==============================================================================
# TAB 1 : CONFIGURATION VIGNOBLE
# ==============================================================================
with tab1:
    st.subheader("📍 Gestion des Parcelles")

    parcelles = config_vignoble.parcelles

    # Affichage de la liste actuelle
    if parcelles:
        df_parcelles = pd.DataFrame(parcelles)
        st.dataframe(df_parcelles, use_container_width=True, hide_index=True)

    st.markdown("---")

    col_add, col_edit = st.columns(2)

    with col_add:
        st.markdown("### ➕ Ajouter une Parcelle")
        with st.form("form_add_parcelle", clear_on_submit=True):
            new_nom = st.text_input("Nom de la parcelle *")
            new_surface = st.number_input("Surface (ha) *", min_value=0.0, step=0.01)
            new_cepages = st.text_input("Cépages (séparés par des virgules) *", placeholder="Ex: Grenache, Syrah")
            new_rfu_max = st.number_input("RFU Max (mm)", min_value=10.0, value=100.0, step=1.0)

            submit_add = st.form_submit_button("Ajouter la Parcelle", type="primary")

            if submit_add:
                if new_nom and new_surface > 0 and new_cepages:
                    cepages_list = [c.strip() for c in new_cepages.split(',')]
                    new_parcelle = {
                        "nom": new_nom,
                        "surface_ha": new_surface,
                        "cepages": cepages_list,
                        "stade_actuel": "repos",
                        "date_debourrement": None,
                        "rfu_max_mm": new_rfu_max
                    }
                    config_vignoble.parcelles.append(new_parcelle)
                    config_vignoble.sauvegarder_config()
                    st.cache_resource.clear()
                    st.success(f"✅ Parcelle '{new_nom}' ajoutée.")
                    st.rerun()
                else:
                    st.error("⚠️ Veuillez remplir tous les champs obligatoires.")

    with col_edit:
        st.markdown("### 📝 Modifier / Supprimer")
        if parcelles:
            nom_edit = st.selectbox("Sélectionner une parcelle", [p['nom'] for p in parcelles])
            parcelle_to_edit = next(p for p in parcelles if p['nom'] == nom_edit)

            with st.form("form_edit_parcelle"):
                edit_nom = st.text_input("Nom", value=parcelle_to_edit['nom'])
                edit_surface = st.number_input("Surface (ha)", min_value=0.0, value=float(parcelle_to_edit['surface_ha']), step=0.01)
                edit_cepages = st.text_input("Cépages", value=", ".join(parcelle_to_edit['cepages']))
                edit_rfu_max = st.number_input("RFU Max (mm)", min_value=10.0, value=float(parcelle_to_edit.get('rfu_max_mm', 100.0)), step=1.0)

                col_btn1, col_btn2 = st.columns(2)
                submit_edit = col_btn1.form_submit_button("Sauvegarder", use_container_width=True)
                submit_del = col_btn2.form_submit_button("🗑️ Supprimer", use_container_width=True)

                if submit_edit:
                    parcelle_to_edit['nom'] = edit_nom
                    parcelle_to_edit['surface_ha'] = edit_surface
                    parcelle_to_edit['cepages'] = [c.strip() for c in edit_cepages.split(',')]
                    parcelle_to_edit['rfu_max_mm'] = edit_rfu_max
                    config_vignoble.sauvegarder_config()
                    st.cache_resource.clear()
                    st.success("✅ Modifications enregistrées.")
                    st.rerun()

                if submit_del:
                    config_vignoble.parcelles = [p for p in config_vignoble.parcelles if p['nom'] != nom_edit]
                    config_vignoble.sauvegarder_config()
                    st.cache_resource.clear()
                    st.warning(f"🗑️ Parcelle '{nom_edit}' supprimée.")
                    st.rerun()
        else:
            st.info("Aucune parcelle à modifier.")

    st.markdown("---")
    st.subheader("⚙️ Paramètres Généraux")
    col_p1, col_p2 = st.columns(2)
    with col_p1:
        lat = st.number_input("Latitude", value=float(config_vignoble.latitude), format="%.6f")
        lon = st.number_input("Longitude", value=float(config_vignoble.longitude), format="%.6f")
    with col_p2:
        t_base = st.number_input("Température de base GDD", value=float(config_vignoble.parametres.get('t_base_gdd', 10.0)))
        rfu_def = st.number_input("RFU Max par défaut", value=float(config_vignoble.parametres.get('rfu_max_mm_default', 100.0)))

    if st.button("Sauvegarder Paramètres Généraux"):
        config_vignoble.latitude = lat
        config_vignoble.longitude = lon
        config_vignoble.parametres['t_base_gdd'] = t_base
        config_vignoble.parametres['rfu_max_mm_default'] = rfu_def
        config_vignoble.sauvegarder_config()
        st.cache_resource.clear()
        st.success("✅ Paramètres généraux sauvegardés.")

# ==============================================================================
# TAB 2 : LISTE PRODUITS
# ==============================================================================
with tab2:
    st.subheader("🧪 Gestion des Produits (Phyto, Engrais, etc.)")

    # Charger les produits
    produits_dict = gestion_traitements.FONGICIDES
    produits_list = list(produits_dict.values())

    if produits_list:
        df_produits = pd.DataFrame(produits_list)
        # Réorganiser colonnes pour lisibilité
        cols = ['nom', 'n_amm', 'type', 'persistance_jours', 'lessivage_seuil_mm', 'dose_reference_kg_ha']
        st.dataframe(df_produits[[c for c in cols if c in df_produits.columns]], use_container_width=True, hide_index=True)

    st.markdown("---")

    col_p_add, col_p_edit = st.columns(2)

    with col_p_add:
        st.markdown("### ➕ Ajouter un Produit")
        with st.form("form_add_produit", clear_on_submit=True):
            p_nom = st.text_input("Nom commercial *")
            p_amm = st.text_input("N° AMM")
            p_type = st.selectbox("Type *", ["contact", "penetrant", "systemique", "engrais solide", "engrais foliaire", "autre"])

            p_pers = st.number_input("Persistance (jours) *", min_value=0, value=7)
            p_less = st.number_input("Seuil lessivage (mm) *", min_value=0, value=25)
            p_dose = st.number_input("Dose référence (Kg/Ha ou L/Ha) *", min_value=0.0, value=1.0, step=0.1, format="%.2f")

            submit_p_add = st.form_submit_button("Ajouter le Produit", type="primary")

            if submit_p_add:
                if p_nom:
                    p_id = p_nom.lower().replace(' ', '_')
                    new_produit = {
                        "id": p_id,
                        "nom": p_nom,
                        "n_amm": p_amm,
                        "type": p_type,
                        "persistance_jours": p_pers,
                        "lessivage_seuil_mm": p_less,
                        "dose_reference_kg_ha": p_dose
                    }

                    # Charger, ajouter et sauvegarder
                    data = storage.load_data('produits', default_factory=lambda: {'produits': []})
                    data['produits'].append(new_produit)
                    storage.save_data('produits', data)
                    st.cache_resource.clear()
                    st.success(f"✅ Produit '{p_nom}' ajouté.")
                    st.rerun()
                else:
                    st.error("⚠️ Le nom commercial est obligatoire.")

    with col_p_edit:
        st.markdown("### 📝 Modifier / Supprimer")
        if produits_list:
            p_select_nom = st.selectbox("Sélectionner un produit", [p['nom'] for p in produits_list])
            p_to_edit = next(p for p in produits_list if p['nom'] == p_select_nom)

            with st.form("form_edit_produit"):
                pe_nom = st.text_input("Nom commercial", value=p_to_edit['nom'])
                pe_amm = st.text_input("N° AMM", value=p_to_edit.get('n_amm', ''))
                pe_type = st.selectbox("Type", ["contact", "penetrant", "systemique", "engrais solide", "engrais foliaire", "autre"],
                                       index=["contact", "penetrant", "systemique", "engrais solide", "engrais foliaire", "autre"].index(p_to_edit.get('type', 'contact')) if p_to_edit.get('type') in ["contact", "penetrant", "systemique", "engrais solide", "engrais foliaire", "autre"] else 0)

                pe_pers = st.number_input("Persistance (jours)", min_value=0, value=int(p_to_edit.get('persistance_jours', 7)))
                pe_less = st.number_input("Seuil lessivage (mm)", min_value=0, value=int(p_to_edit.get('lessivage_seuil_mm', 25)))
                pe_dose = st.number_input("Dose référence", min_value=0.0, value=float(p_to_edit.get('dose_reference_kg_ha', 1.0)), step=0.1, format="%.2f")

                col_pb1, col_pb2 = st.columns(2)
                submit_pe_edit = col_pb1.form_submit_button("Sauvegarder", use_container_width=True)
                submit_pe_del = col_pb2.form_submit_button("🗑️ Supprimer", use_container_width=True)

                if submit_pe_edit:
                    data = storage.load_data('produits')
                    for prod in data['produits']:
                        if prod.get('id') == p_to_edit.get('id') or prod.get('nom') == p_select_nom:
                            prod['nom'] = pe_nom
                            prod['n_amm'] = pe_amm
                            prod['type'] = pe_type
                            prod['persistance_jours'] = pe_pers
                            prod['lessivage_seuil_mm'] = pe_less
                            prod['dose_reference_kg_ha'] = pe_dose
                            break
                    storage.save_data('produits', data)
                    st.cache_resource.clear()
                    st.success("✅ Modifications enregistrées.")
                    st.rerun()

                if submit_pe_del:
                    data = storage.load_data('produits')
                    data['produits'] = [p for p in data['produits'] if (p.get('id') != p_to_edit.get('id') and p.get('nom') != p_select_nom)]
                    storage.save_data('produits', data)
                    st.cache_resource.clear()
                    st.warning(f"🗑️ Produit '{p_select_nom}' supprimé.")
                    st.rerun()
        else:
            st.info("Aucun produit à modifier.")
