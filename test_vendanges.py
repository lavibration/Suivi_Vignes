import pytest
import os
import json
import importlib
import pandas as pd
from unittest.mock import MagicMock, patch

# Dynamically import pages/3_Vendanges.py
vendanges_module = importlib.import_module("pages.3_Vendanges")
GestionVendanges = vendanges_module.GestionVendanges


@pytest.fixture
def temp_vendanges_file(tmp_path):
    """Fixture providing an isolated test JSON file for GestionVendanges"""
    file_path = tmp_path / "test_vendanges.json"
    data = {
        "campagnes": [
            {
                "annee": 2025,
                "status": "en_cours",
                "tickets": [],
                "parametres": {
                    "rendement_theorique": 73.0,
                    "prix_u": 100.0,
                    "frais_vinif_u": 0.1573,
                    "prime_u": 0.0847,
                    "prix_hl_deg_vdp": 6.28,
                    "prix_hl_deg_vdt": 5.2713
                },
                "surface_vendangee": {
                    "total_ha": 2.05,
                    "notes": ""
                },
                "validation": {
                    "validee": False,
                    "hl_reel": None,
                    "prix_u_reel": None,
                    "frais_reels": None,
                    "prime_reelle": None,
                    "date_validation": None
                },
                "parcelles_vendangees": []
            }
        ]
    }
    file_path.write_text(json.dumps(data), encoding='utf-8')
    return file_path


def test_categorisation_et_calculs_ticket():
    gv = GestionVendanges.__new__(GestionVendanges)
    params = {
        "prix_hl_deg_vdp": 6.28,
        "prix_hl_deg_vdt": 5.2713,
        "rendement_theorique": 73.0
    }

    # Ticket 1: 7560 kg, 12.1° (>= 10.5 -> VDP)
    m1 = gv.calculer_metriques_ticket(7560, 12.1, params)
    assert m1['categorie'] == "VDP"
    assert abs(m1['volume_hl'] - (7560 * 0.73 / 100)) < 1e-4  # 55.188 hL
    expected_hl_deg = (7560 * 12.1 * 0.73) / 100  # 667.7748
    assert abs(m1['hl_degres'] - expected_hl_deg) < 1e-4
    assert m1['prix_unitaire_applique'] == 6.28
    assert abs(m1['montant_estime_eur'] - (expected_hl_deg * 6.28)) < 1e-4


def test_tickets_2025_et_totaux_campagne(temp_vendanges_file):
    with patch('storage.DataManager.load_data') as mock_load, \
         patch('storage.DataManager.save_data') as mock_save:

        with open(temp_vendanges_file, 'r', encoding='utf-8') as f:
            initial_data = json.load(f)

        mock_load.return_value = initial_data

        gv = GestionVendanges(fichier='test_vendanges')

        # 5 tickets de test 2025 de l'utilisateur
        tickets_2025 = [
            {'poids_kg': 7560, 'degre': 12.1},
            {'poids_kg': 2050, 'degre': 11.6},
            {'poids_kg': 6600, 'degre': 12.5},
            {'poids_kg': 2280, 'degre': 11.7},
            {'poids_kg': 2450, 'degre': 11.0}
        ]

        for idx, t in enumerate(tickets_2025):
            t['notes'] = f'Benne {idx+1}'
            gv.ajouter_ticket("2025-09-15", t)

        totaux = gv.calculer_totaux(2025)

        assert totaux['nb_tickets'] == 5
        assert totaux['poids_total'] == 20940
        assert totaux['degre_moyen'] == pytest.approx(12.00487, rel=1e-4)

        # Hl° attendu = (20940 kg * 12.00487° * 73%) / 100 = 1835.0886 Hl°
        expected_hl_degres = (251382 * 0.73) / 100
        assert totaux['hl_degres_total'] == pytest.approx(1835.0886, rel=1e-4)
        assert totaux['hl_degres_vdp'] == pytest.approx(1835.0886, rel=1e-4)

        # CA brut VDP @ 6.28 €
        expected_ca_brut = 1835.0886 * 6.28
        assert totaux['ca_brut'] == pytest.approx(expected_ca_brut, rel=1e-4)

        # Primes et Frais
        expected_prime = 0.0847 * 20940  # 1773.618 €
        expected_frais = 0.1573 * 20940  # 3293.862 €
        assert totaux['prime_total'] == pytest.approx(expected_prime, rel=1e-4)
        assert totaux['frais_total'] == pytest.approx(expected_frais, rel=1e-4)

        # Revenu Net
        expected_net = expected_ca_brut + expected_prime - expected_frais
        assert totaux['revenu_net'] == pytest.approx(expected_net, rel=1e-4)

        # Prix au litre
        prod_litres = 20940 * 0.73  # 15286.2 L
        assert totaux['production_litres'] == pytest.approx(prod_litres, rel=1e-4)
        assert totaux['euro_par_litre'] == pytest.approx(expected_net / prod_litres, rel=1e-4)
