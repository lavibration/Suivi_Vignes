"""
Système de prévision et aide à la décision pour le traitement du mildiou
Version finale complète avec :
- Modèles Simple + IPI + Oïdium
- GDD (DJC) avec Biofix manuel
- Persistance de l'historique météo (Pluie, T°, ETP)
- Bilan Hydrique Avancé (ETc, Kc calendrier)
- MODIFIÉ : Correction majeure du bug de persistance météo (RFU à 100%)
- MODIFIÉ : Ajout d'un mode debug avancé pour le Bilan Hydrique
"""

import json
import csv
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
import requests
import os
from storage import DataManager

# Bibliothèques optionnelles pour graphiques
try:
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates

    GRAPHIQUES_DISPONIBLES = True
except ImportError:
    GRAPHIQUES_DISPONIBLES = False
    # print("⚠️  matplotlib non installé - Graphiques désactivés")
    # print("   Pour activer : pip install matplotlib")


class ConfigVignoble:
    """Configuration du vignoble"""

    SENSIBILITES_CEPAGES = {
        'Chardonnay': 7, 'Cabernet Sauvignon': 6, 'Merlot': 7,
        'Grenache': 5, 'Syrah': 6, 'Pinot Noir': 8,
        'Sauvignon': 7, 'Carignan': 4, 'Mourvèdre': 5,
        'Cinsault': 5, 'Ugni Blanc': 6, 'Viognier': 6,
        'Caladoc': 6
    }
    COEF_STADES = {
        'repos': 0.0,
        'debourrement': 0.8,
        'pousse_10cm': 1.5,
        'pre_floraison': 1.8,
        'floraison': 2.0,
        'nouaison': 1.8,
        'fermeture_grappe': 1.5,
        'veraison': 0.7,
        'maturation': 0.3
    }

    def __init__(self, config_file: str = 'config_vignoble'):
        self.config_key = config_file.replace('.json', '')
        self.storage = DataManager()
        self.load_config()

    def load_config(self):
        """Charge la configuration via le DataManager"""
        config = self.storage.load_data(self.config_key, default_factory=None)

        if config:
            self.latitude = config['latitude']
            self.longitude = config['longitude']
            for p in config['parcelles']:
                if 'date_debourrement' not in p:
                    p['date_debourrement'] = None
                if 'rfu_max_mm' not in p:
                    p['rfu_max_mm'] = config.get('parametres', {}).get('rfu_max_mm_default', 100.0)
                if 'objectif_rdt' not in p:
                    p['objectif_rdt'] = 50.0 # hl/ha par défaut
                if 'broyage_sarments' not in p:
                    p['broyage_sarments'] = False

            self.parcelles = config['parcelles']

            default_params = self.get_default_parameters()
            self.parametres = config.get('parametres', default_params)
            for key, value in default_params.items():
                if key not in self.parametres:
                    self.parametres[key] = value

            self.surface_totale = sum(p['surface_ha'] for p in self.parcelles)

            # Charger les coefficients d'exportation depuis l'onglet dédié
            self.export_coefs = self.storage.load_data('besoins', default_factory=dict)
            if not self.export_coefs:
                # Fallback sur les paramètres si l'onglet est vide
                self.export_coefs = self.parametres.get('export_coefs', {})

            print(f"✅ Configuration chargée via DataManager")
        else:
            print(f"⚠️ Configuration non trouvée. Création par défaut.")
            self.create_default_config()

    def get_default_parameters(self):
        """Retourne les paramètres par défaut pour GDD et Bilan Hydrique"""
        default_export = {'n': 1.0, 'p': 0.4, 'k': 1.3, 'mgo': 0.2}
        return {
            "t_base_gdd": 10.0,
            "f_runoff": 0.1,
            "i_const_mm": 1.0,
            "rfu_max_mm_default": 100.0,  # RFU Max globale par défaut
            "kc_calendrier": {
                "1": 0.1, "2": 0.1, "3": 0.2,
                "4": 0.4,
                "5": 0.7,
                "6": 0.8,
                "7": 0.8,
                "8": 0.7,  # Kc pour Août
                "9": 0.6,  # Kc pour Septembre
                "10": 0.4,
                "11": 0.2, "12": 0.1
            },
            "export_coefs": {
                cepage: default_export.copy() for cepage in self.SENSIBILITES_CEPAGES
            }
        }

    def create_default_config(self):
        """Crée une configuration par défaut"""
        config = {
            "latitude": 43.21,
            "longitude": 5.54,
            "localisation": "Cassis, France",
            "parcelles": [
                {
                    "nom": "Parcelle 1", "surface_ha": 1.5, "cepages": ["Grenache", "Syrah"],
                    "stade_actuel": "repos", "date_debourrement": None, "rfu_max_mm": 100.0,
                    "objectif_rdt": 50.0, "broyage_sarments": True
                },
                {
                    "nom": "Parcelle 2", "surface_ha": 1.5, "cepages": ["Mourvèdre"],
                    "stade_actuel": "repos", "date_debourrement": None, "rfu_max_mm": 100.0,
                    "objectif_rdt": 50.0, "broyage_sarments": True
                }
            ],
            "parametres": self.get_default_parameters()
        }
        self.storage.save_data(self.config_key, config)
        self.load_config()  # Recharger après création

    def sauvegarder_config(self):
        """Sauvegarde la configuration actuelle via le DataManager"""
        config_a_sauver = {
            "latitude": self.latitude,
            "longitude": self.longitude,
            "parcelles": self.parcelles,
            "parametres": self.parametres
        }
        # Tenter de garder la localisation si elle existe
        current_config = self.storage.load_data(self.config_key)
        if 'localisation' in current_config:
            config_a_sauver['localisation'] = current_config['localisation']

        self.storage.save_data(self.config_key, config_a_sauver)

    def update_parcelle_stade_et_date(self, nom_parcelle: str, nouveau_stade: str,
                                      date_debourrement: Optional[str] = None) -> bool:
        """Met à jour le stade phénologique et enregistre la date manuelle de débourrement."""
        if nouveau_stade not in self.COEF_STADES:
            print(f"⚠️ Stade '{nouveau_stade}' inconnu. Mise à jour annulée.")
            return False

        for parcelle in self.parcelles:
            if parcelle['nom'] == nom_parcelle:
                parcelle['stade_actuel'] = nouveau_stade
                if nouveau_stade == 'debourrement' and date_debourrement:
                    parcelle['date_debourrement'] = date_debourrement
                    print(
                        f"✅ Date de débourrement (biofix GDD) enregistrée pour '{parcelle['nom']}' : {date_debourrement}")
                elif nouveau_stade == 'repos':
                    parcelle['date_debourrement'] = None
                self.sauvegarder_config()
                return True

        print(f"❌ Parcelle '{nom_parcelle}' non trouvée.")
        return False


class MeteoAPI:
    """Gestion des données météorologiques via Open-Meteo (gratuit)"""

    def __init__(self, latitude: float, longitude: float):
        self.latitude = latitude
        self.longitude = longitude
        self.base_url = "https://api.open-meteo.com/v1/forecast"

    def get_meteo_data(self, days_past: int = 14, days_future: int = 7) -> Dict:
        """
        Récupère les données météo passées (max 90j) et futures.
        Demande l'ETP Penman-Monteith (et0_fao_evapotranspiration).
        """

        if days_past > 90:
            days_past_api = 90
        else:
            days_past_api = days_past

        params = {
            'latitude': self.latitude,
            'longitude': self.longitude,
            'daily': 'temperature_2m_max,temperature_2m_min,precipitation_sum,relative_humidity_2m_mean,et0_fao_evapotranspiration',
            'timezone': 'Europe/Paris',
            'past_days': days_past_api,
            'forecast_days': days_future
        }

        try:
            response = requests.get(self.base_url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            return self._format_meteo_data(data)

        except requests.RequestException as e:
            print(f"❌ Erreur lors de la récupération des données météo: {e}")
            return {}

    def _format_meteo_data(self, raw_data: Dict) -> Dict:
        """Formate les données brutes de l'API"""
        daily = raw_data.get('daily', {})
        formatted = {}

        if 'time' not in daily:
            return {}  # Pas de données

        for i, date in enumerate(daily.get('time', [])):
            temp_max = daily['temperature_2m_max'][i]
            temp_min = daily['temperature_2m_min'][i]

            temp_moy = 0.0
            if temp_max is not None and temp_min is not None:
                temp_moy = (temp_max + temp_min) / 2
            elif temp_max is not None:
                temp_moy = temp_max
            elif temp_min is not None:
                temp_moy = temp_min

            formatted[date] = {
                'temp_max': temp_max,
                'temp_min': temp_min,
                'temp_moy': temp_moy,
                'precipitation': daily['precipitation_sum'][i],
                'humidite': daily['relative_humidity_2m_mean'][i],
                'etp0': daily['et0_fao_evapotranspiration'][i]  # Renommé en etp0
            }

        return formatted


class ModeleSimple:
    """Modèle simplifié basé sur la règle des 3-10 améliorée"""

    @staticmethod
    def calculer_risque_infection(meteo_48h: List[Dict], stade_coef: float,
                                  sensibilite_cepage: float) -> Tuple[float, str]:
        if not meteo_48h:
            return 0.0, "FAIBLE"
        pluie_totale = sum(m.get('precipitation', 0) for m in meteo_48h if m)
        jours_humides = [m for m in meteo_48h if m and m.get('precipitation', 0) > 1]
        temp_moy_list = [m.get('temp_moy') for m in meteo_48h if m and m.get('temp_moy') is not None]
        if not temp_moy_list: return 0.0, "FAIBLE"
        if jours_humides:
            temp_moy = sum(m['temp_moy'] for m in jours_humides) / len(jours_humides)
        else:
            temp_moy = sum(temp_moy_list) / len(temp_moy_list)
        score_base = 0
        if pluie_totale >= 10:
            score_base += 5
        elif pluie_totale >= 5:
            score_base += 3
        elif pluie_totale >= 2:
            score_base += 1
        if 20 <= temp_moy <= 25:
            score_base += 4
        elif 15 <= temp_moy <= 28:
            score_base += 2
        elif 10 <= temp_moy <= 30:
            score_base += 1
        humid_moy_list = [m.get('humidite') for m in meteo_48h if m and m.get('humidite') is not None]
        if not humid_moy_list: return 0.0, "FAIBLE"
        humid_moy = sum(humid_moy_list) / len(humid_moy_list)
        if humid_moy > 85: score_base += 1
        score_final = score_base * stade_coef * (sensibilite_cepage / 5)
        score_final = min(10, score_final)
        if score_final >= 7:
            niveau = "FORT"
        elif score_final >= 4:
            niveau = "MOYEN"
        else:
            niveau = "FAIBLE"
        return round(score_final, 1), niveau


class ModeleIPI:
    """Modèle IPI (Indice Potentiel d'Infection)"""
    IPI_TABLE = {
        10: {6: 10, 9: 20, 12: 30, 15: 40, 18: 50},
        13: {5: 10, 7: 20, 10: 30, 12: 40, 15: 60, 18: 80},
        16: {4: 10, 6: 20, 8: 30, 10: 50, 12: 70, 15: 90},
        19: {3: 10, 5: 20, 7: 40, 9: 60, 11: 80, 13: 100},
        21: {3: 10, 4: 20, 6: 50, 8: 80, 10: 100},
        24: {3: 10, 4: 30, 6: 70, 8: 100},
        27: {3: 20, 5: 60, 7: 100}
    }

    @staticmethod
    def _interpolate(x: float, x0: float, y0: float, x1: float, y1: float) -> float:
        if x1 == x0: return y0
        return y0 + (x - x0) * (y1 - y0) / (x1 - x0)

    @staticmethod
    def _find_bounding_keys(keys: List[float], value: float) -> Tuple[float, float]:
        if value <= keys[0]: return keys[0], keys[0]
        if value >= keys[-1]: return keys[-1], keys[-1]
        for i in range(len(keys) - 1):
            if keys[i] <= value < keys[i + 1]: return keys[i], keys[i + 1]
        return keys[-1], keys[-1]

    @staticmethod
    def calculer_ipi(meteo_evenement: Dict, duree_humectation_estimee: float) -> int:
        temp = meteo_evenement.get('temp_moy')
        if temp is None or temp < 10 or temp > 27: return 0
        temp_keys = sorted(ModeleIPI.IPI_TABLE.keys())
        t0, t1 = ModeleIPI._find_bounding_keys(temp_keys, temp)
        durees_t0 = ModeleIPI.IPI_TABLE[t0]
        keys_d_t0 = sorted(durees_t0.keys())
        d0_t0, d1_t0 = ModeleIPI._find_bounding_keys(keys_d_t0, duree_humectation_estimee)
        ipi_t0 = ModeleIPI._interpolate(duree_humectation_estimee, d0_t0, durees_t0[d0_t0], d1_t0, durees_t0[d1_t0])
        if t0 == t1: return round(max(0, ipi_t0))
        durees_t1 = ModeleIPI.IPI_TABLE[t1]
        keys_d_t1 = sorted(durees_t1.keys())
        d0_t1, d1_t1 = ModeleIPI._find_bounding_keys(keys_d_t1, duree_humectation_estimee)
        ipi_t1 = ModeleIPI._interpolate(duree_humectation_estimee, d0_t1, durees_t1[d0_t1], d1_t1, durees_t1[d1_t1])
        ipi_final = ModeleIPI._interpolate(temp, t0, ipi_t0, t1, ipi_t1)
        return round(max(0, ipi_final))

    @staticmethod
    def estimer_duree_humectation(precipitation: float, humidite: float) -> float:
        if precipitation is None or humidite is None: return 0
        if precipitation < 2: return 0
        if precipitation < 5:
            duree_base = precipitation * 0.8
        else:
            duree_base = precipitation * 1.2
        if humidite > 90:
            duree_base *= 1.3
        elif humidite > 80:
            duree_base *= 1.1
        return min(duree_base, 24)


class ModeleOidium:
    """Modèle de risque Oïdium (simplifié)"""

    @staticmethod
    def calculer_risque_infection(meteo_7j: List[Dict], stade_coef: float) -> Tuple[float, str]:
        if not meteo_7j: return 0.0, "FAIBLE"
        score_total = 0
        jours_comptes = 0
        for m in meteo_7j:
            if not m: continue
            jours_comptes += 1
            temp_max = m.get('temp_max', 0)
            humid = m.get('humidite', 0)
            pluie = m.get('precipitation', 0)
            daily_score = 0
            if temp_max is not None and temp_max >= 33:
                daily_score = -2
            elif temp_max is not None and humid is not None and 20 <= temp_max <= 28 and humid >= 60:
                daily_score = 3
            elif temp_max is not None and humid is not None and 15 <= temp_max <= 30 and humid >= 50:
                daily_score = 1
            if pluie is not None and pluie >= 5: daily_score -= 1
            score_total += max(daily_score, -2)
        max_score_possible = jours_comptes * 3
        if max_score_possible == 0: return 0.0, "FAIBLE"
        score_final_brut = (score_total / max_score_possible) * 10
        score_final_brut = max(0, score_final_brut)
        score_final = score_final_brut * (stade_coef / 1.5)
        score_final = min(10, max(0, score_final))
        if score_final >= 7:
            niveau = "FORT"
        elif score_final >= 4:
            niveau = "MOYEN"
        else:
            niveau = "FAIBLE"
        return round(score_final, 1), niveau


class ModeleBilanHydrique:
    """Modèle de Bilan Hydrique Agronomique (ETc + Ks + Kc dynamique)"""

    @staticmethod
    def calculer_kc_gdd(gdd_cumul: float) -> float:
        """Calcule un Kc dynamique basé sur les GDD (courbe foliaire simplifiée)"""
        # 0 - 200 GDD : Dormance / Débourrement (Kc minimal)
        if gdd_cumul < 200:
            return 0.1
        # 200 - 600 GDD : Croissance active (Kc monte vers 0.7)
        elif gdd_cumul < 600:
            return 0.1 + (0.6 * (gdd_cumul - 200) / 400)
        # 600 - 1200 GDD : Floraison / Nouaison / Croissance baies (Kc plateau)
        elif gdd_cumul < 1200:
            return 0.7 + (0.1 * (gdd_cumul - 600) / 600) # Monte légèrement vers 0.8
        # 1200 - 1500 GDD : Véraison (Kc commence à baisser)
        elif gdd_cumul < 1500:
            return 0.8 - (0.4 * (gdd_cumul - 1200) / 300)
        # > 1500 GDD : Maturation (Kc bas)
        else:
            return max(0.3, 0.4 - (0.1 * (gdd_cumul - 1500) / 300))

    @staticmethod
    def calculer_bilan_rfu(meteo_historique: Dict[str, Dict],
                           parcelle: Dict,
                           stade_manuel: str,
                           kc_calendrier: Dict,
                           rfu_max_mm: float,
                           f_runoff: float,
                           i_const_mm: float,
                           gdd_cumul_actuel: float = 0.0,
                           debug: bool = False) -> Dict:
        """
        Calcule la Réserve Utile (AWC/RFU) restante en %
        Optimisation Jules : Intégration Ks (stress) et Kc dynamique GDD.
        """
        aujourdhui = datetime.now().date()
        annee_actuelle = aujourdhui.year

        if debug:
            print("\n🔍 MODE DEBUG - CALCUL BILAN HYDRIQUE OPTIMISÉ")
            print(f"Date       | Pluie | P.Eff | ET₀  | Kc   | Ks   | ETc  | RFU mm | RFU %")
            print("-" * 85)

        # 1. Début du cycle hydrologique (1er Novembre précédent)
        if aujourdhui.month >= 11:
            date_cycle_debut = datetime(annee_actuelle, 11, 1).date()
        else:
            date_cycle_debut = datetime(annee_actuelle - 1, 11, 1).date()

        dates_disponibles = sorted([datetime.strptime(d, '%Y-%m-%d').date() for d in meteo_historique.keys()])
        dates_utiles = [d for d in dates_disponibles if d >= date_cycle_debut and d <= aujourdhui]

        if not dates_utiles:
            return {
                'rfu_pct': 100.0, 'rfu_mm': rfu_max_mm, 'rfu_max_mm': rfu_max_mm,
                'niveau': "Données insuffisantes", 'historique_pct': {}, 'ks_actuel': 1.0
            }

        date_debut = dates_utiles[0]
        rfu_actuelle_mm = rfu_max_mm # Init plein
        rfu_historique_pct = {}
        ks_actuel = 1.0

        for date_obj in dates_utiles:
            date_str = date_obj.strftime('%Y-%m-%d')
            data_jour = meteo_historique.get(date_str, {})

            pluie = data_jour.get('precipitation', 0.0) or 0.0
            etp0 = data_jour.get('etp0', 0.0) or 0.0
            gdd_jour = data_jour.get('gdd_jour', 0.0) or 0.0 # On a besoin de cumuler les GDD pour le Kc

            # 2. Kc Dynamique (Estimation du cumul au jour J)
            # Pour la simulation, on pourrait cumuler les GDD ici si besoin
            # Mais on va utiliser le Kc calendrier si GDD non dispo (période hivernale)
            # Jules : On utilise Kc GDD si on est après le débourrement estimé
            if date_obj.month >= 3 and date_obj.month <= 10:
                # Simulation simple du cumul GDD progressif pour le Kc
                # Dans une version parfaite, on passerait le dictionnaire des GDD cumulés
                Kc = ModeleBilanHydrique.calculer_kc_gdd(gdd_cumul_actuel * (dates_utiles.index(date_obj)/len(dates_utiles)))
            else:
                Kc = kc_calendrier.get(str(date_obj.month), 0.1)

            # 3. Coefficient de Stress Ks (FAO-56 simplifié)
            # p = 0.5 (seuil de stress à 50% de la RFU pour la vigne)
            seuil_stress_pct = 50.0
            rfu_pct_veille = (rfu_actuelle_mm / rfu_max_mm) * 100 if rfu_max_mm > 0 else 0

            if rfu_pct_veille > seuil_stress_pct:
                ks = 1.0
            else:
                # Ks diminue linéairement de 1.0 à 0.0 entre le seuil et le point de flétrissement
                ks = max(0.0, rfu_pct_veille / seuil_stress_pct)

            ks_actuel = ks

            # 4. Calcul Pluie Efficace et ETc
            if pluie > i_const_mm:
                P_eff = (pluie - i_const_mm) * (1.0 - f_runoff)
            else:
                P_eff = 0.0

            ETc = Kc * etp0 * ks

            # 5. Bilan
            rfu_actuelle_mm = min(rfu_max_mm, rfu_actuelle_mm + P_eff - ETc)
            rfu_actuelle_mm = max(0.0, rfu_actuelle_mm)

            current_pct = (rfu_actuelle_mm / rfu_max_mm) * 100 if rfu_max_mm > 0 else 0
            rfu_historique_pct[date_str] = round(current_pct, 1)

            if debug and (date_obj.day == 1 or date_obj.day == 15 or date_obj == aujourdhui):
                print(f"{date_str} | {pluie:5.1f} | {P_eff:5.1f} | {etp0:4.1f} | {Kc:4.2f} | {ks:4.2f} | {ETc:4.1f} | {rfu_actuelle_mm:6.1f} | {current_pct:5.1f}%")

        if debug:
            print("-" * 70)

        # 8. Calculer le pourcentage final
        if rfu_max_mm == 0:
            rfu_pct = 0.0
        else:
            rfu_pct = (rfu_actuelle_mm / rfu_max_mm) * 100

        # 9. Déterminer le niveau d'alerte
        if rfu_pct <= 30:
            niveau = "STRESS FORT"
        elif rfu_pct <= 60:
            niveau = "SURVEILLANCE"
        else:
            niveau = "CONFORTABLE"

        if stade_manuel == 'repos':
            niveau += " (Dormance)"

        return {
            'rfu_pct': round(rfu_pct, 1),
            'rfu_mm': round(rfu_actuelle_mm, 1),
            'rfu_max_mm': rfu_max_mm,
            'niveau': niveau,
            'historique_pct': rfu_historique_pct,
            'ks_actuel': round(ks_actuel, 2)
        }


class GestionTraitements:
    """Gestion des traitements et calcul de la protection résiduelle"""
    INITIAL_FONGICIDES = {
        'bouillie_bordelaise': {'nom': 'Bouillie bordelaise', 'persistance_jours': 10, 'lessivage_seuil_mm': 30,
                                'type': 'contact', 'dose_reference_kg_ha': 2.0, 'n_amm': '2010486'},
        'cymoxanil': {'nom': 'Cymoxanil', 'persistance_jours': 7, 'lessivage_seuil_mm': 20, 'type': 'penetrant',
                      'dose_reference_kg_ha': 0.5, 'n_amm': '9500057'},
        'fosetyl_al': {'nom': 'Fosétyl-Al', 'persistance_jours': 14, 'lessivage_seuil_mm': 40, 'type': 'systemique',
                       'dose_reference_kg_ha': 2.5, 'n_amm': '2110118'},
        'mancozebe': {'nom': 'Mancozèbe', 'persistance_jours': 7, 'lessivage_seuil_mm': 25, 'type': 'contact',
                      'dose_reference_kg_ha': 1.6, 'n_amm': '8000494'},
        'soufre': {'nom': 'Soufre', 'persistance_jours': 8, 'lessivage_seuil_mm': 15, 'type': 'contact',
                   'dose_reference_kg_ha': 3.0, 'n_amm': '2080066'}
    }
    COEF_POUSSE = {
        'repos': 0.0, 'debourrement': 0.5, 'pousse_10cm': 2.0, 'pre_floraison': 1.8,
        'floraison': 1.0, 'nouaison': 0.8, 'fermeture_grappe': 0.5, 'veraison': 0.2, 'maturation': 0.1
    }

    def __init__(self, fichier_historique: str = 'traitements'):
        self.key = fichier_historique.replace('.json', '')
        self.storage = DataManager()
        self.historique = self.charger_historique()
        self.FONGICIDES = self.charger_produits()

    def charger_produits(self) -> Dict:
        """Charge la liste des produits depuis le stockage ou utilise les valeurs par défaut."""
        data = self.storage.load_data('produits', default_factory=lambda: {'produits': []})
        produits_list = data.get('produits', [])

        if not produits_list:
            # Migration des anciens fongicides vers le nouveau format
            produits_dict = self.INITIAL_FONGICIDES
            # On sauvegarde pour la première fois si vide
            list_to_save = []
            for k, v in produits_dict.items():
                item = v.copy()
                if 'id' not in item: item['id'] = k
                list_to_save.append(item)
            self.storage.save_data('produits', {'produits': list_to_save})
            return produits_dict

        # Reconstruire le dictionnaire indexé par le nom technique (ou id)
        return {p.get('id', p['nom'].lower().replace(' ', '_')): p for p in produits_list}

    def charger_historique(self) -> Dict:
        return self.storage.load_data(self.key, default_factory=lambda: {'traitements': []})

    def sauvegarder_historique(self):
        self.storage.save_data(self.key, self.historique)

    def ajouter_traitement(self, parcelle: str, date: str, produit: str, dose_kg_ha: Optional[float] = None,
                           heure: str = "10:00", mouillage_pct: float = 100.0, surface_traitee: float = 0.0,
                           type_utilisation: str = "Plein champ", cible: str = "Mildiou",
                           conditions_meteo: str = "Ensoleillé, vent faible", applicateur: str = "",
                           systeme_culture: str = "PC", culture: str = "Vigne"):

        # On rafraîchit la liste des produits pour être sûr d'avoir les derniers ajouts
        self.FONGICIDES = self.charger_produits()

        produit_key = produit # On attend l'ID maintenant
        if produit_key not in self.FONGICIDES:
            # Essayer par nom si l'ID ne matche pas (compatibilité)
            found = False
            for k, v in self.FONGICIDES.items():
                if v['nom'] == produit:
                    produit_key = k
                    found = True
                    break

            if not found:
                print(f"⚠️  Produit '{produit}' inconnu. Ajout avec paramètres par défaut.")
                caracteristiques = {'nom': produit, 'persistance_jours': 7, 'lessivage_seuil_mm': 25, 'type': 'contact',
                                    'dose_reference_kg_ha': 1.0, 'n_amm': 'N/A'}
            else:
                caracteristiques = self.FONGICIDES[produit_key].copy()
        else:
            caracteristiques = self.FONGICIDES[produit_key].copy()

        if dose_kg_ha is None:
            dose_kg_ha = caracteristiques['dose_reference_kg_ha']

        traitement = {
            'parcelle': parcelle,
            'date': date,
            'produit': produit_key,
            'dose_kg_ha': dose_kg_ha,
            'caracteristiques': caracteristiques,
            # Nouveaux champs légaux
            'heure': heure,
            'mouillage_pct': mouillage_pct,
            'surface_traitee': surface_traitee,
            'type_utilisation': type_utilisation,
            'cible': cible,
            'conditions_meteo': conditions_meteo,
            'applicateur': applicateur,
            'systeme_culture': systeme_culture,
            'culture': culture
        }
        self.historique['traitements'].append(traitement)
        self.sauvegarder_historique()
        print(f"✅ Traitement '{caracteristiques['nom']}' ajouté pour '{parcelle}' le {date}")

    def calculer_protection_actuelle(self, parcelle: str, date_actuelle: str, meteo_periode: Dict, stade_actuel: str) -> \
    Tuple[float, Dict, str]:
        traitements_parcelle = [t for t in self.historique['traitements'] if t['parcelle'] == parcelle]
        if not traitements_parcelle:
            return 0.0, {}, "Aucun traitement"
        dernier_traitement = max(traitements_parcelle, key=lambda x: x['date'])
        date_trait = datetime.strptime(dernier_traitement['date'], '%Y-%m-%d')
        date_act = datetime.strptime(date_actuelle, '%Y-%m-%d')
        jours_ecoules = (date_act - date_trait).days
        if jours_ecoules < 0:
            return 10.0, dernier_traitement, "Traitement futur"
        carac = dernier_traitement['caracteristiques']
        persistance = carac.get('persistance_jours', 7)
        seuil_lessivage = carac.get('lessivage_seuil_mm', 25)
        type_produit = carac.get('type', 'contact')
        facteur_limitant = "Persistance"
        protection_temps = max(0, 10 - (jours_ecoules / persistance * 10))
        protection = protection_temps
        if type_produit in ['contact', 'penetrant']:
            coef_pousse = self.COEF_POUSSE.get(stade_actuel, 1.0)
            protection_pousse = max(0, 10 - (jours_ecoules * coef_pousse))
            if protection_pousse < protection:
                protection = protection_pousse
                facteur_limitant = "Pousse (dilution)"
        pluie_depuis_traitement = sum(
            meteo_periode.get(date, {}).get('precipitation', 0)
            for date in meteo_periode
            if date >= dernier_traitement['date'] and date <= date_actuelle
        )
        if pluie_depuis_traitement > seuil_lessivage:
            protection = 0
            facteur_limitant = f"Lessivage ({pluie_depuis_traitement:.1f}mm)"
        return round(protection, 1), dernier_traitement, facteur_limitant

    def calculer_ift_periode(self, date_debut: str, date_fin: str, surface_totale: float) -> Dict:
        traitements_periode = [t for t in self.historique['traitements'] if date_debut <= t['date'] <= date_fin]
        if not traitements_periode:
            return {'ift_total': 0.0, 'nb_traitements': 0, 'details': []}
        ift_details = []
        ift_total = 0.0
        for t in traitements_periode:
            dose_appliquee = t.get('dose_kg_ha', 0)
            dose_reference = t['caracteristiques'].get('dose_reference_kg_ha', 1.0)
            ift_traitement = dose_appliquee / dose_reference
            ift_total += ift_traitement
            ift_details.append({'date': t['date'], 'parcelle': t['parcelle'], 'produit': t['caracteristiques']['nom'],
                                'ift': round(ift_traitement, 2)})
        return {'ift_total': round(ift_total, 2), 'nb_traitements': len(traitements_periode), 'details': ift_details,
                'periode': f"{date_debut} à {date_fin}"}


class GestionFertilisation:
    """Gestion des apports en engrais et amendements"""

    def __init__(self, fichier='fertilisation'):
        self.key = fichier.replace('.json', '')
        self.storage = DataManager()
        self.donnees = self.charger_donnees()

    def charger_donnees(self) -> Dict:
        return self.storage.load_data(self.key, default_factory=lambda: {'apports': []})

    def sauvegarder(self):
        self.storage.save_data(self.key, self.donnees)

    def ajouter_apport(self, parcelle: str, date_apport: str, produit_id: str, produit_info: Dict, quantite_ha: float):
        """Ajoute un apport et calcule les unités"""

        # Calcul des unités : Qty * (% / 100)
        u_n = quantite_ha * (float(produit_info.get('n', 0)) / 100)
        u_p = quantite_ha * (float(produit_info.get('p', 0)) / 100)
        u_k = quantite_ha * (float(produit_info.get('k', 0)) / 100)
        u_mgo = quantite_ha * (float(produit_info.get('mgo', 0)) / 100)

        apport = {
            'parcelle': parcelle,
            'date': date_apport,
            'produit_id': produit_id,
            'produit_nom': produit_info.get('nom', produit_id),
            'quantite_ha': quantite_ha,
            'u_n': round(u_n, 2),
            'u_p': round(u_p, 2),
            'u_k': round(u_k, 2),
            'u_mgo': round(u_mgo, 2),
            'bio': produit_info.get('bio', False),
            'type_application': produit_info.get('type_application', 'Sol')
        }

        self.donnees['apports'].append(apport)
        self.sauvegarder()
        return apport

    def get_bilan_annuel(self, annee: int) -> Dict:
        """Retourne le bilan N-P-K par parcelle pour une année"""
        bilan = {}
        for a in self.donnees['apports']:
            date_dt = datetime.strptime(a['date'], '%Y-%m-%d')
            if date_dt.year == annee:
                p = a['parcelle']
                if p not in bilan:
                    bilan[p] = {'n': 0, 'p': 0, 'k': 0, 'mgo': 0, 'nb_passages': 0}
                bilan[p]['n'] += a.get('u_n', 0)
                bilan[p]['p'] += a.get('u_p', 0)
                bilan[p]['k'] += a.get('u_k', 0)
                bilan[p]['mgo'] += a.get('u_mgo', 0)
                bilan[p]['nb_passages'] += 1

        # Arrondir les résultats
        for p in bilan:
            bilan[p]['n'] = round(bilan[p]['n'], 1)
            bilan[p]['p'] = round(bilan[p]['p'], 1)
            bilan[p]['k'] = round(bilan[p]['k'], 1)
            bilan[p]['mgo'] = round(bilan[p]['mgo'], 1)

        return bilan

    def get_bilan_detaille(self, annee: int, parcelle_nom: str) -> Dict:
        """Retourne le bilan N-P-K détaillé (Sol vs Foliaire)"""
        detail = {'sol': {'n': 0, 'p': 0, 'k': 0, 'mgo': 0}, 'foliaire': {'n': 0, 'p': 0, 'k': 0, 'mgo': 0}}
        for a in self.donnees['apports']:
            date_dt = datetime.strptime(a['date'], '%Y-%m-%d')
            if date_dt.year == annee and a['parcelle'] == parcelle_nom:
                t = a.get('type_application', 'Sol').lower()
                if t not in detail: detail[t] = {'n': 0, 'p': 0, 'k': 0, 'mgo': 0}
                detail[t]['n'] += a.get('u_n', 0)
                detail[t]['p'] += a.get('u_p', 0)
                detail[t]['k'] += a.get('u_k', 0)
                detail[t]['mgo'] += a.get('u_mgo', 0)

        for t in detail:
            for k in detail[t]:
                detail[t][k] = round(detail[t][k], 1)
        return detail

    def calculer_bilan_pilotage(self, parcelle_nom: str, annee: int, config_vignoble: 'ConfigVignoble') -> Dict:
        """Calcule les besoins théoriques et le solde pour une parcelle avec breakdown sarments"""
        parcelle = next((p for p in config_vignoble.parcelles if p['nom'] == parcelle_nom), None)
        if not parcelle:
            return {}

        objectif_hl_ha = parcelle.get('objectif_rdt', 50.0)
        cepages = parcelle.get('cepages', [])

        # Calculer le coefficient moyen pondéré par cépage
        all_coefs = config_vignoble.export_coefs

        sum_n, sum_p, sum_k, sum_mgo = 0, 0, 0, 0
        count = 0
        for c in cepages:
            coef = all_coefs.get(c, {'n': 1.0, 'p': 0.4, 'k': 1.3, 'mgo': 0.2})
            sum_n += coef.get('n', 0)
            sum_p += coef.get('p', 0)
            sum_k += coef.get('k', 0)
            sum_mgo += coef.get('mgo', 0)
            count += 1

        if count > 0:
            avg_coef_n = sum_n / count
            avg_coef_p = sum_p / count
            avg_coef_k = sum_k / count
            avg_coef_mgo = sum_mgo / count
        else:
            avg_coef_n, avg_coef_p, avg_coef_k, avg_coef_mgo = 1.0, 0.4, 1.3, 0.2

        # Besoin théorique (Unités/Ha) = Objectif (Hl/Ha) * Coef (Unités/Hl)
        besoin_n = objectif_hl_ha * avg_coef_n
        besoin_p = objectif_hl_ha * avg_coef_p
        besoin_k = objectif_hl_ha * avg_coef_k
        besoin_mgo = objectif_hl_ha * avg_coef_mgo

        # Récupérer les apports réels de l'année (Breakdown Sol/Foliaire)
        apports_detail = self.get_bilan_detaille(annee, parcelle_nom)
        apport_sol = apports_detail.get('sol', {'n': 0, 'p': 0, 'k': 0})
        apport_foliaire = apports_detail.get('foliaire', {'n': 0, 'p': 0, 'k': 0})

        # Récupérer les apports réels de l'année (Unités réelles)
        apport_sol_mgo = apport_sol.get('mgo', 0.0) # On s'assure que mgo est là
        apport_foliaire_mgo = apport_foliaire.get('mgo', 0.0)

        # Crédit sarments (hypothèse conservatrice mise à jour)
        restitution = {'n': 0, 'p': 0, 'k': 0, 'mgo': 0}
        if parcelle.get('broyage_sarments', False):
            # N: 6, P: 2, K: 8, MgO: 1
            restitution = {'n': 6.0, 'p': 2.0, 'k': 8.0, 'mgo': 1.0}

        # Totaux disponibles
        total_n = apport_sol['n'] + apport_foliaire['n'] + restitution['n']
        total_p = apport_sol['p'] + apport_foliaire['p'] + restitution['p']
        total_k = apport_sol['k'] + apport_foliaire['k'] + restitution['k']
        total_mgo = apport_sol.get('mgo', 0) + apport_foliaire.get('mgo', 0) + restitution['mgo']

        solde_n = total_n - besoin_n
        solde_p = total_p - besoin_p
        solde_k = total_k - besoin_k
        solde_mgo = total_mgo - besoin_mgo

        couverture_n = (total_n / besoin_n * 100) if besoin_n > 0 else 0
        couverture_p = (total_p / besoin_p * 100) if besoin_p > 0 else 0
        couverture_k = (total_k / besoin_k * 100) if besoin_k > 0 else 0
        couverture_mgo = (total_mgo / besoin_mgo * 100) if besoin_mgo > 0 else 0

        return {
            'objectif_hl_ha': objectif_hl_ha,
            'besoins': {'n': round(besoin_n, 1), 'p': round(besoin_p, 1), 'k': round(besoin_k, 1), 'mgo': round(besoin_mgo, 1)},
            'apports': {'n': round(total_n, 1), 'p': round(total_p, 1), 'k': round(total_k, 1), 'mgo': round(total_mgo, 1)},
            'breakdown': {
                'sol': apport_sol,
                'foliaire': apport_foliaire,
                'sarments': restitution
            },
            'soldes': {'n': round(solde_n, 1), 'p': round(solde_p, 1), 'k': round(solde_k, 1), 'mgo': round(solde_mgo, 1)},
            'couverture_pct': {'n': round(couverture_n, 1), 'p': round(couverture_p, 1), 'k': round(couverture_k, 1), 'mgo': round(couverture_mgo, 1)}
        }


class GestionHistoriqueAlertes:
    """Gestion de l'historique des alertes et analyses"""

    def __init__(self, fichier='historique_alertes'):
        self.key = fichier.replace('.json', '')
        self.storage = DataManager()
        self.historique = self.charger_historique()

    def charger_historique(self):
        return self.storage.load_data(self.key, default_factory=self.creer_structure_defaut)

    def creer_structure_defaut(self):
        return {'campagnes': []}

    def sauvegarder(self):
        self.storage.save_data(self.key, self.historique)

    def get_campagne(self, annee):
        for c in self.historique['campagnes']:
            if c['annee'] == annee: return c
        return None

    def creer_campagne(self, annee):
        campagne = {'annee': annee, 'analyses': []}
        self.historique['campagnes'].append(campagne)
        return campagne

    def ajouter_analyse(self, analyse_complete):
        date_analyse = analyse_complete['date_analyse']
        annee = datetime.strptime(date_analyse, '%Y-%m-%d').year
        campagne = self.get_campagne(annee)
        if not campagne:
            campagne = self.creer_campagne(annee)
        analyse_simplifiee = {
            'date': date_analyse,
            'parcelle': analyse_complete['parcelle'],
            'stade': analyse_complete['stade'],
            'gdd_cumul': analyse_complete.get('gdd', {}).get('cumul'),
            'gdd_stade_estime': analyse_complete.get('gdd', {}).get('stade_estime'),
            'bilan_hydrique_pct': analyse_complete.get('bilan_hydrique', {}).get('rfu_pct'),
            'bilan_hydrique_ks': analyse_complete.get('bilan_hydrique', {}).get('ks_actuel'),
            'risque_mildiou': {
                'score': analyse_complete['risque_infection']['score'],
                'niveau': analyse_complete['risque_infection']['niveau'],
                'ipi': analyse_complete['risque_infection'].get('ipi')
            },
            'risque_oidium': {
                'score': analyse_complete.get('risque_oidium', {}).get('score'),
                'niveau': analyse_complete.get('risque_oidium', {}).get('niveau')
            },
            'protection': {
                'score': analyse_complete['protection_actuelle']['score'],
                'dernier_traitement': analyse_complete['protection_actuelle']['dernier_traitement'].get('date') if
                analyse_complete['protection_actuelle']['dernier_traitement'] else None,
                'facteur_limitant': analyse_complete['protection_actuelle']['facteur_limitant']
            },
            'decision': {
                'score': analyse_complete['decision']['score'],
                'action': analyse_complete['decision']['action'],
                'urgence': analyse_complete['decision']['urgence'],
                'alerte_oidium': analyse_complete['decision'].get('alerte_oidium'),
                'alerte_stade': analyse_complete.get('gdd', {}).get('alerte_stade'),
                'alerte_hydrique': analyse_complete.get('bilan_hydrique', {}).get('niveau')
            },
            'meteo': {
                'temp_moy': analyse_complete['meteo_actuelle'].get('temp_moy'),
                'precipitation': analyse_complete['meteo_actuelle'].get('precipitation'),
                'humidite': analyse_complete['meteo_actuelle'].get('humidite')
            },
            'previsions': {
                'pluie_3j': analyse_complete['previsions_3j']['pluie_totale']
            }
        }
        analyses_existantes = [a for a in campagne['analyses']
                               if a['date'] == date_analyse and a['parcelle'] == analyse_complete['parcelle']]
        if analyses_existantes:
            idx = campagne['analyses'].index(analyses_existantes[0])
            campagne['analyses'][idx] = analyse_simplifiee
        else:
            campagne['analyses'].append(analyse_simplifiee)
        self.sauvegarder()

    def get_analyses_parcelle(self, parcelle, date_debut=None, date_fin=None):
        analyses = []
        for campagne in self.historique['campagnes']:
            for analyse in campagne['analyses']:
                if analyse['parcelle'] == parcelle:
                    if date_debut and analyse['date'] < date_debut: continue
                    if date_fin and analyse['date'] > date_fin: continue
                    analyses.append(analyse)
        return sorted(analyses, key=lambda x: x['date'])

    def get_alertes_urgence(self, urgence='haute', jours=7):
        date_limite = (datetime.now() - timedelta(days=jours)).strftime('%Y-%m-%d')
        alertes = []
        for campagne in self.historique['campagnes']:
            for analyse in campagne['analyses']:
                if analyse['date'] >= date_limite and analyse['decision']['urgence'] == urgence:
                    alertes.append(analyse)
        return sorted(alertes, key=lambda x: x['date'], reverse=True)

    def generer_rapport_campagne(self, annee):
        campagne = self.get_campagne(annee)
        if not campagne or not campagne['analyses']: return None
        analyses = campagne['analyses']
        parcelles_stats = {}
        for analyse in analyses:
            parcelle = analyse['parcelle']
            if parcelle not in parcelles_stats:
                parcelles_stats[parcelle] = {'nb_analyses': 0, 'alertes_haute': 0, 'alertes_moyenne': 0,
                                             'risque_moyen': 0, 'protection_moyenne': 0}
            stats = parcelles_stats[parcelle]
            stats['nb_analyses'] += 1
            stats['risque_moyen'] += analyse['risque_mildiou']['score']
            stats['protection_moyenne'] += analyse['protection']['score']
            if analyse['decision']['urgence'] == 'haute':
                stats['alertes_haute'] += 1
            elif analyse['decision']['urgence'] == 'moyenne':
                stats['alertes_moyenne'] += 1
        for stats in parcelles_stats.values():
            if stats['nb_analyses'] > 0:
                stats['risque_moyen'] = round(stats['risque_moyen'] / stats['nb_analyses'], 2)
                stats['protection_moyenne'] = round(stats['protection_moyenne'] / stats['nb_analyses'], 2)
        return {'annee': annee, 'nb_analyses_total': len(analyses), 'parcelles': parcelles_stats,
                'periode': {'debut': min(a['date'] for a in analyses), 'fin': max(a['date'] for a in analyses)}}


class SystemeDecision:
    """Système principal d'aide à la décision"""

    SEUIL_ALERTE_PLUIE = 10  # mm
    SEUIL_PROTECTION_FAIBLE = 5  # /10
    SEUIL_DECISION_HAUTE = 5  # /10
    SEUIL_DECISION_MOYENNE = 2  # /10

    METEO_HISTORIQUE_FILE = 'meteo_historique.json'
    GDD_STADE_MAP = {
        180: 'debourrement', 300: 'pousse_10cm', 500: 'pre_floraison',
        600: 'floraison', 750: 'nouaison', 900: 'fermeture_grappe',
        1200: 'veraison', 1500: 'maturation', 1800: 'repos'
    }

    def __init__(self):
        self.storage = DataManager()
        self.config = ConfigVignoble()
        self.meteo = MeteoAPI(self.config.latitude, self.config.longitude)
        self.traitements = GestionTraitements()
        self.modele_simple = ModeleSimple()
        self.modele_ipi = ModeleIPI()
        self.modele_oidium = ModeleOidium()
        self.modele_bilan_hydrique = ModeleBilanHydrique()
        self.historique_analyses = []
        self.historique_alertes = GestionHistoriqueAlertes()

        self.meteo_historique: Dict[str, Dict] = self._charger_meteo_historique()
        # On lance une mise à jour de l'historique météo au démarrage
        self._mettre_a_jour_historique_meteo()

    def _charger_meteo_historique(self) -> Dict[str, Dict]:
        """Charge l'historique MÉTÉO via le DataManager."""
        return self.storage.load_data(self.METEO_HISTORIQUE_FILE.replace('.json', ''))

    def _sauvegarder_meteo_historique(self):
        """Sauvegarde l'historique MÉTÉO via le DataManager."""
        try:
            aujourdhui = datetime.now().date()
            data_a_sauver = {}

            dates_triees = sorted(self.meteo_historique.keys())

            for date_str in dates_triees:
                try:
                    date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
                    # On garde les 366 derniers jours OU si la date est dans l'année en cours
                    if (aujourdhui - date_obj).days <= 366 or date_obj.year == aujourdhui.year:
                        data_a_sauver[date_str] = self.meteo_historique[date_str]
                except (ValueError, TypeError):
                    print(f"Ignoré : clé invalide dans l'historique météo : {date_str}")

            self.storage.save_data(self.METEO_HISTORIQUE_FILE.replace('.json', ''), data_a_sauver)

            # Sauvegarder aussi les GDD séparément pour l'onglet GDD demandé
            gdd_data = {d: v.get('gdd_jour', 0.0) for d, v in data_a_sauver.items() if 'gdd_jour' in v}
            self.storage.save_data('gdd_historique', gdd_data)

        except Exception as e:
            print(f"⚠️ Erreur lors de la sauvegarde Météo/GDD: {e}")

    # --- MODIFIÉ : Correction du Bug de persistance ---
    def _mettre_a_jour_historique_meteo(self) -> Dict:
        """
        Appelle l'API (90j) et fusionne les données avec l'historique persistant.
        Calcule et stocke le GDD journalier et l'ETP.
        Retourne l'historique complet pour l'analyse.
        """
        # 1. Appeler l'API pour les 90 derniers jours + 7 jours futurs
        meteo_data_recent = self.meteo.get_meteo_data(days_past=90, days_future=7)

        if not meteo_data_recent:
            print("❌ Échec de la mise à jour de l'historique météo. Utilisation des données en cache.")
            return self.meteo_historique

        aujourdhui = datetime.now().date()
        T_base = self.config.parametres.get('t_base_gdd', 10.0)

        # 2. Mettre à jour l'historique persistant
        for date_str, data in meteo_data_recent.items():
            if not data:
                continue

            # Ne PAS écraser l'historique avec des valeurs nulles d'Open-Meteo
            temp_max = data.get('temp_max')
            temp_min = data.get('temp_min')
            pluie = data.get('precipitation')
            humid = data.get('humidite')
            etp0 = data.get('etp0')

            # ❗ Si Open-Meteo renvoie des valeurs nulles → on ignore ce jour
            if temp_max is None and temp_min is None and pluie is None and etp0 is None:
                # print(f"Ignoré {date_str} : données Open-Meteo manquantes")
                continue

            # Calcul température moyenne
            if temp_max is not None and temp_min is not None:
                temp_moy = (temp_max + temp_min) / 2
            elif temp_max is not None:
                temp_moy = temp_max
            elif temp_min is not None:
                temp_moy = temp_min
            else:
                temp_moy = 0.0

            # Calcul GDD
            gdd_journalier = max(0.0, temp_moy - T_base)

            # Fusion (sans écraser par None)
            jour = self.meteo_historique.get(date_str, {})
            self.meteo_historique[date_str] = {
                'temp_moy': temp_moy,
                'temp_max': temp_max if temp_max is not None else jour.get('temp_max'),
                'temp_min': temp_min if temp_min is not None else jour.get('temp_min'),
                'precipitation': pluie if pluie is not None else jour.get('precipitation', 0),
                'humidite': humid if humid is not None else jour.get('humidite', 60),
                'etp0': etp0 if etp0 is not None else jour.get('etp0', 3.5),
                'gdd_jour': gdd_journalier
            }

        # 3. Sauvegarder le fichier (contient maintenant l'ancien + le nouveau)
        self._sauvegarder_meteo_historique()

        return self.meteo_historique

    def _calculer_gdd(self, parcelle: Dict, meteo_historique: Dict, date_actuelle: str, stade_manuel: str) -> Tuple[
        int, str, Optional[int], Optional[str], str]:
        """
        Calcule le GDD cumulé (base 10) en lisant l'historique persistant.
        """
        try:
            if stade_manuel == 'repos':
                return 0, 'repos', 180, 'debourrement', 'En dormance (calcul GDD inactif)'

            annee_actuelle = datetime.strptime(date_actuelle, '%Y-%m-%d').year
            aujourdhui = datetime.strptime(date_actuelle, '%Y-%m-%d').date()

            date_debut_gdd_str = f"{annee_actuelle}-03-01"
            mode_calcul = "1er Mars (Estimation)"

            date_biofix = parcelle.get('date_debourrement')
            if date_biofix:
                date_biofix_dt = datetime.strptime(date_biofix, '%Y-%m-%d')
                if date_biofix_dt.year == annee_actuelle and date_biofix_dt.date() <= aujourdhui:
                    date_debut_gdd_str = date_biofix
                    mode_calcul = f"Biofix ({date_biofix})"

            date_debut_gdd = datetime.strptime(date_debut_gdd_str, '%Y-%m-%d').date()

            gdd_sum = 0.0
            stade_estime_gdd = 'repos'

            dates_historique = sorted(meteo_historique.keys())

            for date_str in dates_historique:
                date_meteo = datetime.strptime(date_str, '%Y-%m-%d').date()
                if date_meteo >= date_debut_gdd and date_meteo <= aujourdhui:
                    gdd_sum += meteo_historique.get(date_str, {}).get('gdd_jour', 0.0)

            for gdd_seuil, nom_stade in sorted(self.GDD_STADE_MAP.items(), reverse=True):
                if gdd_sum >= gdd_seuil:
                    stade_estime_gdd = nom_stade
                    break

            prochain_stade_nom = None
            prochain_stade_gdd = None
            for gdd_seuil, nom_stade in sorted(self.GDD_STADE_MAP.items()):
                if gdd_sum < gdd_seuil:
                    prochain_stade_nom = nom_stade
                    prochain_stade_gdd = gdd_seuil
                    break

            return int(gdd_sum), stade_estime_gdd, prochain_stade_gdd, prochain_stade_nom, mode_calcul

        except Exception as e:
            print(f"Erreur calcul GDD: {e}")
            return 0, 'repos', None, None, 'Erreur'

    def _predire_stade_futur(self, meteo_historique: Dict, date_actuelle: str, gdd_actuel: int,
                             prochain_stade_gdd: Optional[int], prochain_stade_nom: Optional[str], stade_manuel: str) -> \
    Tuple[str, int]:

        if stade_manuel == 'repos':
            return "Prévision inactive (dormance)", -1

        if not prochain_stade_gdd:
            return "Cycle végétatif estimé terminé.", -1
        gdd_necessaire = prochain_stade_gdd - gdd_actuel
        if gdd_necessaire <= 0:
            return f"Stade '{prochain_stade_nom}' déjà atteint.", 0

        gdd_futur_cumul = 0
        jours_pour_atteindre = -1

        dates_futures = sorted([d for d in meteo_historique.keys() if d > date_actuelle])[:7]
        T_base = self.config.parametres.get('t_base_gdd', 10.0)

        for i, date in enumerate(dates_futures):
            if date in meteo_historique and meteo_historique[date]:
                temp_moy = meteo_historique[date].get('temp_moy', 0)
                if temp_moy is None: temp_moy = 0.0
                gdd_futur_cumul += max(0, temp_moy - T_base)
                if gdd_futur_cumul >= gdd_necessaire:
                    jours_pour_atteindre = i + 1
                    break

        if jours_pour_atteindre != -1:
            return f"Prévision : {prochain_stade_nom} dans ~{jours_pour_atteindre} jours.", jours_pour_atteindre
        else:
            return f"{prochain_stade_nom} non atteint dans les 7 prochains jours.", -1

    def analyser_parcelle(self, nom_parcelle: str, utiliser_ipi: bool = False,
                          debug: bool = False) -> Dict:
        """Analyse complète d'une parcelle"""
        parcelle = next((p for p in self.config.parcelles if p['nom'] == nom_parcelle), None)
        if not parcelle:
            return {'erreur': f"Parcelle '{nom_parcelle}' non trouvée"}

        # L'historique météo est déjà chargé et mis à jour dans __init__
        meteo_historique_complet = self.meteo_historique
        if not meteo_historique_complet:
            return {'erreur': "Historique météo vide. Impossible de lancer l'analyse."}

        date_actuelle = datetime.now().strftime('%Y-%m-%d')

        dates_48h = [(datetime.now() - timedelta(days=i)).strftime('%Y-%m-%d') for i in range(2, -1, -1)]
        meteo_48h = [meteo_historique_complet.get(d, {}) for d in dates_48h]

        sensibilites = [self.config.SENSIBILITES_CEPAGES.get(c, 5) for c in parcelle['cepages']]
        sensibilite_moy = sum(sensibilites) / len(sensibilites)

        stade_manuel = parcelle['stade_actuel']
        stade_coef = self.config.COEF_STADES.get(stade_manuel, 1.0)

        # MODÈLE SIMPLE
        risque_simple, niveau_simple = self.modele_simple.calculer_risque_infection(
            meteo_48h, stade_coef, sensibilite_moy
        )

        if debug:
            print(f"\n🔍 MODE DEBUG - STADE MANUEL UTILISÉ : {stade_manuel} (Coef: {stade_coef})")
            print("\n🔍 MODE DEBUG - CALCUL RISQUE SIMPLE (MILDIOU)")
            print(f"Pluie 48h: {sum(m.get('precipitation', 0) for m in meteo_48h if m):.1f}mm")
            temp_moy_list = [m.get('temp_moy') for m in meteo_48h if m and m.get('temp_moy') is not None]
            temp_moy_48h = sum(temp_moy_list) / len(temp_moy_list) if temp_moy_list else 0
            print(f"Temp moyenne 48h: {temp_moy_48h:.1f}°C")
            print(f"Coef stade: {stade_coef}")
            print(f"Sensibilité cépages: {sensibilite_moy:.1f}")
            print(f"→ Score: {risque_simple}/10 ({niveau_simple})")

        # MODÈLE IPI
        ipi_value = None
        ipi_risque = "N/A"
        if utiliser_ipi and meteo_48h and stade_coef > 0.0:
            jour_max_pluie = max(meteo_48h, key=lambda x: x.get('precipitation', 0) if x else -1)
            if jour_max_pluie and jour_max_pluie.get('precipitation', 0) >= 2:
                duree_humect = self.modele_ipi.estimer_duree_humectation(jour_max_pluie.get('precipitation'),
                                                                         jour_max_pluie.get('humidite'))
                if duree_humect > 0:
                    ipi_value = self.modele_ipi.calculer_ipi(jour_max_pluie, duree_humect)
                    if ipi_value >= 60:
                        ipi_risque = "FORT"
                    elif ipi_value >= 30:
                        ipi_risque = "MOYEN"
                    else:
                        ipi_risque = "FAIBLE"

                    if debug:
                        print("\n🔍 MODE DEBUG - CALCUL IPI")
                        print(f"Jour max pluie: {jour_max_pluie.get('precipitation'):.1f}mm")
                        print(f"Température: {jour_max_pluie.get('temp_moy'):.1f}°C")
                        print(f"Humidité: {jour_max_pluie.get('humidite', 0):.0f}%")
                        print(f"Durée humectation: {duree_humect:.1f}h")
                        print(f"→ IPI: {ipi_value}/100 ({ipi_risque})")
                else:
                    ipi_value = 0; ipi_risque = "FAIBLE (Humect. Nulle)"
            else:
                ipi_value = 0; ipi_risque = "FAIBLE (Pluie Insuff.)"
        elif utiliser_ipi:
            ipi_value = 0
            ipi_risque = "NUL (Repos végétatif)"

        # MODÈLE OÏDIUM
        dates_7j = [(datetime.now() - timedelta(days=i)).strftime('%Y-%m-%d') for i in range(6, -1, -1)]
        meteo_7j = [meteo_historique_complet.get(d, {}) for d in dates_7j]
        risque_oidium, niveau_oidium = self.modele_oidium.calculer_risque_infection(
            meteo_7j, stade_coef
        )

        if debug:
            print("\n🔍 MODE DEBUG - CALCUL OÏDIUM (7 jours)")
            print(f"Coef stade (manuel) appliqué: {stade_coef}")
            print("-" * 50)
            print("Date       | T°Max | Humidité | Pluie | Score Jour")
            print("-" * 50)
            score_total_debug = 0;
            jours_comptes_debug = 0
            for i, jour_meteo in enumerate(meteo_7j):
                date_str = dates_7j[i]
                if not jour_meteo: print(f"{date_str} | Données N/A"); continue
                jours_comptes_debug += 1
                temp_max = jour_meteo.get('temp_max', 0);
                humid = jour_meteo.get('humidite', 0);
                pluie = jour_meteo.get('precipitation', 0)
                daily_score_debug = 0
                if temp_max is not None and temp_max >= 33:
                    daily_score_debug = -2
                elif temp_max is not None and humid is not None and 20 <= temp_max <= 28 and humid >= 60:
                    daily_score_debug = 3
                elif temp_max is not None and humid is not None and 15 <= temp_max <= 30 and humid >= 50:
                    daily_score_debug = 1
                if pluie is not None and pluie >= 5: daily_score_debug -= 1
                daily_score_debug = max(daily_score_debug, -2);
                score_total_debug += daily_score_debug
                print(f"{date_str} | {temp_max:>5.1f}C | {humid:>6.0f}% | {pluie:>5.1f}mm | {daily_score_debug:>4}")
            print("-" * 50);
            print(f"Score total brut: {score_total_debug}")
            max_score_possible_debug = jours_comptes_debug * 3
            if max_score_possible_debug > 0:
                score_norm_debug = (score_total_debug / max_score_possible_debug) * 10
                print(f"Score normalisé (sur 10): {max(0, score_norm_debug):.1f}")
            print(f"→ Score Oïdium Final (avec stade): {risque_oidium}/10 ({niveau_oidium})")

        # ======================================================================
        # --- BLOC : CALCUL GDD (DJC) (Utilise la persistance) ---
        # ======================================================================
        gdd_actuel, stade_estime, prochain_stade_gdd, prochain_stade_nom, mode_calcul = self._calculer_gdd(
            parcelle, self.meteo_historique, date_actuelle, stade_manuel
        )

        alerte_stade, _ = self._predire_stade_futur(
            self.meteo_historique, date_actuelle, gdd_actuel, prochain_stade_gdd, prochain_stade_nom, stade_manuel
        )

        if debug:
            print("\n🔍 MODE DEBUG - CALCUL GDD (DJC)")
            print(f"Date début GDD : {mode_calcul}")
            print(f"GDD Cumulés (Base 10°C) : {gdd_actuel}")
            print(f"Stade Estimé (GDD) : {stade_estime}")
            print(f"Prochain stade : {prochain_stade_nom} (à {prochain_stade_gdd} GDD)")
            print(f"Alerte Prévision : {alerte_stade}")
        # ======================================================================

        # ======================================================================
        # --- BLOC : BILAN HYDRIQUE (Utilise la persistance) ---
        # ======================================================================
        rfu_max_mm = parcelle.get('rfu_max_mm', self.config.parametres.get('rfu_max_mm_default', 100.0))
        kc_calendrier = self.config.parametres.get('kc_calendrier', {})
        f_runoff = self.config.parametres.get('f_runoff', 0.1)
        i_const_mm = self.config.parametres.get('i_const_mm', 1.0)

        bilan_hydrique = self.modele_bilan_hydrique.calculer_bilan_rfu(
            self.meteo_historique, parcelle, stade_manuel,
            kc_calendrier, rfu_max_mm, f_runoff, i_const_mm,
            gdd_cumul_actuel=gdd_actuel,
            debug=debug  # Passe le flag debug
        )
        # ======================================================================

        # PROTECTION ACTUELLE
        protection, dernier_trait, facteur_limitant = self.traitements.calculer_protection_actuelle(
            nom_parcelle, date_actuelle, self.meteo_historique, stade_manuel
        )

        if debug:
            print("\n🔍 MODE DEBUG - PROTECTION")
            print(f"Stade: {parcelle['stade_actuel']}")
            print(f"Coef pousse: {self.traitements.COEF_POUSSE.get(parcelle['stade_actuel'], 1.0)}")
            print(f"→ Protection: {protection}/10 (Limité par: {facteur_limitant})")

        # DÉCISION
        score_decision = risque_simple - protection
        if score_decision >= self.SEUIL_DECISION_HAUTE:
            decision = "TRAITER MAINTENANT (Mildiou)"
            urgence = "haute"
        elif score_decision >= self.SEUIL_DECISION_MOYENNE:
            decision = "Surveiller - Traiter si pluie annoncée (Mildiou)"
            urgence = "moyenne"
        else:
            decision = "Pas de traitement Mildiou nécessaire"
            urgence = "faible"

        alerte_oidium = ""
        if niveau_oidium == "FORT":
            alerte_oidium = "⚠️ RISQUE OÏDIUM FORT - Vérifier protection"
        elif niveau_oidium == "MOYEN":
            alerte_oidium = "🔸 Risque Oïdium MOYEN - Surveillance"

        # PRÉVISIONS
        dates_futures = sorted([d for d in self.meteo_historique.keys() if d > date_actuelle])[:3]
        pluie_prevue = sum(self.meteo_historique.get(d, {}).get('precipitation', 0) for d in dates_futures)
        alerte_preventive = ""
        if pluie_prevue > self.SEUIL_ALERTE_PLUIE and protection < self.SEUIL_PROTECTION_FAIBLE:
            alerte_preventive = f"⚠️  Pluie de {pluie_prevue:.1f}mm prévue - Traitement préventif Mildiou recommandé"

        analyse = {
            'parcelle': nom_parcelle,
            'date_analyse': date_actuelle,
            'cepages': parcelle['cepages'],
            'stade': stade_manuel,
            'meteo_actuelle': self.meteo_historique.get(date_actuelle, {}),

            'gdd': {
                'cumul': gdd_actuel,
                'stade_estime': stade_estime,
                'alerte_stade': alerte_stade,
                'mode_calcul': mode_calcul
            },
            'bilan_hydrique': bilan_hydrique,
            'risque_infection': {
                'score': risque_simple,
                'niveau': niveau_simple,
                'ipi': ipi_value,
                'ipi_niveau': ipi_risque
            },
            'risque_oidium': {
                'score': risque_oidium,
                'niveau': niveau_oidium
            },
            'protection_actuelle': {
                'score': protection,
                'dernier_traitement': dernier_trait,
                'facteur_limitant': facteur_limitant
            },
            'decision': {
                'score': round(score_decision, 1),
                'action': decision,
                'urgence': urgence,
                'alerte_preventive': alerte_preventive,
                'alerte_oidium': alerte_oidium
            },
            'previsions_3j': {
                'pluie_totale': round(pluie_prevue, 1),
                'details': {d: self.meteo_historique.get(d, {}) for d in dates_futures}
            }
        }

        self.historique_analyses.append(
            {'date': date_actuelle, 'parcelle': nom_parcelle, 'risque': risque_simple, 'protection': protection,
             'decision_score': score_decision})
        try:
            self.historique_alertes.ajouter_analyse(analyse)
        except Exception as e:
            print(f"⚠️ Erreur sauvegarde historique : {e}")

        return analyse

    def afficher_rapport(self, analyse: Dict):
        """Affiche un rapport formaté de l'analyse"""
        print("\n" + "=" * 60)
        print(f"   ANALYSE MILDIOU, OÏDIUM & HYDRIQUE - {analyse['parcelle']}")
        print("=" * 60)
        print(f"Date: {analyse['date_analyse']}")
        print(f"Cépages: {', '.join(analyse['cepages'])}")
        print(f"Stade phénologique (Manuel): {analyse['stade']}")

        gdd_info = analyse.get('gdd', {})
        print(f"GDD Cumulés (base 10°C) : {gdd_info.get('cumul', 0):.0f} GDD")
        print(f"   └── Mode de calcul : {gdd_info.get('mode_calcul', 'N/A')}")
        print(f"Stade estimé (GDD) : {gdd_info.get('stade_estime', 'N/A')}")
        if gdd_info.get('alerte_stade'):
            print(f"   └── {gdd_info.get('alerte_stade')}")

        print("-" * 60)
        meteo = analyse['meteo_actuelle']
        print(f"\n🌡️  MÉTÉO ACTUELLE")
        print(f"   Température: {meteo.get('temp_min', 'N/A')}°C - {meteo.get('temp_max', 'N/A')}°C")
        print(f"   Précipitations: {meteo.get('precipitation', 0):.1f} mm")
        print(f"   Humidité: {meteo.get('humidite', 'N/A'):.0f}%")
        print(f"   ETP (Évap.) : {meteo.get('etp0', 'N/A'):.1f} mm")

        risque_m = analyse['risque_infection']
        print(f"\n🦠 RISQUE MILDIOU: {risque_m['niveau']}")
        print(f"   Score modèle simple: {risque_m['score']}/10")
        if risque_m['ipi'] is not None:
            print(f"   IPI: {risque_m['ipi']}/100 ({risque_m['ipi_niveau']})")

        risque_o = analyse.get('risque_oidium', {})
        print(f"\n🍄 RISQUE OÏDIUM: {risque_o.get('niveau', 'N/A')}")
        print(f"   Score modèle Oïdium: {risque_o.get('score', 0)}/10")

        bilan_h = analyse.get('bilan_hydrique', {})
        print(f"\n💧 BILAN HYDRIQUE: {bilan_h.get('niveau', 'N/A')}")
        print(
            f"   Réserve Utile (RFU) : {bilan_h.get('rfu_pct', 0)}% ({bilan_h.get('rfu_mm', 0)} / {bilan_h.get('rfu_max_mm', 0)} mm)")
        print(f"   Indice de Stress (Ks) : {bilan_h.get('ks_actuel', 1.0)}")

        prot = analyse['protection_actuelle']
        print(f"\n🛡️  PROTECTION ACTUELLE: {prot['score']}/10")
        if prot['dernier_traitement']:
            dt = prot['dernier_traitement']
            print(f"   Dernier traitement: {dt['date']}")
            print(f"   Produit: {dt['caracteristiques'].get('nom', 'N/A')}")
            print(f"   Facteur limitant: {prot['facteur_limitant']}")
        else:
            print("   Aucun traitement enregistré.")

        dec = analyse['decision']
        print(f"\n{'=' * 60}")
        print(f"➜  DÉCISION: {dec['action']}")
        print(f"   Score décision (Mildiou): {dec['score']}/10")
        if dec['alerte_preventive']:
            print(f"\n   {dec['alerte_preventive']}")
        if dec['alerte_oidium']:
            print(f"   {dec['alerte_oidium']}")
        if bilan_h.get('niveau') == "STRESS FORT":
            print(f"   💧 ALERTE STRESS HYDRIQUE FORT ({bilan_h.get('rfu_pct')}%)")
        print("=" * 60)
        prev = analyse['previsions_3j']
        print(f"\n📅 PRÉVISIONS 3 JOURS")
        print(f"   Cumul pluie prévu: {prev['pluie_totale']} mm")
        print()

    def generer_graphique_evolution(self, parcelle: str, nb_jours: int = 30,
                                    fichier_sortie: str = 'evolution_risque.png'):
        if not GRAPHIQUES_DISPONIBLES:
            print("⚠️  matplotlib non installé. Graphiques non disponibles.")
            return

        meteo_dict_daily = self.meteo_historique

        dates, risques, protections = [], [], []
        date_fin = datetime.now()

        parcelle_obj = next((p for p in self.config.parcelles if p['nom'] == parcelle), None)
        if not parcelle_obj:
            print(f"❌ Parcelle {parcelle} non trouvée pour graphique.")
            return

        for i in range(nb_jours, -1, -1):
            date_dt = date_fin - timedelta(days=i)
            date = date_dt.strftime('%Y-%m-%d')

            if date not in meteo_dict_daily:
                continue

            dates.append(date_dt)

            meteo_48h = []
            for j in range(3):
                d = (date_dt - timedelta(days=2 - j)).strftime('%Y-%m-%d')
                if d in meteo_dict_daily: meteo_48h.append(meteo_dict_daily.get(d, {}))

            sensibilites = [self.config.SENSIBILITES_CEPAGES.get(c, 5) for c in parcelle_obj['cepages']]
            sensibilite_moy = sum(sensibilites) / len(sensibilites)
            stade_coef = self.config.COEF_STADES.get(parcelle_obj['stade_actuel'], 1.0)
            risque, _ = self.modele_simple.calculer_risque_infection(meteo_48h, stade_coef, sensibilite_moy)
            protection, _, _ = self.traitements.calculer_protection_actuelle(parcelle, date, meteo_dict_daily,
                                                                             parcelle_obj['stade_actuel'])
            risques.append(risque)
            protections.append(protection)

        if not dates:
            print("❌ Aucune donnée à tracer pour le graphique (vérifiez l'historique météo).")
            return

        fig, ax = plt.subplots(figsize=(12, 6))
        ax.plot(dates, risques, 'r-', linewidth=2, label='Risque infection', marker='o')
        ax.plot(dates, protections, 'g-', linewidth=2, label='Protection', marker='s')
        ax.axhline(y=self.SEUIL_DECISION_HAUTE, color='orange', linestyle='--',
                   label=f'Seuil traitement ({self.SEUIL_DECISION_HAUTE}/10)')
        ax.fill_between(dates, 0, risques, alpha=0.2, color='red')
        ax.fill_between(dates, 0, protections, alpha=0.2, color='green')
        ax.set_xlabel('Date', fontsize=12);
        ax.set_ylabel('Score (0-10)', fontsize=12)
        ax.set_title(f'Évolution Risque/Protection - {parcelle}', fontsize=14, fontweight='bold')
        ax.legend(loc='best', fontsize=10);
        ax.grid(True, alpha=0.3)
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%d/%m'))
        ax.xaxis.set_major_locator(mdates.DayLocator(interval=max(1, nb_jours // 10)))
        plt.xticks(rotation=45);
        plt.tight_layout()
        plt.savefig(fichier_sortie, dpi=150)
        print(f"✅ Graphique sauvegardé : {fichier_sortie}");
        plt.close()

    def exporter_analyses_csv(self, fichier: str = 'historique_analyses.csv'):
        if not self.historique_analyses:
            print("⚠️  Aucune analyse à exporter");
            return
        with open(fichier, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=['date', 'parcelle', 'risque', 'protection', 'decision_score'])
            writer.writeheader();
            writer.writerows(self.historique_analyses)
        print(f"✅ Historique exporté : {fichier}")

    def generer_synthese_annuelle(self, annee: int, fichier_sortie: str = None):
        if fichier_sortie is None: fichier_sortie = f'synthese_{annee}.txt'
        date_debut = f"{annee}-01-01";
        date_fin = f"{annee}-12-31"
        ift = self.traitements.calculer_ift_periode(date_debut, date_fin, self.config.surface_totale)
        stats_parcelles = {}
        for parcelle in self.config.parcelles:
            traitements_parcelle = [t for t in self.traitements.historique['traitements'] if
                                    t['parcelle'] == parcelle['nom'] and date_debut <= t['date'] <= date_fin]
            stats_parcelles[parcelle['nom']] = {'nb_traitements': len(traitements_parcelle),
                                                'surface_ha': parcelle['surface_ha'], 'cepages': parcelle['cepages']}
        with open(fichier_sortie, 'w', encoding='utf-8') as f:
            f.write("=" * 70 + "\n");
            f.write(f"   SYNTHÈSE ANNUELLE MILDIOU - {annee}\n");
            f.write(f"   {self.config.config_file.replace('.json', '').upper()}\n");
            f.write("=" * 70 + "\n\n")
            f.write(f"📊 DONNÉES GÉNÉRALES\n");
            f.write(f"   Surface totale : {self.config.surface_totale} ha\n");
            f.write(f"   Nombre de parcelles : {len(self.config.parcelles)}\n");
            f.write(f"   Période d'analyse : {date_debut} au {date_fin}\n\n")
            f.write(f"💊 BILAN TRAITEMENTS\n");
            f.write(f"   Nombre total de traitements : {ift['nb_traitements']}\n");
            f.write(f"   IFT total : {ift['ift_total']}\n");
            f.write(f"   IFT moyen par hectare : {ift['ift_total'] / self.config.surface_totale:.2f}\n\n")
            f.write(f"📋 DÉTAIL PAR PARCELLE\n");
            f.write("-" * 70 + "\n")
            for nom, stats in stats_parcelles.items():
                f.write(f"\n🍇 {nom}\n");
                f.write(f"   Surface : {stats['surface_ha']} ha\n");
                f.write(f"   Cépages : {', '.join(stats['cepages'])}\n");
                f.write(f"   Traitements : {stats['nb_traitements']}\n");
                ift_parcelle = stats['nb_traitements'];
                f.write(f"   IFT estimé : {ift_parcelle}\n")
            f.write("\n" + "-" * 70 + "\n");
            f.write(f"📅 HISTORIQUE DES TRAITEMENTS\n");
            f.write("-" * 70 + "\n")
            for detail in ift['details']:
                f.write(f"\n{detail['date']} - {detail['parcelle']}\n");
                f.write(f"   Produit : {detail['produit']}\n");
                f.write(f"   IFT : {detail['ift']}\n")
            f.write("\n" + "=" * 70 + "\n");
            f.write(f"💡 RECOMMANDATIONS\n");
            f.write("=" * 70 + "\n")
            if ift['ift_total'] > 15:
                f.write("⚠️  IFT élevé : Envisager des stratégies de réduction\n");
                f.write("   - Optimiser le positionnement des traitements\n");
                f.write("   - Privilégier les produits longue rémanence\n");
                f.write("   - Évaluer les cépages résistants\n")
            elif ift['ift_total'] < 8:
                f.write("✅ IFT maîtrisé : Bonne gestion phytosanitaire\n")
            else:
                f.write("✓  IFT dans la moyenne nationale\n")
            f.write("\n" + "=" * 70 + "\n");
            f.write(f"Rapport généré le {datetime.now().strftime('%d/%m/%Y à %H:%M')}\n");
            f.write("=" * 70 + "\n")
        print(f"✅ Synthèse annuelle générée : {fichier_sortie}")
        with open(fichier_sortie, 'r', encoding='utf-8') as f:
            print("\n" + f.read())


def menu_maj_stade_et_date(systeme):
    """Menu interactif pour mettre à jour le stade et la date de débourrement (Biofix)."""
    print("\n📅 MISE À JOUR STADE / DATE DÉBOURREMENT")
    print("-" * 70)

    print("\nParcelles disponibles :")
    parcelles = systeme.config.parcelles
    parcelles_noms = [p['nom'] for p in parcelles]
    for i, p in enumerate(parcelles, 1):
        biofix_date = f" (Biofix GDD: {p.get('date_debourrement')})" if p.get('date_debourrement') else ""
        print(f" {i}. {p['nom']} (Stade actuel: {p['stade_actuel']}){biofix_date}")

    try:
        parcelle_idx = int(input("\n➜ Numéro de la parcelle à mettre à jour : ")) - 1
        parcelle_choisie = parcelles_noms[parcelle_idx]
    except (ValueError, IndexError):
        print("❌ Entrée invalide.")
        return

    stades_noms = list(systeme.config.COEF_STADES.keys())
    print("\nStades disponibles :")
    for i, s_nom in enumerate(stades_noms, 1):
        print(f" {i}. {s_nom}")

    try:
        stade_idx = int(input("\n➜ Numéro du nouveau stade : ")) - 1
        nouveau_stade = stades_noms[stade_idx]
    except (ValueError, IndexError):
        print("❌ Entrée invalide.")
        return

    date_debourrement = None
    if nouveau_stade == 'debourrement':
        date_input = input(f"Date d'observation du DÉBOURREMENT (AAAA-MM-JJ) ou [Entrée]=Aujourd'hui : ").strip()
        if date_input:
            try:
                datetime.strptime(date_input, '%Y-%m-%d')
                date_debourrement = date_input
            except ValueError:
                print("❌ Format de date invalide. Utilisation de la date du jour.")
                date_debourrement = datetime.now().strftime('%Y-%m-%d')
        else:
            date_debourrement = datetime.now().strftime('%Y-%m-%d')

    systeme.config.update_parcelle_stade_et_date(parcelle_choisie, nouveau_stade, date_debourrement)


def menu_principal():
    """Menu interactif principal"""
    systeme = SystemeDecision()
    while True:
        print("\n" + "=" * 70);
        print("🍇 SYSTÈME DE PRÉVISION MILDIOU & OÏDIUM - MENU PRINCIPAL");
        print("=" * 70)
        print("\n1️⃣  Analyser toutes les parcelles")
        print("2️⃣  Analyser une parcelle spécifique")
        print("3️⃣  Enregistrer un traitement")
        print("4️⃣  Générer graphique d'évolution")
        print("5️⃣  Mettre à jour stade / Date Débourrement (Biofix)")
        print("6️⃣  Calculer IFT d'une période")
        print("7️⃣  Générer synthèse annuelle")
        print("8️⃣  Liste des fongicides disponibles")
        print("9️⃣  Quitter")

        choix = input("\n➜ Votre choix (1-9) : ").strip()

        if choix == '1':
            print("\n" + "=" * 70);
            print("📊 ANALYSE DE TOUTES LES PARCELLES");
            print("=" * 70)
            for parcelle in systeme.config.parcelles:
                analyse = systeme.analyser_parcelle(parcelle['nom'], utiliser_ipi=True)
                if 'erreur' not in analyse:
                    systeme.afficher_rapport(analyse)
                else:
                    print(f"❌ {analyse['erreur']}")
        elif choix == '2':
            print("\n📍 Parcelles disponibles :")
            for i, p in enumerate(systeme.config.parcelles, 1): print(f"   {i}. {p['nom']}")
            try:
                idx = int(input("\n➜ Numéro de la parcelle : ")) - 1
                parcelle = systeme.config.parcelles[idx]
                debug = input("Mode debug ? (o/n) : ").lower() == 'o'
                analyse = systeme.analyser_parcelle(parcelle['nom'], utiliser_ipi=True, debug=debug)
                if 'erreur' not in analyse:
                    systeme.afficher_rapport(analyse)
                else:
                    print(f"❌ {analyse['erreur']}")
            except (ValueError, IndexError):
                print("❌ Choix invalide")
        elif choix == '3':
            print("\n💊 ENREGISTREMENT D'UN TRAITEMENT");
            print("-" * 70);
            print("\nParcelles disponibles :")
            for i, p in enumerate(systeme.config.parcelles, 1): print(f"   {i}. {p['nom']}")
            try:
                idx = int(input("\n➜ Numéro de la parcelle : ")) - 1
                parcelle = systeme.config.parcelles[idx]['nom']
                date = input("Date du traitement (YYYY-MM-DD) ou [Entrée]=aujourd'hui : ").strip()
                if not date: date = datetime.now().strftime('%Y-%m-%d')
                print("\nProduits disponibles :")
                produits = list(systeme.traitements.FONGICIDES.keys())
                for i, p in enumerate(produits, 1): print(f"   {i}. {systeme.traitements.FONGICIDES[p]['nom']}")
                prod_idx = int(input("\n➜ Numéro du produit : ")) - 1
                produit = produits[prod_idx]
                dose = input(f"Dose (kg/ha) ou [Entrée]=dose référence : ").strip()
                dose = float(dose) if dose else None
                systeme.traitements.ajouter_traitement(parcelle, date, produit, dose)
            except (ValueError, IndexError):
                print("❌ Entrée invalide")
        elif choix == '4':
            if not GRAPHIQUES_DISPONIBLES: print("\n❌ matplotlib non installé"); print(
                "   Installation : pip install matplotlib"); continue
            print("\n📈 GÉNÉRATION DE GRAPHIQUE");
            print("-" * 70);
            print("\nParcelles disponibles :")
            for i, p in enumerate(systeme.config.parcelles, 1): print(f"   {i}. {p['nom']}")
            try:
                idx = int(input("\n➜ Numéro de la parcelle : ")) - 1
                parcelle = systeme.config.parcelles[idx]['nom']
                nb_jours = input("Nombre de jours (défaut=30) : ").strip()
                nb_jours = int(nb_jours) if nb_jours else 30
                fichier = f"evolution_{parcelle.replace(' ', '_')}.png"
                systeme.generer_graphique_evolution(parcelle, nb_jours, fichier)
            except (ValueError, IndexError):
                print("❌ Entrée invalide")

        elif choix == '5':
            menu_maj_stade_et_date(systeme)

        elif choix == '6':
            print("\n📊 CALCUL IFT");
            print("-" * 70)
            date_debut = input("Date début (YYYY-MM-DD) : ").strip()
            date_fin = input("Date fin (YYYY-MM-DD) : ").strip()
            if date_debut and date_fin:
                ift = systeme.traitements.calculer_ift_periode(date_debut, date_fin, systeme.config.surface_totale)
                print(f"\n{'=' * 70}");
                print(f"IFT PÉRIODE : {ift['periode']}");
                print(f"{'=' * 70}")
                print(f"IFT total : {ift['ift_total']}");
                print(f"IFT moyen/ha : {ift['ift_total'] / systeme.config.surface_totale:.2f}");
                print(f"Nombre de traitements : {ift['nb_traitements']}")
                if ift['details']:
                    print(f"\nDétail :");
                    for d in ift['details']: print(
                        f"  {d['date']} - {d['parcelle']} - {d['produit']} (IFT: {d['ift']})")

        elif choix == '7':
            print("\n📑 SYNTHÈSE ANNUELLE");
            print("-" * 70)
            annee = input(f"Année (défaut={datetime.now().year}) : ").strip()
            annee = int(annee) if annee else datetime.now().year
            systeme.generer_synthese_annuelle(annee)

        elif choix == '8':
            print("\n💊 FONGICIDES DISPONIBLES");
            print("=" * 70)
            for code, info in systeme.traitements.FONGICIDES.items():
                print(f"\n🔹 {info['nom']}");
                print(f"   Code : {code}");
                print(f"   Type : {info['type']}")
                print(f"   Persistance : {info['persistance_jours']} jours");
                print(f"   Seuil lessivage : {info['lessivage_seuil_mm']} mm");
                print(f"   Dose référence : {info['dose_reference_kg_ha']} kg/ha")

        elif choix == '9':
            print("\n👋 Au revoir et bonnes vendanges !");
            break

        else:
            print("\n❌ Choix invalide")

        input("\n[Appuyez sur Entrée pour continuer]")


if __name__ == "__main__":
    menu_principal()