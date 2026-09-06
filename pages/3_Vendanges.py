"""
Page Suivi des Vendanges
Saisie tickets, calculs automatiques, dashboard historique
Fichier : pages/3_Vendanges.py
"""

import streamlit as st
import sys
import os
from datetime import datetime, date
import pandas as pd
import json
import plotly.express as px
import plotly.graph_objects as go
from storage import DataManager
import traceback

# --- Initialisation des chemins et Imports ---
try:
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from mildiou_prevention import SystemeDecision, ConfigVignoble
except ImportError:
    st.error("❌ Erreur d'importation : Le fichier 'mildiou_prevention.py' n'est pas trouvé.")
    st.stop()

st.set_page_config(page_title="🍇 Vendanges", page_icon="🍇", layout="wide")
st.title("🍇 Suivi des Vendanges")


# Classe de gestion des vendanges
class GestionVendanges:
    def __init__(self, fichier='vendanges'):
        self.key = fichier.replace('.json', '')
        self.storage = DataManager()
        self.donnees = self.charger_donnees()

    def charger_donnees(self):
        """Charge les données vendanges via DataManager"""
        data = self.storage.load_data(self.key, default_factory=self.creer_structure_defaut)
        # Migration : supprimer campagne_courante si elle existe
        if 'campagne_courante' in data:
            del data['campagne_courante']
        return data

    def creer_structure_defaut(self):
        """Crée structure par défaut avec historique vide"""
        return {'campagnes': []}

    def sauvegarder(self):
        """Sauvegarde les données via DataManager"""
        self.storage.save_data(self.key, self.donnees)

    def get_campagne(self, annee):
        """Récupère une campagne par année"""
        for c in self.donnees['campagnes']:
            if c['annee'] == annee:
                return c
        return None

    def get_campagne_active(self):
        """Retourne la campagne active (dernière non-validée ou année en cours)"""
        # Chercher la dernière campagne non-validée
        campagnes_non_validees = [
            c for c in self.donnees['campagnes']
            if not c['validation']['validee']
        ]

        if campagnes_non_validees:
            # Retourner la plus récente
            return max(campagnes_non_validees, key=lambda x: x['annee'])

        # Sinon, retourner l'année en cours
        annee_courante = datetime.now().year
        campagne = self.get_campagne(annee_courante)

        if not campagne:
            campagne = self.creer_campagne(annee_courante)

        return campagne

    def get_toutes_campagnes_triees(self):
        """Retourne toutes les campagnes triées par année décroissante"""
        return sorted(self.donnees['campagnes'], key=lambda x: x['annee'], reverse=True)

    def creer_campagne(self, annee):
        """Crée une nouvelle campagne"""
        campagne = {
            'annee': annee,
            'status': 'en_cours',
            'tickets': [],
            'parametres': {
                'rendement_theorique': 73.0,
                'prix_u': 100.0000,
                'frais_vinif_u': 0.1573,
                'prime_u': 0.0847,
                'prix_hl_deg_vdp': 6.28,
                'prix_hl_deg_vdt': 5.2713
            },
            'surface_vendangee': {
                'total_ha': 2.05,
                'notes': ''
            },
            'validation': {
                'validee': False,
                'hl_reel': None,
                'prix_u_reel': None,
                'frais_reels': None,
                'prime_reelle': None,
                'date_validation': None
            },
            'parcelles_vendangees': []
        }
        self.donnees['campagnes'].append(campagne)
        self.sauvegarder()
        return campagne

    def calculer_metriques_ticket(self, poids_kg, degre, params):
        """Calcule la catégorie, le volume hL, les hL.° et le montant estimé d'un ticket basé sur le rendement jus (73%)"""
        prix_vdp = params.get('prix_hl_deg_vdp', 6.28)
        prix_vdt = params.get('prix_hl_deg_vdt', 5.2713)
        rdt_theo = params.get('rendement_theorique', 73.0)
        rdt_ratio = (rdt_theo / 100.0) if rdt_theo > 1 else (rdt_theo if rdt_theo > 0 else 0.73)

        categorie = "VDP" if degre >= 10.5 else "VDT"

        # Volume hL = Poids en kg × rendement jus / 100
        volume_hl = (poids_kg * rdt_ratio) / 100.0

        # Hl° = Poids kg × Degré × rendement jus / 100
        hl_degres = (poids_kg * degre * rdt_ratio) / 100.0

        prix_unitaire = prix_vdp if categorie == "VDP" else prix_vdt
        montant_estime = hl_degres * prix_unitaire

        return {
            'categorie': categorie,
            'volume_hl': volume_hl,
            'hl_degres': hl_degres,
            'prix_unitaire_applique': prix_unitaire,
            'montant_estime_eur': montant_estime
        }

    def ajouter_ticket(self, date_ticket, ticket):
        """Ajoute un ticket de vendange (crée la campagne si nécessaire)"""
        # Extraire l'année de la date du ticket
        annee = datetime.strptime(date_ticket, '%Y-%m-%d').year

        campagne = self.get_campagne(annee)
        if not campagne:
            campagne = self.creer_campagne(annee)

        # Vérifier si la campagne est validée
        if campagne['validation']['validee']:
            return False, f"❌ La campagne {annee} est validée. Impossible d'ajouter des tickets."

        params = campagne.get('parametres', {})
        metriques = self.calculer_metriques_ticket(ticket['poids_kg'], ticket['degre'], params)
        ticket.update(metriques)

        ticket['id'] = len(campagne['tickets']) + 1
        campagne['tickets'].append(ticket)
        self.sauvegarder()
        return True, f"✅ Ticket enregistré pour la campagne {annee}"

    def supprimer_ticket(self, annee, ticket_id):
        """Supprime un ticket"""
        campagne = self.get_campagne(annee)
        if campagne:
            campagne['tickets'] = [t for t in campagne['tickets'] if t['id'] != ticket_id]
            self.sauvegarder()

    def calculer_totaux(self, annee):
        """Calcule les totaux d'une campagne selon les règles exactes de valorisation"""
        campagne = self.get_campagne(annee)
        if not campagne or not campagne['tickets']:
            return None

        tickets = campagne['tickets']
        params = campagne.get('parametres', {})
        prix_vdp = params.get('prix_hl_deg_vdp', 6.28)
        prix_vdt = params.get('prix_hl_deg_vdt', 5.2713)
        rdt_theo = params.get('rendement_theorique', 73.0)
        rdt_ratio = (rdt_theo / 100.0) if rdt_theo > 1 else (rdt_theo if rdt_theo > 0 else 0.73)

        # Mettre à jour / recalculer métriques par ticket
        for t in tickets:
            metriques = self.calculer_metriques_ticket(t['poids_kg'], t['degre'], params)
            t.update(metriques)

        poids_total = sum(t['poids_kg'] for t in tickets)
        poids_vdp = sum(t['poids_kg'] for t in tickets if t['categorie'] == 'VDP')
        poids_vdt = sum(t['poids_kg'] for t in tickets if t['categorie'] == 'VDT')

        pct_poids_vdp = (poids_vdp / poids_total * 100) if poids_total > 0 else 0.0
        pct_poids_vdt = (poids_vdt / poids_total * 100) if poids_total > 0 else 0.0

        degre_moyen = (sum(t['poids_kg'] * t['degre'] for t in tickets) / poids_total) if poids_total > 0 else 0.0

        volume_vdp_hl = sum(t['volume_hl'] for t in tickets if t['categorie'] == 'VDP')
        volume_vdt_hl = sum(t['volume_hl'] for t in tickets if t['categorie'] == 'VDT')
        volume_total_hl = sum(t['volume_hl'] for t in tickets)

        pct_volume_vdp = (volume_vdp_hl / volume_total_hl * 100) if volume_total_hl > 0 else 0.0
        pct_volume_vdt = (volume_vdt_hl / volume_total_hl * 100) if volume_total_hl > 0 else 0.0

        hl_degres_vdp = sum(t['hl_degres'] for t in tickets if t['categorie'] == 'VDP')
        hl_degres_vdt = sum(t['hl_degres'] for t in tickets if t['categorie'] == 'VDT')
        hl_degres_total = sum(t['hl_degres'] for t in tickets)

        ca_vdp_estime = sum(t['montant_estime_eur'] for t in tickets if t['categorie'] == 'VDP')
        ca_vdt_estime = sum(t['montant_estime_eur'] for t in tickets if t['categorie'] == 'VDT')
        ca_brut = ca_vdp_estime + ca_vdt_estime

        prix_moyen_pondere_hl_deg = (ca_brut / hl_degres_total) if hl_degres_total > 0 else 0.0

        # Production en Litres = Poids total × Rendement Jus (0.73)
        production_litres = poids_total * rdt_ratio

        # Primes et Frais
        prime_u = params.get('prime_u', 0.0847)
        frais_u = params.get('frais_vinif_u', 0.1573)

        prime_total = prime_u * poids_total
        frais_total = frais_u * poids_total

        # Revenu Net = CA Brut (Revenus théoriques) + Primes - Frais
        revenu_net = ca_brut + prime_total - frais_total

        # Prix €/L = Revenu Net / Production en Litres
        euro_par_litre = (revenu_net / production_litres) if production_litres > 0 else 0.0
        euro_par_hl = euro_par_litre * 100.0

        return {
            'nb_tickets': len(tickets),
            'poids_total': poids_total,
            'poids_vdp': poids_vdp,
            'poids_vdt': poids_vdt,
            'pct_poids_vdp': pct_poids_vdp,
            'pct_poids_vdt': pct_poids_vdt,
            'degre_moyen': degre_moyen,
            'volume_total_hl': volume_total_hl,
            'volume_vdp_hl': volume_vdp_hl,
            'volume_vdt_hl': volume_vdt_hl,
            'pct_volume_vdp': pct_volume_vdp,
            'pct_volume_vdt': pct_volume_vdt,
            'hl_degres_vdp': hl_degres_vdp,
            'hl_degres_vdt': hl_degres_vdt,
            'hl_degres_total': hl_degres_total,
            'ca_vdp_estime': ca_vdp_estime,
            'ca_vdt_estime': ca_vdt_estime,
            'ca_total_estime': ca_brut,
            'ca_brut': ca_brut,
            'prix_moyen_pondere_hl_deg': prix_moyen_pondere_hl_deg,
            'hl_estime': hl_degres_total,
            'production_litres': production_litres,
            'prime_total': prime_total,
            'frais_total': frais_total,
            'revenu_net': revenu_net,
            'euro_par_litre': euro_par_litre,
            'euro_par_hl': euro_par_hl
        }

    def valider_campagne(self, annee, donnees_validation):
        """Valide une campagne avec données réelles"""
        campagne = self.get_campagne(annee)
        if campagne:
            campagne['validation'].update(donnees_validation)
            campagne['validation']['validee'] = True
            campagne['validation']['date_validation'] = datetime.now().strftime('%Y-%m-%d')
            campagne['status'] = 'validee'

            # Calculer données historiques pour dashboard
            tickets = campagne['tickets']
            if tickets:
                poids_total = sum(t['poids_kg'] for t in tickets)
                degre_moyen = sum(t['poids_kg'] * t['degre'] for t in tickets) / poids_total if poids_total > 0 else 0

                hl_reel = donnees_validation['hl_reel']
                prix_u_reel = donnees_validation['prix_u_reel']
                prime_reelle = donnees_validation.get('prime_reelle', 0)
                frais_reels = donnees_validation.get('frais_reels', 0)

                surface_ha = campagne.get('surface_vendangee', {}).get('total_ha', 2.05)

                ca_brut = (hl_reel * prix_u_reel) + prime_reelle
                ca_net = ca_brut - frais_reels

                # Rendement réel EN POURCENTAGE
                rendement_reel = (hl_reel * 100) / (poids_total * degre_moyen) if (poids_total > 0 and degre_moyen > 0) else 0

                # Production litres réelle
                production_litres = poids_total * (rendement_reel / 100)

                # €/Hl RÉEL : CA Net / Production en Hl
                # Production Hl = Production Litres / 100
                production_hl = production_litres / 100
                euro_par_hl = ca_net / production_hl if production_hl > 0 else 0

                # Poids/Ha en TONNES
                poids_ha_tonnes = (poids_total / 1000) / surface_ha if surface_ha > 0 else 0

                campagne['donnees_historiques'] = {
                    'poids_kg': poids_total,
                    'hl': hl_reel,
                    'degre_moyen': degre_moyen,
                    'ca_brut': ca_brut,
                    'ca_net': ca_net,
                    'total_ha': surface_ha,
                    'ca_ha': ca_brut / surface_ha if surface_ha > 0 else 0,
                    'euro_hl': euro_par_hl,  # Déjà en €/Hl (multiplié par 100)
                    'poids_ha': poids_ha_tonnes,  # en tonnes
                    'rendement_reel': rendement_reel,  # en %
                    'prime_totale': prime_reelle,
                    'frais_totaux': frais_reels
                }

            self.sauvegarder()

    def vider_historique(self):
        """Vide tout l'historique (DANGER)"""
        self.donnees['campagnes'] = []
        self.sauvegarder()

    def devalider_campagne(self, annee):
        """Dévalide une campagne pour permettre modifications"""
        campagne = self.get_campagne(annee)
        if campagne:
            campagne['validation']['validee'] = False
            campagne['status'] = 'en_cours'
            # Supprimer données historiques
            if 'donnees_historiques' in campagne:
                del campagne['donnees_historiques']
            self.sauvegarder()

    def supprimer_campagne(self, annee):
        """Supprime une campagne spécifique"""
        self.donnees['campagnes'] = [c for c in self.donnees['campagnes'] if c['annee'] != annee]
        self.sauvegarder()

    def importer_historique(self, df):
        """Importe l'historique depuis un DataFrame avec l'ensemble des métriques d'Excel"""
        for _, row in df.iterrows():
            try:
                annee = int(row['Année'])
            except:
                continue

            if self.get_campagne(annee):
                continue

            poids_kg = self.storage._get_num(row.get('Poids Kg', row.get('poids_kg', 0)))
            hl_deg = self.storage._get_num(row.get('Hl°', row.get('H°', row.get('hl', 0))))
            prix_u = self.storage._get_num(row.get('Prix U', row.get('prix_u', 100)))
            ca_brut = self.storage._get_num(row.get('Revenus €', row.get('Revenus', row.get('ca_brut', 0))))
            prime_u = self.storage._get_num(row.get('Prime U', row.get('prime_u', 0)))
            prime_eur = self.storage._get_num(row.get('Prime €', row.get('prime_totale', 0)))
            frais_u = self.storage._get_num(row.get('Frais U', row.get('frais_u', 15.73)))
            frais_eur = self.storage._get_num(row.get('Frais (€)', row.get('Frais', row.get('frais_totaux', 0))))
            degre_moyen = self.storage._get_num(row.get('degré réel', row.get('Degré', row.get('degre_moyen', 0))))
            rendement_jus = self.storage._get_num(row.get('rendement jus', row.get('rendement_reel', 73)))
            ca_net = self.storage._get_num(row.get('Chiffre Affaire Net €', row.get('ca_net', 0)))
            total_ha = self.storage._get_num(row.get('Total Ha', row.get('total_ha', 2.05)))
            ca_ha = self.storage._get_num(row.get('CA / Ha (€)', row.get('ca_ha', 0)))
            euro_hl = self.storage._get_num(row.get('€/hl (72% rdt)', row.get('euro_hl', 0)))
            poids_ha = self.storage._get_num(row.get('Poids/Ha', row.get('poids_ha', 0)))

            if ca_net == 0 and ca_brut > 0:
                ca_net = ca_brut - frais_eur

            # Si le degré réel n'est pas fourni mais qu'on a hl° et poids
            if degre_moyen == 0 and hl_deg > 0 and poids_kg > 0:
                rdt_ratio = (rendement_jus / 100) if rendement_jus > 1 else (rendement_jus if rendement_jus > 0 else 0.73)
                degre_moyen = (hl_deg * 100) / (poids_kg * rdt_ratio) if rdt_ratio > 0 else 0

            campagne = {
                'annee': annee,
                'status': 'validee',
                'tickets': [],
                'parametres': {
                    'rendement_theorique': rendement_jus,
                    'prix_u': prix_u,
                    'frais_vinif_u': frais_u,
                    'prime_u': prime_u,
                    'prix_hl_deg_vdp': 6.28,
                    'prix_hl_deg_vdt': 5.2713,
                    'ratio_kg_hl': 130.0
                },
                'validation': {
                    'validee': True,
                    'hl_reel': hl_deg,
                    'prix_u_reel': prix_u,
                    'frais_reels': frais_eur,
                    'prime_reelle': prime_eur,
                    'date_validation': f"{annee}-12-31"
                },
                'donnees_historiques': {
                    'poids_kg': poids_kg,
                    'hl': hl_deg,
                    'degre_moyen': degre_moyen,
                    'ca_brut': ca_brut,
                    'ca_net': ca_net,
                    'total_ha': total_ha,
                    'ca_ha': ca_ha if ca_ha > 0 else (ca_brut / total_ha if total_ha > 0 else 0),
                    'euro_hl': euro_hl,
                    'poids_ha': poids_ha if poids_ha > 0 else ((poids_kg / 1000) / total_ha if total_ha > 0 else 0),
                    'rendement_reel': rendement_jus,
                    'prime_totale': prime_eur,
                    'frais_totaux': frais_eur
                },
                'parcelles_vendangees': []
            }

            self.donnees['campagnes'].append(campagne)

        self.sauvegarder()


# Initialiser
@st.cache_resource
def init_vendanges():
    return GestionVendanges()

vendanges = init_vendanges()

# Charger config vignoble pour surface totale
try:
    config = ConfigVignoble()
    surface_totale = sum(p.get('surface_ha', 0) for p in config.parcelles)
    if surface_totale == 0:
        surface_totale = 2.05
except:
    surface_totale = 2.05

# Récupérer la campagne active
campagne_active = vendanges.get_campagne_active()
annee_active = campagne_active['annee']

# Gérer la navigation par onglets via session_state pour éviter les resets
tab_titles = [
    "📝 Saisie Tickets",
    "📊 Suivi Campagnes",
    "📈 Dashboard",
    "📑 Historique & Import"
]

if "active_tab_vendanges" not in st.session_state:
    st.session_state.active_tab_vendanges = tab_titles[0]

selected_tab = st.radio(
    "Navigation",
    tab_titles,
    index=tab_titles.index(st.session_state.active_tab_vendanges),
    horizontal=True,
    label_visibility="collapsed"
)
st.session_state.active_tab_vendanges = selected_tab

st.markdown("---")

def afficher_synthese_campagne(totaux):
    """Affiche le panneau / widget de synthèse de la campagne"""
    if not totaux:
        st.info("Aucune donnée disponible pour cette campagne.")
        return

    st.markdown("### 📊 Synthèse Globale de Récolte")

    kpi1, kpi2, kpi3, kpi4 = st.columns(4)
    with kpi1:
        st.metric("⚖️ Poids Total", f"{totaux['poids_total']:,.0f} kg", f"{totaux['nb_tickets']} tickets")
    with kpi2:
        st.metric("🌡️ Degré Moyen Pondéré", f"{totaux['degre_moyen']:.2f}°")
    with kpi3:
        st.metric("💰 CA Brut Estimé", f"{totaux['ca_brut']:,.2f} €")
    with kpi4:
        st.metric("🏷️ Prix Moyen / hL.°", f"{totaux['prix_moyen_pondere_hl_deg']:.4f} €")

    st.markdown("---")

    col_vdp, col_vdt, col_cumul = st.columns(3)

    with col_vdp:
        st.markdown("#### 🟢 Catégorie VDP (>= 10.5°)")
        st.write(f"**Tonnage :** {totaux['poids_vdp']:,.0f} kg ({totaux['pct_poids_vdp']:.1f}%)")
        st.write(f"**Volume Jus :** {totaux['volume_vdp_hl']:.2f} hL ({totaux['pct_volume_vdp']:.1f}%)")
        st.write(f"**Cumul hL.° :** {totaux['hl_degres_vdp']:.2f}")
        st.write(f"**Montant Estimé :** {totaux['ca_vdp_estime']:,.2f} €")

    with col_vdt:
        st.markdown("#### 🟠 Catégorie VDT (< 10.5°)")
        st.write(f"**Tonnage :** {totaux['poids_vdt']:,.0f} kg ({totaux['pct_poids_vdt']:.1f}%)")
        st.write(f"**Volume Jus :** {totaux['volume_vdt_hl']:.2f} hL ({totaux['pct_volume_vdt']:.1f}%)")
        st.write(f"**Cumul hL.° :** {totaux['hl_degres_vdt']:.2f}")
        st.write(f"**Montant Estimé :** {totaux['ca_vdt_estime']:,.2f} €")

    with col_cumul:
        st.markdown("#### 🍷 Valorisation Net & Performance")
        st.write(f"**Volume Jus Total :** {totaux['volume_total_hl']:.2f} hL ({totaux['production_litres']:,.0f} L)")
        st.write(f"**Cumul Total hL.° :** {totaux['hl_degres_total']:.2f}")
        st.write(f"**Revenu Net Estimé :** {totaux['revenu_net']:,.2f} €")
        st.write(f"**Prix / Litre (Jus) :** {totaux['euro_par_litre']:.4f} € / L ({totaux['euro_par_hl']:.2f} €/hL)")


# ========================================
# TAB 1 : SAISIE TICKETS
# ========================================
if selected_tab == tab_titles[0]:
    st.subheader("📝 Saisie des Tickets de Vendange")

    st.info(f"💡 Les tickets sont automatiquement affectés à la campagne correspondant à leur date.")

    col_form, col_preview = st.columns([2, 1])

    params_active = campagne_active.get('parametres', {})
    prix_vdp_act = params_active.get('prix_hl_deg_vdp', 6.28)
    prix_vdt_act = params_active.get('prix_hl_deg_vdt', 5.2713)
    rdt_act = params_active.get('rendement_theorique', 73.0)
    rdt_ratio_act = (rdt_act / 100.0) if rdt_act > 1 else (rdt_act if rdt_act > 0 else 0.73)

    with col_form:
        st.markdown("**Nouveau Ticket de Vendange**")

        col1, col2 = st.columns(2)

        with col1:
            date_vendange = st.date_input(
                "📅 Date",
                value=date.today(),
                format="DD/MM/YYYY"
            )

            poids = st.number_input(
                "⚖️ Poids (kg)",
                min_value=0,
                max_value=50000,
                value=2000,
                step=100,
                help="Poids de la benne en kg"
            )

        with col2:
            num_ticket = st.text_input(
                "🎫 N° Ticket/Benne",
                placeholder="Ex: B001, T123...",
                help="Optionnel : numéro de la benne ou du ticket"
            )

            col_deg_val, col_deg_badge = st.columns([2, 1])
            with col_deg_val:
                degre = st.number_input(
                    "🌡️ Degré (%)",
                    min_value=0.0,
                    max_value=20.0,
                    value=12.0,
                    step=0.1,
                    format="%.1f",
                    help="Degré mesuré (>= 10.5° = VDP, < 10.5° = VDT)"
                )
            with col_deg_badge:
                st.write("")
                st.write("")
                if degre >= 10.5:
                    st.success("🏷️ **VDP**")
                else:
                    st.warning("🏷️ **VDT**")

        notes = st.text_area(
            "📝 Notes (optionnel)",
            placeholder="Qualité, tri, observations...",
            height=80
        )

        # Aperçu calculé en temps réel sur le formulaire
        cat_preview = "VDP" if degre >= 10.5 else "VDT"
        vol_preview = (poids * rdt_ratio_act) / 100.0
        hldeg_preview = (poids * degre * rdt_ratio_act) / 100.0
        pu_preview = prix_vdp_act if cat_preview == "VDP" else prix_vdt_act
        montant_preview = hldeg_preview * pu_preview
        vol_hl_preview = vol_preview

        st.markdown("##### 🔍 Aperçu Calculé du Ticket")
        pcol1, pcol2, pcol3, pcol4 = st.columns(4)
        with pcol1:
            st.metric("Catégorie", cat_preview)
        with pcol2:
            st.metric("Volume Jus Estimé", f"{vol_hl_preview:.2f} hL")
        with pcol3:
            st.metric("hL.° Générés", f"{hldeg_preview:.2f}")
        with pcol4:
            st.metric("Montant Estimé", f"{montant_preview:,.2f} €")

        if st.button("✅ Enregistrer le Ticket", type="primary", use_container_width=True):
            if poids > 0 and degre > 0:
                ticket = {
                    'date': date_vendange.strftime('%Y-%m-%d'),
                    'num_ticket': num_ticket if num_ticket else f"T{date_vendange.strftime('%Y%m%d')}",
                    'poids_kg': poids,
                    'degre': degre,
                    'notes': notes
                }

                success, message = vendanges.ajouter_ticket(date_vendange.strftime('%Y-%m-%d'), ticket)

                if success:
                    st.success(f"{message} : {poids} kg à {degre}° ({cat_preview})")
                    st.rerun()
                else:
                    st.error(message)
            else:
                st.error("⚠️ Poids et degré doivent être > 0")

    with col_preview:
        st.markdown("**📊 Campagne Active**")
        st.metric("Année", annee_active)

        totaux = vendanges.calculer_totaux(annee_active)

        if totaux:
            st.metric("Tickets", totaux['nb_tickets'])
            st.metric("Poids Total", f"{totaux['poids_total'] or 0:,.0f} kg")
            st.metric("Degré Moyen Pondéré", f"{totaux['degre_moyen'] or 0:.2f}°")
            st.metric("Total hL.°", f"{totaux['hl_degres_total'] or 0:.2f}")
            st.metric("CA Total Estimé", f"{totaux['ca_total_estime'] or 0:,.2f} €")
        else:
            st.info("Aucun ticket saisi")

    # Synthèse globale de la campagne active
    if totaux:
        st.markdown("---")
        afficher_synthese_campagne(totaux)

    # Liste des tickets de la campagne active
    st.markdown("---")
    st.subheader(f"🎫 Tickets de la Campagne {annee_active}")

    if campagne_active['tickets']:
        df_tickets = pd.DataFrame(campagne_active['tickets'])
        df_tickets['date'] = pd.to_datetime(df_tickets['date']).dt.strftime('%d/%m/%Y')

        df_tickets['Catégorie'] = df_tickets['categorie'].apply(
            lambda cat: "🟢 VDP" if cat == "VDP" else "🟠 VDT"
        )
        df_tickets['Volume (hL)'] = df_tickets['volume_hl'].apply(lambda x: f"{x:.2f}")
        df_tickets['hL.°'] = df_tickets['hl_degres'].apply(lambda x: f"{x:.2f}")
        df_tickets['Montant (€)'] = df_tickets['montant_estime_eur'].apply(lambda x: f"{x:,.2f} €")

        cols_map = {
            'date': 'Date',
            'num_ticket': 'N° Ticket',
            'poids_kg': 'Poids (kg)',
            'degre': 'Degré (°)',
            'Catégorie': 'Catégorie',
            'Volume (hL)': 'Volume (hL)',
            'hL.°': 'hL.°',
            'Montant (€)': 'Montant (€)',
            'notes': 'Notes'
        }

        df_show = df_tickets[[c for c in cols_map.keys() if c in df_tickets.columns]].rename(columns=cols_map)

        st.dataframe(
            df_show,
            use_container_width=True,
            hide_index=True
        )

        # Supprimer un ticket
        if not campagne_active['validation']['validee']:
            with st.expander("🗑️ Supprimer un ticket"):
                options_suppr = [f"ID {t['id']} - {t['num_ticket']} - {t['date']} - {t['poids_kg']}kg" for t in campagne_active['tickets']]

                ticket_a_supprimer_str = st.selectbox(
                    "Sélectionner le ticket à supprimer",
                    options=options_suppr,
                    key="ticket_suppr"
                )

                if st.button("🗑️ Confirmer Suppression", type="secondary"):
                    ticket_id = int(ticket_a_supprimer_str.split(' ')[1])
                    vendanges.supprimer_ticket(annee_active, ticket_id)
                    st.success("✅ Ticket supprimé")
                    st.rerun()
        else:
            st.warning("⚠️ Campagne validée : impossible de supprimer des tickets")
    else:
        st.info("📝 Aucun ticket saisi pour le moment. Utilisez le formulaire ci-dessus pour commencer.")

# ========================================
# TAB 2 : SUIVI CAMPAGNES
# ========================================
elif selected_tab == tab_titles[1]:
    st.subheader("📊 Suivi des Campagnes")

    # Sélecteur de campagne
    campagnes_disponibles = vendanges.get_toutes_campagnes_triees()

    if not campagnes_disponibles:
        st.info("📝 Aucune campagne disponible. Commencez par saisir des tickets dans l'onglet 'Saisie Tickets'.")
    else:
        # Créer un dict pour le selectbox
        options_campagnes = {}
        for c in campagnes_disponibles:
            statut = "✅ Validée" if c['validation']['validee'] else "🟡 En cours"
            nb_tickets = len(c['tickets'])
            options_campagnes[c['annee']] = f"{c['annee']} - {statut} ({nb_tickets} tickets)"

        annee_selectionnee = st.selectbox(
            "Choisir la campagne à afficher",
            options=list(options_campagnes.keys()),
            format_func=lambda x: options_campagnes[x],
            index=0  # Par défaut la plus récente
        )

        campagne = vendanges.get_campagne(annee_selectionnee)

        if not campagne['tickets']:
            st.info(f"📝 Aucune donnée pour {annee_selectionnee}. Saisissez des tickets avec cette date dans l'onglet 'Saisie Tickets'.")
        else:
            # Status
            if campagne['validation']['validee']:
                st.success("✅ Campagne Validée (données réelles)")
            else:
                st.warning("🟡 Campagne En Cours (estimation)")

            st.markdown("---")

            # Totaux et Synthèse Globale
            totaux = vendanges.calculer_totaux(annee_selectionnee)
            afficher_synthese_campagne(totaux)

            # Détail des tickets de la campagne
            st.markdown("---")
            st.subheader(f"🎫 Tickets Détaillés de la Récolte {annee_selectionnee}")

            if campagne['tickets']:
                df_t_sel = pd.DataFrame(campagne['tickets'])
                df_t_sel['date'] = pd.to_datetime(df_t_sel['date']).dt.strftime('%d/%m/%Y')

                df_t_sel['Catégorie'] = df_t_sel['categorie'].apply(
                    lambda cat: "🟢 VDP" if cat == "VDP" else "🟠 VDT"
                )
                df_t_sel['Volume (hL)'] = df_t_sel['volume_hl'].apply(lambda x: f"{x:.2f}")
                df_t_sel['hL.°'] = df_t_sel['hl_degres'].apply(lambda x: f"{x:.2f}")
                df_t_sel['Montant (€)'] = df_t_sel['montant_estime_eur'].apply(lambda x: f"{x:,.2f} €")

                cols_map = {
                    'date': 'Date',
                    'num_ticket': 'N° Ticket',
                    'poids_kg': 'Poids (kg)',
                    'degre': 'Degré (°)',
                    'Catégorie': 'Catégorie',
                    'Volume (hL)': 'Volume (hL)',
                    'hL.°': 'hL.°',
                    'Montant (€)': 'Montant (€)',
                    'notes': 'Notes'
                }

                df_show_sel = df_t_sel[[c for c in cols_map.keys() if c in df_t_sel.columns]].rename(columns=cols_map)

                st.dataframe(
                    df_show_sel,
                    use_container_width=True,
                    hide_index=True
                )

                csv_tickets = df_show_sel.to_csv(index=False).encode('utf-8')
                st.download_button(
                    label=f"📥 Télécharger le détail des tickets {annee_selectionnee} (CSV)",
                    data=csv_tickets,
                    file_name=f"tickets_vendanges_{annee_selectionnee}.csv",
                    mime="text/csv",
                    key=f"dl_tickets_{annee_selectionnee}"
                )
            else:
                st.info(f"Aucun ticket individuel saisi pour la campagne {annee_selectionnee}.")

            st.markdown("---")

            # Paramètres et calculs financiers
            st.subheader("💰 Paramètres et Calculs Financiers")

            col_param1, col_param2 = st.columns(2)

            with col_param1:
                st.markdown("**Paramètres de Valorisation hL.° & Vinification**")

                prix_vdp_val = st.number_input(
                    "Prix hL.° VDP (€)",
                    min_value=0.0,
                    value=campagne['parametres'].get('prix_hl_deg_vdp', 6.28),
                    step=0.0001,
                    format="%.4f",
                    key=f"prix_vdp_{annee_selectionnee}",
                    disabled=campagne['validation']['validee']
                )

                prix_vdt_val = st.number_input(
                    "Prix hL.° VDT (€)",
                    min_value=0.0,
                    value=campagne['parametres'].get('prix_hl_deg_vdt', 5.2713),
                    step=0.0001,
                    format="%.4f",
                    key=f"prix_vdt_{annee_selectionnee}",
                    disabled=campagne['validation']['validee']
                )

                rdt_theo = st.number_input(
                    "Rendement jus théorique (%)",
                    min_value=60.0,
                    max_value=80.0,
                    value=campagne['parametres'].get('rendement_theorique', 73.0),
                    step=0.1,
                    format="%.1f",
                    help="Pourcentage de jus extrait du raisin (73% par défaut)",
                    key=f"rdt_theo_{annee_selectionnee}",
                    disabled=campagne['validation']['validee']
                )

                prix_u = st.number_input(
                    "Prix U Coopérative (€/Hl°)",
                    min_value=0.0,
                    value=campagne['parametres']['prix_u'],
                    step=0.0001,
                    format="%.4f",
                    key=f"prix_u_{annee_selectionnee}",
                    disabled=campagne['validation']['validee']
                )

                prime_u = st.number_input(
                    "Prime U (€/kg)",
                    min_value=0.0,
                    value=campagne['parametres'].get('prime_u', 0.0),
                    step=0.0001,
                    format="%.4f",
                    help="Prime par kilogramme de raisin",
                    key=f"prime_u_{annee_selectionnee}",
                    disabled=campagne['validation']['validee']
                )

                frais_u = st.number_input(
                    "Frais vinification U (€/kg)",
                    min_value=0.0,
                    value=campagne['parametres']['frais_vinif_u'],
                    step=0.0001,
                    format="%.4f",
                    help="Frais par kilogramme de raisin",
                    key=f"frais_u_{annee_selectionnee}",
                    disabled=campagne['validation']['validee']
                )

                if not campagne['validation']['validee']:
                    if st.button("💾 Sauvegarder Paramètres", key=f"save_params_{annee_selectionnee}"):
                        campagne['parametres']['prix_hl_deg_vdp'] = prix_vdp_val
                        campagne['parametres']['prix_hl_deg_vdt'] = prix_vdt_val
                        campagne['parametres']['rendement_theorique'] = rdt_theo
                        campagne['parametres']['prix_u'] = prix_u
                        campagne['parametres']['prime_u'] = prime_u
                        campagne['parametres']['frais_vinif_u'] = frais_u
                        vendanges.sauvegarder()
                        st.success("✅ Paramètres sauvegardés")
                        st.rerun()

            with col_param2:
                st.markdown("**Résultats Financiers & Valorisation**")

                st.metric("Hl° Cumulés", f"{totaux['hl_degres_total']:.2f}")
                st.metric("Production Jus", f"{totaux['production_litres']:,.0f} L ({totaux['volume_total_hl']:.2f} hL)")
                st.metric("Revenus Théoriques (CA Brut)", f"{totaux['ca_brut']:,.2f} €")
                st.metric("Prime Totale", f"{totaux['prime_total']:,.2f} €")
                st.metric("Frais Vinification", f"{totaux['frais_total']:,.2f} €")
                st.metric("**Revenu Net**", f"**{totaux['revenu_net']:,.2f} €**")

                col_ind1, col_ind2 = st.columns(2)
                with col_ind1:
                    st.metric("Prix € / Litre", f"{totaux['euro_par_litre']:.4f} €/L")
                with col_ind2:
                    st.metric("Prix € / hL", f"{totaux['euro_par_hl']:.2f} €/hL")

            # Surface vendangée
            st.markdown("---")
            st.subheader("📏 Surface Vendangée")

            col_surf1, col_surf2 = st.columns([1, 2])

            with col_surf1:
                surface_vend = st.number_input(
                    "Surface vendangée (ha)",
                    min_value=0.0,
                    max_value=10.0,
                    value=campagne.get('surface_vendangee', {}).get('total_ha', surface_totale),
                    step=0.01,
                    format="%.2f",
                    key=f"surface_vend_{annee_selectionnee}",
                    disabled=campagne['validation']['validee']
                )

            with col_surf2:
                notes_surface = st.text_area(
                    "Notes surface (optionnel)",
                    value=campagne.get('surface_vendangee', {}).get('notes', ''),
                    placeholder="Ex: Gel sur Parcelle 2 (0.5 ha), Grêle Parcelle 1...",
                    height=80,
                    key=f"notes_surf_{annee_selectionnee}",
                    disabled=campagne['validation']['validee']
                )

            if not campagne['validation']['validee']:
                if st.button("💾 Sauvegarder Surface", key=f"save_surface_{annee_selectionnee}"):
                    campagne['surface_vendangee'] = {
                        'total_ha': surface_vend,
                        'notes': notes_surface
                    }
                    vendanges.sauvegarder()
                    st.success("✅ Surface sauvegardée")
                    st.rerun()

            # Validation campagne
            st.markdown("---")
            st.subheader("✅ Validation de la Campagne")

            if campagne['validation']['validee']:
                st.success("✅ Campagne Validée")

                val = campagne['validation']
                col_v1, col_v2, col_v3 = st.columns(3)

                with col_v1:
                    st.metric("Hl° Réel (Facture)", f"{val['hl_reel']:.1f}" if val['hl_reel'] else "N/A")

                with col_v2:
                    st.metric("Prix U Réel", f"{val['prix_u_reel']:.4f} €" if val['prix_u_reel'] else "N/A")

                with col_v3:
                    poids_degre = totaux['poids_total'] * totaux['degre_moyen']
                    rdt_reel = (val['hl_reel'] * 100) / poids_degre * 100 if val['hl_reel'] and poids_degre else 0
                    st.metric("Rendement Réel", f"{rdt_reel or 0:.1f}%")

                # Bouton dévalider
                st.markdown("---")
                st.warning("⚠️ **Dévalider la campagne** pour pouvoir modifier les tickets ou paramètres")
                if st.button("🔄 Dévalider la Campagne", type="secondary"):
                    vendanges.devalider_campagne(annee_selectionnee)
                    st.success(f"✅ Campagne {annee_selectionnee} dévalidée. Vous pouvez maintenant la modifier.")
                    st.rerun()

            else:
                with st.form(f"form_validation_{annee_selectionnee}"):
                    st.markdown("Lorsque vous recevez la facture de la coopérative, validez les données réelles :")
                    st.info("💡 La validation archivera cette campagne dans l'historique.")

                    col_v1, col_v2 = st.columns(2)

                    with col_v1:
                        hl_reel = st.number_input(
                            "Hl° Réel (facturé)",
                            min_value=0.0,
                            value=hl_calc,
                            step=0.1
                        )

                        prix_u_reel = st.number_input(
                            "Prix U Réel (€/Hl°)",
                            min_value=0.0,
                            value=prix_u,
                            step=0.0001,
                            format="%.4f"
                        )

                    with col_v2:
                        prime_reelle = st.number_input(
                            "Prime Réelle (€ total)",
                            min_value=0.0,
                            value=prime_calc,
                            step=0.01
                        )

                        frais_reels = st.number_input(
                            "Frais Réels (€ total)",
                            min_value=0.0,
                            value=frais_total,
                            step=0.01
                        )

                    if st.form_submit_button("✅ Valider la Campagne", type="primary"):
                        donnees_val = {
                            'hl_reel': hl_reel,
                            'prix_u_reel': prix_u_reel,
                            'prime_reelle': prime_reelle,
                            'frais_reels': frais_reels
                        }

                        vendanges.valider_campagne(annee_selectionnee, donnees_val)
                        st.success(f"✅ Campagne {annee_selectionnee} validée !")
                        st.balloons()
                        st.rerun()

# ========================================
# TAB 3 : DASHBOARD GRAPHIQUES
# ========================================
elif selected_tab == tab_titles[2]:
    col_title, col_refresh = st.columns([3, 1])
    with col_title:
        st.subheader("📈 Dashboard Historique")
    with col_refresh:
        if st.button("🔄 Actualiser Dashboard", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

    campagnes = [c for c in vendanges.donnees['campagnes'] if c.get('donnees_historiques')]

    if not campagnes:
        st.info("📊 Aucune donnée historique. Importez vos données Excel dans l'onglet 'Historique & Import' ou validez une campagne.")
    else:
        data = []
        for c in campagnes:
            hist = c.get('donnees_historiques', {})

            # CORRECTION : Si euro_hl semble être 100x trop grand (ancienne version), on corrige
            euro_hl_value = hist.get('euro_hl', 0)
            if euro_hl_value > 1000:
                euro_hl_value = euro_hl_value / 100

            # Calculs consolidés
            ca_net = hist.get('ca_net', 0)
            total_ha = hist.get('total_ha', surface_totale)
            if total_ha == 0: total_ha = surface_totale

            # CA/Ha calculé dynamiquement pour éviter les zéros du GSheet
            ca_ha_calc = ca_net / total_ha if total_ha > 0 else 0

            # Rendement : s'assurer qu'il est en % (parfois stocké en ratio 0.73 au lieu de 73)
            rdt_reel = hist.get('rendement_reel')
            if rdt_reel is None:
                rdt_reel = 0.0

            if 0 < rdt_reel < 2:
                rdt_reel = rdt_reel * 100

            data.append({
                'Année': c['annee'],
                'Poids_kg': hist.get('poids_kg', 0),
                'Total_Ha': total_ha,
                'Poids_Ha': hist.get('poids_ha', 0),
                'CA_Ha': ca_ha_calc,
                'Euro_Hl': euro_hl_value,
                'CA_Net': ca_net,
                'Rendement_Reel': rdt_reel,
                'Degre': hist.get('degre_moyen', 12.0)
            })

        df = pd.DataFrame(data).sort_values('Année')
        df['Année_str'] = df['Année'].astype(str)

        if len(df) > 0:
            # --- KPI CARDS ---
            last_year = df.iloc[-1]
            avg_ca_ha = df['CA_Ha'].mean()
            avg_euro_hl = df['Euro_Hl'].mean()

            kpi1, kpi2, kpi3, kpi4 = st.columns(4)
            with kpi1:
                st.metric(f"Poids {last_year['Année']}", f"{last_year['Poids_kg']:,.0f} kg",
                          delta=f"{last_year['Poids_kg'] - df.iloc[-2]['Poids_kg']:,.0f}" if len(df) > 1 else None)
            with kpi2:
                st.metric(f"CA/Ha {last_year['Année']}", f"{last_year['CA_Ha']:,.0f} €",
                          delta=f"{last_year['CA_Ha'] - avg_ca_ha:,.0f} vs moy", delta_color="normal")
            with kpi3:
                st.metric(f"Prix Hl {last_year['Année']}", f"{last_year['Euro_Hl']:.2f} €",
                          delta=f"{last_year['Euro_Hl'] - avg_euro_hl:.2f} vs moy")
            with kpi4:
                st.metric(f"Rendement {last_year['Année']}", f"{last_year['Rendement_Reel']:.1f}%")

            st.markdown("---")

            # --- GRAPHIQUES PLOTLY ---

            def create_bar_chart(df, x, y, title, color_hex="#3366CC"):
                fig = px.bar(df, x=x, y=y, title=title,
                             labels={x: 'Année', y: title.split(' (')[0]},
                             template="plotly_dark")
                fig.update_traces(marker_color=color_hex, opacity=0.8)
                fig.update_layout(margin=dict(l=20, r=20, t=40, b=20), height=350)
                return fig

            def create_line_chart(df, x, y, title, color_hex="#FF9900"):
                fig = px.line(df, x=x, y=y, title=title, markers=True,
                              labels={x: 'Année', y: title.split(' (')[0]},
                              template="plotly_dark")
                fig.update_traces(line_color=color_hex, line_width=3)
                fig.update_layout(margin=dict(l=20, r=20, t=40, b=20), height=350)
                return fig

            col_g1, col_g2 = st.columns(2)

            with col_g1:
                st.plotly_chart(create_bar_chart(df, 'Année_str', 'Poids_kg', "Poids Kg par Année", "#60B4FF"), use_container_width=True)

            with col_g2:
                st.plotly_chart(create_line_chart(df, 'Année_str', 'CA_Ha', "CA/Ha (€) par Année", "#FF4B4B"), use_container_width=True)

            col_g3, col_g4 = st.columns(2)

            with col_g3:
                st.plotly_chart(create_bar_chart(df, 'Année_str', 'Poids_Ha', "Poids/Ha (tonnes/ha)", "#00CC96"), use_container_width=True)

            with col_g4:
                st.plotly_chart(create_line_chart(df, 'Année_str', 'Euro_Hl', "€/Hl par Année", "#AB63FA"), use_container_width=True)

            col_g5, col_g6 = st.columns(2)

            with col_g5:
                df_ca_net = df[df['CA_Net'] > 0]
                if len(df_ca_net) > 0:
                    st.plotly_chart(create_bar_chart(df_ca_net, 'Année_str', 'CA_Net', "Chiffre d'Affaire Net (€)", "#FFA15A"), use_container_width=True)
                else:
                    st.info("Aucune donnée CA Net disponible")

            with col_g6:
                df_rdt = df[df['Rendement_Reel'] > 0]
                if len(df_rdt) > 0:
                    st.plotly_chart(create_line_chart(df_rdt, 'Année_str', 'Rendement_Reel', "Rendement Réel (%)", "#19D3F3"), use_container_width=True)
                else:
                    st.info("Aucune donnée rendement disponible")

# ========================================
# TAB 4 : HISTORIQUE & IMPORT
# ========================================
elif selected_tab == tab_titles[3]:
    st.subheader("📑 Historique & Import Données")

    # Section gestion de l'historique
    st.markdown("### 🗑️ Gestion de l'Historique")

    with st.expander("⚠️ Actions Dangereuses"):
        st.warning("**Attention** : Ces actions sont irréversibles !")

        col_danger1, col_danger2 = st.columns(2)

        with col_danger1:
            st.markdown("**Vider tout l'historique**")
            vider_confirm = st.checkbox("Je confirme vouloir tout supprimer", key="confirm_vider")
            if st.button("🗑️ Vider Tout l'Historique", type="secondary", disabled=not vider_confirm):
                vendanges.vider_historique()
                st.success("✅ Historique complètement vidé")
                st.rerun()

        with col_danger2:
            st.markdown("**Supprimer une campagne**")
            campagnes_existantes = [c['annee'] for c in vendanges.donnees['campagnes']]
            if campagnes_existantes:
                annee_suppr = st.selectbox(
                    "Choisir l'année",
                    campagnes_existantes
                )
                if st.button(f"🗑️ Supprimer {annee_suppr}"):
                    vendanges.supprimer_campagne(annee_suppr)
                    st.success(f"✅ Campagne {annee_suppr} supprimée")
                    st.rerun()

    st.markdown("---")
    st.markdown("### 📥 Import Historique Excel")

    st.info("""
    **Format attendu** : Fichier Excel (.xlsx ou .csv) avec colonnes :
    - Année
    - Poids Kg
    - H° (Hl degré)
    - Prix U
    - Revenus € (ou CA Brut)
    - Chiffre Affaire Net €
    - Total Ha
    - CA / Ha (€)
    - €/hl (72% rdt)
    - Poids/Ha
    - Frais U
    - Prime U
    - rendement jus
    """)

    uploaded_file = st.file_uploader(
        "Choisir un fichier Excel",
        type=['xlsx', 'xls', 'csv'],
        help="Fichier avec historique 2013-2024"
    )

    if uploaded_file:
        try:
            if uploaded_file.name.endswith('.csv'):
                df_import = pd.read_csv(uploaded_file)
            else:
                df_import = pd.read_excel(uploaded_file)

            st.success(f"✅ Fichier chargé : {len(df_import)} lignes")

            st.dataframe(df_import.head(), use_container_width=True)

            if st.button("📥 Importer ces Données", type="primary"):
                vendanges.importer_historique(df_import)
                st.success("✅ Données importées avec succès !")
                st.rerun()

        except Exception as e:
            st.error(f"❌ Erreur lors de l'import : {str(e)}")
            with st.expander("Détails"):
                st.code(traceback.format_exc())

    # Tableau historique complet
    st.markdown("---")
    st.markdown("### 📊 Tableau Historique Complet")

    if vendanges.donnees['campagnes']:
        data_table = []

        for c in sorted(vendanges.donnees['campagnes'], key=lambda x: x['annee'], reverse=True):
            if 'donnees_historiques' in c:
                hist = c['donnees_historiques']

                euro_hl_value = hist.get('euro_hl', 0)
                if euro_hl_value > 1000:
                    euro_hl_value = euro_hl_value / 100

                degre_m = hist.get('degre_moyen')
                if (degre_m is None or degre_m == 0) and hist.get('hl', 0) > 0 and hist.get('poids_kg', 0) > 0:
                    rdt_r = hist.get('rendement_reel', 73)
                    rdt_ratio = (rdt_r / 100) if rdt_r > 1 else (rdt_r if rdt_r > 0 else 0.73)
                    degre_m = (hist.get('hl') * 100) / (hist.get('poids_kg') * rdt_ratio) if rdt_ratio > 0 else 0.0

                data_table.append({
                    'Année': c['annee'],
                    'Poids (kg)': f"{hist.get('poids_kg', 0) or 0:,.0f}",
                    'Degré réel (°)': f"{degre_m:.2f}°" if degre_m else "-",
                    'Hl°': f"{hist.get('hl', 0) or 0:.1f}",
                    'CA Brut (€)': f"{hist.get('ca_brut', 0) or 0:,.0f}",
                    'Prime (€)': f"{hist.get('prime_totale', 0) or 0:,.2f}",
                    'Frais (€)': f"{hist.get('frais_totaux', 0) or 0:,.2f}",
                    'CA Net (€)': f"{hist.get('ca_net', 0) or 0:,.0f}",
                    'Total Ha': f"{hist.get('total_ha', 0) or 0:.2f}",
                    'CA/Ha (€)': f"{hist.get('ca_ha', 0) or 0:,.0f}",
                    'Poids/Ha (t)': f"{hist.get('poids_ha', 0) or 0:.2f}",
                    'Rdt Réel (%)': f"{hist.get('rendement_reel', 0) or 0:.1f}",
                    '€/Hl': f"{euro_hl_value or 0:.2f}",
                    'Status': '✅ Validé'
                })
            else:
                # Afficher aussi les campagnes non validées
                nb_tickets = len(c.get('tickets', []))
                data_table.append({
                    'Année': c['annee'],
                    'Poids (kg)': f"{nb_tickets} tickets",
                    'Degré réel (°)': '-',
                    'Hl°': '-',
                    'CA Brut (€)': '-',
                    'Prime (€)': '-',
                    'Frais (€)': '-',
                    'CA Net (€)': '-',
                    'Total Ha': '-',
                    'CA/Ha (€)': '-',
                    'Poids/Ha (t)': '-',
                    'Rdt Réel (%)': '-',
                    '€/Hl': '-',
                    'Status': '🟡 En cours'
                })

        if data_table:
            df_table = pd.DataFrame(data_table)
            st.dataframe(df_table, use_container_width=True, hide_index=True)

            # Export CSV (seulement campagnes validées)
            df_validees = df_table[df_table['Status'] == '✅ Validé']
            if len(df_validees) > 0:
                csv = df_validees.to_csv(index=False).encode('utf-8')
                st.download_button(
                    label="📥 Télécharger en CSV (campagnes validées)",
                    data=csv,
                    file_name=f"historique_vendanges_{datetime.now().strftime('%Y%m%d')}.csv",
                    mime="text/csv"
                )
        else:
            st.info("📝 Aucune donnée historique disponible")
    else:
        st.info("📝 Aucune campagne disponible. Commencez par saisir des tickets ou importer l'historique.")