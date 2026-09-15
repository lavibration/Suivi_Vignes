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
