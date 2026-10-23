import pytest
from mildiou_prevention import ConfigVignoble, ModeleSimple, ModeleIPI, SystemeDecision

def test_coef_stades_veraison_maturite():
    assert ConfigVignoble.COEF_STADES['veraison'] == 0.4
    assert ConfigVignoble.COEF_STADES['maturite'] == 0.05

def test_modele_simple_thermal_kill_switch():
    meteo_normal = [
        {'precipitation': 12, 'temp_moy': 22, 'humidite': 80, 'temp_max': 28},
        {'precipitation': 0, 'temp_moy': 22, 'humidite': 70, 'temp_max': 29}
    ]
    score_normal, _ = ModeleSimple.calculer_risque_infection(meteo_normal, stade_coef=1.0, sensibilite_cepage=5.0)

    # 32°C kill switch (-2 points base)
    meteo_32 = [
        {'precipitation': 12, 'temp_moy': 22, 'humidite': 80, 'temp_max': 32},
        {'precipitation': 0, 'temp_moy': 22, 'humidite': 70, 'temp_max': 29}
    ]
    score_32, _ = ModeleSimple.calculer_risque_infection(meteo_32, stade_coef=1.0, sensibilite_cepage=5.0)
    assert score_normal - score_32 == 2.0

    # 35°C kill switch (-5 points base)
    meteo_35 = [
        {'precipitation': 12, 'temp_moy': 22, 'humidite': 80, 'temp_max': 35},
        {'precipitation': 0, 'temp_moy': 22, 'humidite': 70, 'temp_max': 29}
    ]
    score_35, _ = ModeleSimple.calculer_risque_infection(meteo_35, stade_coef=1.0, sensibilite_cepage=5.0)
    assert score_normal - score_35 == 5.0

def test_modele_ipi_thermal_kill_switch():
    event_35 = {'temp_moy': 20, 'temp_max': 35, 'humidite': 85, 'precipitation': 15}
    ipi = ModeleIPI.calculer_ipi(event_35, duree_humectation_estimee=10)
    assert ipi == 0

def test_systeme_decision_ipi_weighting():
    sys_dec = SystemeDecision()
    sys_dec.meteo_historique = {
        '2025-08-01': {'precipitation': 10, 'temp_moy': 22, 'temp_max': 28, 'humidite': 90},
        '2025-08-02': {'precipitation': 5, 'temp_moy': 22, 'temp_max': 28, 'humidite': 90},
        '2025-08-03': {'precipitation': 0, 'temp_moy': 22, 'temp_max': 28, 'humidite': 80}
    }
    # Test with veraison stage_coef = 0.4
    res = sys_dec.analyser_parcelle(sys_dec.config.parcelles[0]['nom'], utiliser_ipi=True, debug=False, sauvegarder_historique=False)
    assert 'erreur' not in res

def test_kc_stades_mapping():
    assert ConfigVignoble.KC_STADES['repos'] == 0.1
    assert ConfigVignoble.KC_STADES['pointe_verte'] == 0.2
    assert ConfigVignoble.KC_STADES['floraison'] == 0.8
    assert ConfigVignoble.KC_STADES['veraison'] == 0.5
    assert ConfigVignoble.KC_STADES['maturite'] == 0.3

def test_calculer_gdd_recalibration():
    sys_dec = SystemeDecision()
    parcelle = {'nom': 'Test', 'date_debourrement': None}
    meteo = {}
    date_actuelle = '2025-06-01'

    # With manual stage 'floraison'
    gdd_sum, stade_estime, prochain_gdd, prochain_nom, mode = sys_dec._calculer_gdd(
        parcelle, meteo, date_actuelle, stade_manuel='floraison'
    )
    assert gdd_sum == 660
    assert stade_estime == 'floraison'
    assert prochain_nom == 'nouaison'
    assert prochain_gdd == 820
    assert mode == "Recalibré sur observation (floraison)"

    # With manual stage 'repos'
    gdd_sum, stade_estime, _, _, mode = sys_dec._calculer_gdd(
        parcelle, meteo, date_actuelle, stade_manuel='repos'
    )
    assert gdd_sum == 0
    assert stade_estime == 'repos'

def test_bilan_rfu_kc_today():
    from mildiou_prevention import ModeleBilanHydrique
    from datetime import datetime

    today_str = datetime.now().strftime('%Y-%m-%d')
    meteo = {
        today_str: {'precipitation': 0.0, 'etp0': 4.0, 'gdd_jour': 10.0}
    }
    parcelle = {'nom': 'Test', 'rfu_max_mm': 100.0}

    # Bilan RFU with 'floraison' (KC_STADES['floraison'] = 0.8)
    res = ModeleBilanHydrique.calculer_bilan_rfu(
        meteo_historique=meteo,
        parcelle=parcelle,
        stade_manuel='floraison',
        kc_calendrier={},
        rfu_max_mm=100.0,
        f_runoff=0.1,
        i_const_mm=1.0,
        gdd_cumul_actuel=660.0
    )
    # ETc = Kc * etp0 * ks = 0.8 * 4.0 * 1.0 = 3.2
    # rfu_actuelle = 100.0 - 3.2 = 96.8
    assert res['rfu_mm'] == 96.8
