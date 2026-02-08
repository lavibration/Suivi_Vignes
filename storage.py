import streamlit as st
import pandas as pd
import json
import os
from datetime import datetime

try:
    from streamlit_gsheets import GSheetsConnection
    GSHEETS_AVAILABLE = True
except ImportError:
    GSHEETS_AVAILABLE = False

class DataManager:
    """Gestionnaire de données supportant JSON local et Google Sheets."""

    def __init__(self):
        self.use_gsheets = False
        if GSHEETS_AVAILABLE:
            if self._is_gsheets_configured():
                try:
                    self.conn = st.connection("gsheets", type=GSheetsConnection)
                    self.use_gsheets = True
                except Exception as e:
                    st.warning(f"Impossible de se connecter à Google Sheets, repli sur JSON: {e}")

        self.script_dir = os.path.dirname(os.path.abspath(__file__))

    def _is_gsheets_configured(self):
        """Vérifie si les secrets pour Google Sheets sont présents."""
        try:
            return "connections" in st.secrets and "gsheets" in st.secrets["connections"]
        except Exception:
            return False

    def load_data(self, key, default_factory=dict):
        """Charge les données pour une clé donnée (ex: 'traitements')."""
        json_file = os.path.join(self.script_dir, f"{key}.json")

        if self.use_gsheets:
            try:
                # Mapping des clés vers les noms d'onglets
                tab_name = self._get_tab_name(key)
                df = self.conn.read(worksheet=tab_name)
                if df is not None and not df.empty:
                    return self._df_to_json(key, df)
            except Exception as e:
                st.error(f"Erreur lors du chargement de '{key}' depuis GSheets: {e}")
                # Fallback sur JSON

        # Fallback JSON
        if os.path.exists(json_file):
            try:
                with open(json_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                st.error(f"Erreur lors du chargement de {json_file}: {e}")

        return default_factory()

    def save_data(self, key, data):
        """Sauvegarde les données pour une clé donnée."""
        # Toujours sauvegarder en local JSON par sécurité/cache
        json_file = os.path.join(self.script_dir, f"{key}.json")
        try:
            with open(json_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            st.error(f"Erreur lors de la sauvegarde locale de {key}: {e}")

        if self.use_gsheets:
            try:
                tab_name = self._get_tab_name(key)
                df = self._json_to_df(key, data)
                self.conn.update(worksheet=tab_name, data=df)
            except Exception as e:
                st.error(f"Erreur lors de la sauvegarde de '{key}' vers GSheets: {e}")

    def _get_tab_name(self, key):
        mapping = {
            'traitements': 'traitements',
            'meteo_historique': 'meteo',
            'historique_alertes': 'alertes',
            'gdd_historique': 'gdd',
            'vendanges': 'vendanges',
            'config_vignoble': 'config'
        }
        return mapping.get(key, key)

    def _df_to_json(self, key, df):
        """Convertit un DataFrame GSheets en structure JSON."""
        if df.empty:
            return self._get_default_for_key(key)

        # Nettoyage des colonnes Unnamed (souvent présentes dans GSheets vides)
        df = df.loc[:, ~df.columns.str.contains('^Unnamed')]

        if key == 'traitements':
            return {'traitements': df.to_dict(orient='records')}

        elif key == 'meteo_historique':
            if 'date' in df.columns:
                df = df.set_index('date')
            return df.to_dict(orient='index')

        elif key == 'gdd_historique':
            if 'date' in df.columns and 'value' in df.columns:
                return dict(zip(df['date'], df['value']))
            return {}

        elif key == 'historique_alertes':
            campagnes = []
            if 'annee' in df.columns:
                for annee, group in df.groupby('annee'):
                    analyses = group.drop(columns=['annee']).to_dict(orient='records')
                    for a in analyses:
                        for subkey in ['risque_mildiou', 'risque_oidium', 'protection', 'decision', 'meteo', 'previsions']:
                            if subkey in a and isinstance(a[subkey], str) and a[subkey].strip().startswith('{'):
                                try:
                                    a[subkey] = json.loads(a[subkey])
                                except:
                                    pass
                    campagnes.append({'annee': int(annee), 'analyses': analyses})
            return {'campagnes': campagnes}

        elif key == 'vendanges':
            campagnes = []
            if 'annee' in df.columns:
                for annee, group in df.groupby('annee'):
                    rows = group.to_dict(orient='records')
                    tickets = [r for r in rows if r.get('type') == 'TICKET']
                    params_rows = [r for r in rows if r.get('type') == 'CAMPAGNE']

                    # Nettoyage des tickets (enlever les colonnes nulles de campagne)
                    clean_tickets = []
                    for t in tickets:
                        clean_t = {k: v for k, v in t.items() if v == v and v is not None} # remove NaN
                        if 'type' in clean_t: del clean_t['type']
                        if 'annee' in clean_t: del clean_t['annee']
                        clean_tickets.append(clean_t)

                    campagne = {'annee': int(annee), 'tickets': clean_tickets}
                    if params_rows:
                        p = params_rows[0]
                        campagne['status'] = p.get('status', 'en_cours')
                        campagne['parametres'] = {
                            'rendement_theorique': p.get('rdt_theo', 73.0),
                            'prix_u': p.get('prix_u', 100.0),
                            'prime_u': p.get('prime_u', 0.0),
                            'frais_vinif_u': p.get('frais_vinif_u', 15.73)
                        }
                        campagne['surface_vendangee'] = {
                            'total_ha': p.get('total_ha', 2.05),
                            'notes': p.get('notes_surface', '')
                        }
                        campagne['validation'] = {
                            'validee': bool(p.get('validee', False)),
                            'hl_reel': p.get('hl_reel'),
                            'prix_u_reel': p.get('prix_u_reel'),
                            'prime_reelle': p.get('prime_reelle'),
                            'frais_reels': p.get('frais_reels'),
                            'date_validation': p.get('date_validation')
                        }
                        if p.get('validee'):
                             campagne['donnees_historiques'] = {
                                'poids_kg': p.get('poids_kg_hist'),
                                'hl': p.get('hl_hist'),
                                'ca_brut': p.get('ca_brut_hist'),
                                'ca_net': p.get('ca_net_hist'),
                                'total_ha': p.get('total_ha_hist'),
                                'euro_hl': p.get('euro_hl_hist'),
                                'poids_ha': p.get('poids_ha_hist'),
                                'rendement_reel': p.get('rendement_reel_hist')
                             }
                    campagnes.append(campagne)
            return {'campagnes': campagnes}

        return df.to_dict(orient='records')

    def _json_to_df(self, key, data):
        """Convertit une structure JSON en DataFrame pour GSheets."""
        if key == 'traitements':
            return pd.DataFrame(data.get('traitements', []))

        elif key == 'meteo_historique':
            rows = []
            for date, values in data.items():
                row = {'date': date}
                row.update(values)
                rows.append(row)
            return pd.DataFrame(rows)

        elif key == 'gdd_historique':
            rows = [{'date': k, 'value': v} for k, v in data.items()]
            return pd.DataFrame(rows)

        elif key == 'historique_alertes':
            rows = []
            for campagne in data.get('campagnes', []):
                annee = campagne['annee']
                for analyse in campagne['analyses']:
                    row = {'annee': annee}
                    for k, v in analyse.items():
                        if isinstance(v, dict):
                            row[k] = json.dumps(v, ensure_ascii=False)
                        else:
                            row[k] = v
                    rows.append(row)
            return pd.DataFrame(rows)

        elif key == 'vendanges':
            rows = []
            for campagne in data.get('campagnes', []):
                annee = campagne['annee']
                p = campagne.get('parametres', {})
                s = campagne.get('surface_vendangee', {})
                v = campagne.get('validation', {})
                h = campagne.get('donnees_historiques', {})

                camp_row = {
                    'annee': annee, 'type': 'CAMPAGNE',
                    'status': campagne.get('status'),
                    'rdt_theo': p.get('rendement_theorique'),
                    'prix_u': p.get('prix_u'),
                    'prime_u': p.get('prime_u'),
                    'frais_vinif_u': p.get('frais_vinif_u'),
                    'total_ha': s.get('total_ha'),
                    'notes_surface': s.get('notes'),
                    'validee': v.get('validee'),
                    'hl_reel': v.get('hl_reel'),
                    'prix_u_reel': v.get('prix_u_reel'),
                    'prime_reelle': v.get('prime_reelle'),
                    'frais_reels': v.get('frais_reels'),
                    'date_validation': v.get('date_validation'),
                    'poids_kg_hist': h.get('poids_kg'),
                    'hl_hist': h.get('hl'),
                    'ca_brut_hist': h.get('ca_brut'),
                    'ca_net_hist': h.get('ca_net'),
                    'total_ha_hist': h.get('total_ha'),
                    'euro_hl_hist': h.get('euro_hl'),
                    'poids_ha_hist': h.get('poids_ha'),
                    'rendement_reel_hist': h.get('rendement_reel')
                }
                rows.append(camp_row)

                for ticket in campagne.get('tickets', []):
                    t_row = {'annee': annee, 'type': 'TICKET'}
                    t_row.update(ticket)
                    rows.append(t_row)
            return pd.DataFrame(rows)

        return pd.DataFrame(data)

    def _get_default_for_key(self, key):
        defaults = {
            'traitements': {'traitements': []},
            'meteo_historique': {},
            'historique_alertes': {'campagnes': []},
            'gdd_historique': {},
            'vendanges': {'campagnes': []}
        }
        return defaults.get(key, {})
