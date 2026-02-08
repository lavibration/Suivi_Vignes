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
                'frais_vinif_u': 15.7300,
                'prime_u': 0.0000
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
        """Calcule les totaux d'une campagne"""
        campagne = self.get_campagne(annee)
        if not campagne or not campagne['tickets']:
            return None

        tickets = campagne['tickets']
        poids_total = sum(t['poids_kg'] for t in tickets)

        # Degré moyen pondéré
        if poids_total > 0:
            degre_moyen = sum(t['poids_kg'] * t['degre'] for t in tickets) / poids_total
        else:
            degre_moyen = 0

        # Calculs
        rdt = campagne['parametres']['rendement_theorique'] / 100
        hl_estime = (poids_total * degre_moyen * rdt) / 100

        # Production en litres = rendement % × poids kg
        production_litres = poids_total * rdt

        prix_u = campagne['parametres']['prix_u']
        prime_u = campagne['parametres'].get('prime_u', 0)
        frais_u = campagne['parametres']['frais_vinif_u']

        # Prime € = Prime U (€/kg) × Poids total (kg)
        prime_total = prime_u * poids_total

        # CA brut = (Prix U × Hl°) + Prime totale
        ca_brut = (hl_estime * prix_u) + prime_total

        # Frais € = Frais U (€/kg) × Poids total (kg)
        frais_total = frais_u * poids_total

        revenu_net = ca_brut - frais_total

        # €/L et €/Hl
        euro_par_litre = revenu_net / production_litres if production_litres > 0 else 0
        euro_par_hl = euro_par_litre * 100

        return {
            'nb_tickets': len(tickets),
            'poids_total': poids_total,
            'degre_moyen': degre_moyen,
            'hl_estime': hl_estime,
            'production_litres': production_litres,
            'ca_brut': ca_brut,
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
        """Importe l'historique depuis un DataFrame"""
        for _, row in df.iterrows():
            annee = int(row['Année'])

            if self.get_campagne(annee):
                continue

            campagne = {
                'annee': annee,
                'status': 'validee',
                'tickets': [],
                'parametres': {
                    'rendement_theorique': float(row.get('rendement jus', 73)),
                    'prix_u': float(row.get('Prix U', 100)),
                    'frais_vinif_u': float(row.get('Frais U', 15.73)),
                    'prime_u': float(row.get('Prime U', 0))
                },
                'validation': {
                    'validee': True,
                    'hl_reel': float(row.get('Revenus €', 0)) / float(row.get('Prix U', 100)) if 'Revenus €' in row and float(row.get('Prix U', 100)) != 0 else None,
                    'prix_u_reel': float(row.get('Prix U', 100)),
                    'frais_reels': None,
                    'prime_reelle': float(row.get('Prime €', 0)),
                    'date_validation': f"{annee}-12-31"
                },
                'donnees_historiques': {
                    'poids_kg': float(row.get('Poids Kg', 0)),
                    'hl': float(row.get('H°', 0)) if 'H°' in row else None,
                    'ca_brut': float(row.get('Revenus €', 0)),
                    'ca_net': float(row.get('Chiffre Affaire Net €', 0)),
                    'total_ha': float(row.get('Total Ha', 0)),
                    'ca_ha': float(row.get('CA / Ha (€)', 0)),
                    'euro_hl': float(row.get('€/hl (72% rdt)', 0)),
                    'poids_ha': float(row.get('Poids/Ha', 0)),
                    'rendement_reel': float(row.get('rendement jus', 73))
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

# Onglets principaux
tab1, tab2, tab3, tab4 = st.tabs([
    "📝 Saisie Tickets",
    "📊 Suivi Campagnes",
    "📈 Dashboard",
    "📑 Historique & Import"
])

# ========================================
# TAB 1 : SAISIE TICKETS
# ========================================
with tab1:
    st.subheader("📝 Saisie des Tickets de Vendange")

    st.info(f"💡 Les tickets sont automatiquement affectés à la campagne correspondant à leur date.")

    col_form, col_preview = st.columns([2, 1])

    with col_form:
        with st.form("form_ticket", clear_on_submit=True):
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

                degre = st.number_input(
                    "🌡️ Degré (%)",
                    min_value=0.0,
                    max_value=20.0,
                    value=12.0,
                    step=0.1,
                    format="%.1f",
                    help="Degré mesuré"
                )

            notes = st.text_area(
                "📝 Notes (optionnel)",
                placeholder="Qualité, tri, observations...",
                height=80
            )

            submitted = st.form_submit_button("✅ Enregistrer le Ticket", type="primary", use_container_width=True)

            if submitted:
                if poids > 0 and degre > 0:
                    annee_ticket = date_vendange.year

                    ticket = {
                        'date': date_vendange.strftime('%Y-%m-%d'),
                        'num_ticket': num_ticket if num_ticket else f"T{date_vendange.strftime('%Y%m%d')}",
                        'poids_kg': poids,
                        'degre': degre,
                        'notes': notes
                    }

                    success, message = vendanges.ajouter_ticket(date_vendange.strftime('%Y-%m-%d'), ticket)

                    if success:
                        st.success(f"{message} : {poids} kg à {degre}°")
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
            st.metric("Degré Moyen", f"{totaux['degre_moyen'] or 0:.1f}°")
            st.metric("Hl° Estimé", f"{totaux['hl_estime'] or 0:.1f}")
        else:
            st.info("Aucun ticket saisi")

    # Liste des tickets de la campagne active
    st.markdown("---")
    st.subheader(f"🎫 Tickets de la Campagne {annee_active}")

    if campagne_active['tickets']:
        df_tickets = pd.DataFrame(campagne_active['tickets'])
        df_tickets['date'] = pd.to_datetime(df_tickets['date']).dt.strftime('%d/%m/%Y')

        cols = ['date', 'num_ticket', 'poids_kg', 'degre', 'notes', 'id']
        df_display = df_tickets[[c for c in cols if c in df_tickets.columns]]
        df_display.columns = ['Date', 'N° Ticket', 'Poids (kg)', 'Degré (°)', 'Notes', 'ID']

        st.dataframe(
            df_display.drop(columns=['ID']),
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
with tab2:
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

            # Indicateurs principaux
            totaux = vendanges.calculer_totaux(annee_selectionnee)

            col1, col2, col3, col4 = st.columns(4)

            with col1:
                st.metric("🏋️ Poids Total", f"{totaux['poids_total'] or 0:,.0f} kg")

            with col2:
                st.metric("🌡️ Degré Moyen", f"{totaux['degre_moyen'] or 0:.2f}°")

            with col3:
                st.metric("🍷 Hl° Estimé", f"{totaux['hl_estime'] or 0:.1f}")

            with col4:
                surf_campagne = campagne.get('surface_vendangee', {}).get('total_ha', surface_totale)
                poids_ha = totaux['poids_total'] / surf_campagne if surf_campagne > 0 else 0
                st.metric("📏 Poids/Ha", f"{poids_ha or 0:,.0f} kg/ha")

            st.markdown("---")

            # Paramètres et calculs financiers
            st.subheader("💰 Paramètres et Calculs Financiers")

            col_param1, col_param2 = st.columns(2)

            with col_param1:
                st.markdown("**Paramètres**")

                rdt_theo = st.number_input(
                    "Rendement théorique (%)",
                    min_value=60.0,
                    max_value=80.0,
                    value=campagne['parametres']['rendement_theorique'],
                    step=0.1,
                    format="%.1f",
                    key=f"rdt_theo_{annee_selectionnee}",
                    disabled=campagne['validation']['validee']
                )

                prix_u = st.number_input(
                    "Prix U (€/Hl°)",
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
                    if st.button("💾 Sauvegarder Paramètres"):
                        campagne['parametres']['rendement_theorique'] = rdt_theo
                        campagne['parametres']['prix_u'] = prix_u
                        campagne['parametres']['prime_u'] = prime_u
                        campagne['parametres']['frais_vinif_u'] = frais_u
                        vendanges.sauvegarder()
                        st.success("✅ Paramètres sauvegardés")
                        st.rerun()

            with col_param2:
                st.markdown("**Résultats Financiers (Estimation)**")

                # Recalculer avec params actuels
                hl_calc = (totaux['poids_total'] * totaux['degre_moyen'] * (rdt_theo/100)) / 100
                production_litres = totaux['poids_total'] * (rdt_theo/100)

                prime_calc = prime_u * totaux['poids_total']
                ca_brut = (hl_calc * prix_u) + prime_calc
                frais_total = frais_u * totaux['poids_total']
                revenu_net = ca_brut - frais_total

                euro_par_litre = revenu_net / production_litres if production_litres > 0 else 0
                euro_par_hl = euro_par_litre * 100

                surface_ha = campagne.get('surface_vendangee', {}).get('total_ha', surface_totale)
                ca_ha = ca_brut / surface_ha if surface_ha > 0 else 0

                st.metric("Hl° (recalculé)", f"{hl_calc:.1f}")
                st.metric("Production Litres", f"{production_litres or 0:,.0f} L")
                st.metric("Prime Totale", f"{prime_calc:,.2f} €")
                st.metric("CA Brut", f"{ca_brut or 0:,.0f} €")
                st.metric("Frais Vinification", f"{frais_total or 0:,.0f} €")
                st.metric("**Revenu Net**", f"**{revenu_net:,.0f} €**")

                col_ind1, col_ind2 = st.columns(2)
                with col_ind1:
                    st.metric("CA/Ha", f"{ca_ha or 0:,.0f} €/ha")
                    st.metric("€/Litre", f"{euro_par_litre or 0:.2f} €/L")
                with col_ind2:
                    st.metric("€/Hl", f"{euro_par_hl:.0f} €/Hl")

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
with tab3:
    st.subheader("📈 Dashboard Historique")

    # Bouton rafraîchir
    if st.button("🔄 Actualiser Dashboard"):
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
            if euro_hl_value > 1000:  # Si > 1000, c'est probablement une erreur (devrait être < 200)
                euro_hl_value = euro_hl_value / 100

            data.append({
                'Année': c['annee'],
                'Poids_kg': hist.get('poids_kg', 0),
                'Total_Ha': hist.get('total_ha', surface_totale),
                'Poids_Ha': hist.get('poids_ha', 0),
                'CA_Ha': hist.get('ca_ha', 0),
                'Euro_Hl': euro_hl_value,
                'CA_Net': hist.get('ca_net', 0),
                'Rendement_Reel': hist.get('rendement_reel', 0)
            })

        df = pd.DataFrame(data).sort_values('Année')

        # Forcer l'année en string pour affichage correct
        df['Année_str'] = df['Année'].astype(str)

        if len(df) > 0:
            col_g1, col_g2 = st.columns(2)

            with col_g1:
                st.markdown("**Poids Kg par Année**")
                st.bar_chart(df.set_index('Année_str')['Poids_kg'])

            with col_g2:
                st.markdown("**CA/Ha (€)**")
                st.line_chart(df.set_index('Année_str')['CA_Ha'])

            col_g3, col_g4 = st.columns(2)

            with col_g3:
                st.markdown("**Poids/Ha (tonnes/ha)**")
                st.bar_chart(df.set_index('Année_str')['Poids_Ha'])

            with col_g4:
                st.markdown("**€/Hl**")
                st.line_chart(df.set_index('Année_str')['Euro_Hl'])

            col_g5, col_g6 = st.columns(2)

            with col_g5:
                st.markdown("**Chiffre d'Affaire Net (€)**")
                df_ca_net = df[df['CA_Net'] > 0]
                if len(df_ca_net) > 0:
                    st.bar_chart(df_ca_net.set_index('Année_str')['CA_Net'])
                else:
                    st.info("Aucune donnée CA Net disponible")

            with col_g6:
                st.markdown("**Rendement Réel (%)**")
                df_rdt = df[df['Rendement_Reel'] > 0]
                if len(df_rdt) > 0:
                    st.line_chart(df_rdt.set_index('Année_str')['Rendement_Reel'])
                else:
                    st.info("Aucune donnée rendement disponible")

# ========================================
# TAB 4 : HISTORIQUE & IMPORT
# ========================================
with tab4:
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

                # CORRECTION : Si euro_hl semble être 100x trop grand, on corrige
                euro_hl_value = hist.get('euro_hl', 0)
                if euro_hl_value > 1000:
                    euro_hl_value = euro_hl_value / 100

                def fmt_num(val, format_str):
                    try:
                        if val is None or val != val: return "-"
                        return format_str % float(val)
                    except: return "-"

                data_table.append({
                    'Année': c['annee'],
                    'Poids (kg)': f"{hist.get('poids_kg', 0) or 0:,.0f}",
                    'Hl°': f"{hist.get('hl', 0) or 0:.1f}",
                    'CA Brut (€)': f"{hist.get('ca_brut', 0) or 0:,.0f}",
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
                    'Hl°': '-',
                    'CA Brut (€)': '-',
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