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

    def _load_local_json(self, filepath, default_factory):
        if os.path.exists(filepath):
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    content = f.read()
                    # Fix potential NaN in JSON
                    content = content.replace(': NaN', ': null').replace(': nan', ': null')
                    return json.loads(content)
            except Exception as e:
                st.error(f"Erreur lors du chargement de {filepath}: {e}")
        return default_factory()

    def load_data(self, key, default_factory=dict):
        """Charge les données pour une clé donnée."""
        json_file = os.path.join(self.script_dir, f"{key}.json")

        if self.use_gsheets:
            try:
                tab_name = self._get_tab_name(key)
                df = self.conn.read(worksheet=tab_name)

                # Check if empty
                is_empty = df is None or len(df) == 0 or (len(df.columns) > 0 and all(df.columns.str.contains('^Unnamed')))

                if not is_empty and key in ['traitements', 'vendanges', 'historique_alertes', 'meteo_historique', 'gdd_historique']:
                    mandatory = {'traitements': 'parcelle', 'vendanges': 'annee', 'historique_alertes': 'annee', 'meteo_historique': 'date', 'gdd_historique': 'date'}
                    if mandatory[key] not in df.columns:
                        is_empty = True

                if not is_empty:
                    return self._df_to_json(key, df)
                else:
                    if os.path.exists(json_file):
                        local_data = self._load_local_json(json_file, default_factory)
                        if local_data and (isinstance(local_data, dict) and (local_data.get('campagnes') or local_data.get('traitements') or len(local_data) > 0)):
                            st.info(f"Migration automatique de '{key}' vers Google Sheets...")
                            self.save_data(key, local_data)
                            return local_data
            except Exception as e:
                st.error(f"Erreur lors du chargement de '{key}' depuis GSheets: {e}")

        return self._load_local_json(json_file, default_factory)

    def save_data(self, key, data):
        """Sauvegarde les données."""
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
            'config_vignoble': 'config',
            'produits': 'produits',
            'fertilisation': 'fertilisation'
        }
        return mapping.get(key, key)

    def _to_bool(self, val):
        if isinstance(val, bool): return val
        if isinstance(val, str): return val.lower() in ('true', '1', 'yes', 'vrai', 't')
        if val == val and val is not None: return bool(val)
        return False

    def _get_num(self, val, default=0.0):
        try:
            if val is None or val != val: return default
            if isinstance(val, str):
                # Gérer les décimales à la française (virgule)
                val = val.replace(',', '.')
            return float(val)
        except: return default

    def _df_to_json(self, key, df):
        """Convertit un DataFrame GSheets en structure JSON."""
        if df is None or df.empty:
            return self._get_default_for_key(key)

        df = df.loc[:, ~df.columns.str.contains('^Unnamed')]

        if key == 'produits':
            return {'produits': df.to_dict(orient='records')}

        if key == 'fertilisation':
            return {'apports': df.to_dict(orient='records')}

        if key == 'traitements':
            recs = df.to_dict(orient='records')
            for r in recs:
                if 'caracteristiques' in r and isinstance(r['caracteristiques'], str) and r['caracteristiques'].startswith('{'):
                    try: r['caracteristiques'] = json.loads(r['caracteristiques'])
                    except: pass
                # Coercion numérique pour les nouveaux champs
                if 'mouillage_pct' in r: r['mouillage_pct'] = self._get_num(r['mouillage_pct'], 100.0)
                if 'surface_traitee' in r: r['surface_traitee'] = self._get_num(r['surface_traitee'], 0.0)
                if 'dose_kg_ha' in r: r['dose_kg_ha'] = self._get_num(r['dose_kg_ha'], 0.0)
            return {'traitements': recs}

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
                df['annee'] = pd.to_numeric(df['annee'], errors='coerce')
                df = df.dropna(subset=['annee'])
                for annee, group in df.groupby('annee'):
                    analyses = group.drop(columns=['annee']).to_dict(orient='records')
                    for a in analyses:
                        for subkey in ['risque_mildiou', 'risque_oidium', 'protection', 'decision', 'meteo', 'previsions']:
                            if subkey in a and isinstance(a[subkey], str) and a[subkey].strip().startswith('{'):
                                try: a[subkey] = json.loads(a[subkey])
                                except: pass
                    campagnes.append({'annee': int(annee), 'analyses': analyses})
            return {'campagnes': campagnes}

        elif key == 'vendanges':
            campagnes = []
            if 'annee' in df.columns:
                df['annee'] = pd.to_numeric(df['annee'], errors='coerce')
                df = df.dropna(subset=['annee'])
                for annee, group in df.groupby('annee'):
                    rows = group.to_dict(orient='records')
                    tickets_rows = [r for r in rows if r.get('type') == 'TICKET']
                    params_rows = [r for r in rows if r.get('type') == 'CAMPAGNE']

                    clean_tickets = []
                    for t in tickets_rows:
                        clean_t = {
                            'date': t.get('date'),
                            'num_ticket': t.get('num_ticket'),
                            'poids_kg': self._get_num(t.get('poids_kg')),
                            'degre': self._get_num(t.get('degre')),
                            'notes': t.get('notes', ''),
                            'id': self._get_num(t.get('id'))
                        }
                        clean_tickets.append(clean_t)

                    campagne = {'annee': int(annee), 'tickets': clean_tickets}
                    if params_rows:
                        p = params_rows[0]
                        campagne['status'] = p.get('status', 'en_cours')
                        campagne['parametres'] = {
                            'rendement_theorique': self._get_num(p.get('rdt_theo'), 73.0),
                            'prix_u': self._get_num(p.get('prix_u'), 100.0),
                            'prime_u': self._get_num(p.get('prime_u'), 0.0),
                            'frais_vinif_u': self._get_num(p.get('frais_vinif_u'), 15.73)
                        }
                        campagne['surface_vendangee'] = {
                            'total_ha': self._get_num(p.get('total_ha'), 2.05),
                            'notes': p.get('notes_surface', '')
                        }
                        campagne['validation'] = {
                            'validee': self._to_bool(p.get('validee')),
                            'hl_reel': self._get_num(p.get('hl_reel')),
                            'prix_u_reel': self._get_num(p.get('prix_u_reel')),
                            'prime_reelle': self._get_num(p.get('prime_reelle')),
                            'frais_reels': self._get_num(p.get('frais_reels')),
                            'date_validation': p.get('date_validation')
                        }
                        if campagne['validation']['validee']:
                             campagne['donnees_historiques'] = {
                                'poids_kg': self._get_num(p.get('poids_kg_hist')),
                                'hl': self._get_num(p.get('hl_hist')),
                                'ca_brut': self._get_num(p.get('ca_brut_hist')),
                                'ca_net': self._get_num(p.get('ca_net_hist')),
                                'total_ha': self._get_num(p.get('total_ha_hist')),
                                'euro_hl': self._get_num(p.get('euro_hl_hist')),
                                'poids_ha': self._get_num(p.get('poids_ha_hist')),
                                'rendement_reel': self._get_num(p.get('rendement_reel_hist'))
                             }
                    campagnes.append(campagne)
            return {'campagnes': campagnes}

        elif key == 'config_vignoble':
            if 'json_content' in df.columns and not df.empty:
                try: return json.loads(df.iloc[0]['json_content'])
                except: return self._get_default_for_key(key)

        return df.to_dict(orient='records')

    def _json_to_df(self, key, data):
        """Convertit une structure JSON en DataFrame pour GSheets."""
        if not data: return pd.DataFrame()

        if key == 'produits':
            return pd.DataFrame(data.get('produits', []))

        if key == 'fertilisation':
            return pd.DataFrame(data.get('apports', []))

        if key == 'traitements':
            rows = []
            for t in data.get('traitements', []):
                row = t.copy()
                if 'caracteristiques' in row and isinstance(row['caracteristiques'], dict):
                    row['caracteristiques'] = json.dumps(row['caracteristiques'], ensure_ascii=False)
                rows.append(row)
            return pd.DataFrame(rows)

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
                        if isinstance(v, (dict, list)):
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

        elif key == 'config_vignoble':
            return pd.DataFrame([{'json_content': json.dumps(data, ensure_ascii=False)}])

        return pd.DataFrame(data)

    def _get_default_for_key(self, key):
        defaults = {
            'traitements': {'traitements': []},
            'meteo_historique': {},
            'historique_alertes': {'campagnes': []},
            'gdd_historique': {},
            'vendanges': {'campagnes': []},
            'config_vignoble': {},
            'produits': {'produits': []},
            'fertilisation': {'apports': []}
        }
        return defaults.get(key, {})
