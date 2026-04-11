from mildiou_prevention import SystemeDecision, ModeleSimple
import json
from datetime import datetime, timedelta

def test_risk():
    # Mock data based on user report
    # Pluie 48h: 41.1mm , Temp moyenne 48h: 10.2°C , Coef stade: 0.8 , Sensibilité cépages: 6.0
    # We want to see how we get 4.8

    meteo_48h = [
        {'precipitation': 41.1, 'temp_moy': 10.2, 'humidite': 80},
        {'precipitation': 0, 'temp_moy': 10.2, 'humidite': 80}
    ]

    stade_coef = 0.8
    sensibilite = 6.0

    score, niveau = ModeleSimple.calculer_risque_infection(meteo_48h, stade_coef, sensibilite)
    print(f"Calculated Score: {score}, Niveau: {niveau}")

    # Let's check with stade_coef = 0.4 (pointe_verte)
    score_pv, niveau_pv = ModeleSimple.calculer_risque_infection(meteo_48h, 0.4, sensibilite)
    print(f"Calculated Score (pointe_verte): {score_pv}, Niveau: {niveau_pv}")

def test_gdd():
    systeme = SystemeDecision()
    # Mock a parcel that was just set to pointe_verte
    parcelle = {
        "nom": "Test",
        "stade_actuel": "pointe_verte",
        "date_debourrement": "2026-04-11"
    }

    # Mock meteo_historique
    date_actuelle = "2026-04-11"
    meteo_historique = {
        "2026-04-11": {"gdd_jour": 2.0}
    }

    gdd_actuel, stade_estime, prochain_stade_gdd, prochain_stade_nom, mode_calcul = systeme._calculer_gdd(
        parcelle, meteo_historique, date_actuelle, "pointe_verte"
    )

    print(f"GDD Actual: {gdd_actuel}")
    print(f"Stade Estime: {stade_estime}")
    print(f"Mode Calcul: {mode_calcul}")

if __name__ == "__main__":
    print("--- Risk Test ---")
    test_risk()
    print("\n--- GDD Test ---")
    test_gdd()
