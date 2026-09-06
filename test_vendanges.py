import pytest
import os
import json
import importlib
import pandas as pd
from unittest.mock import MagicMock, patch

# Dynamically import pages/3_Vendanges.py and storage.py
vendanges_module = importlib.import_module("pages.3_Vendanges")
storage_module = importlib.import_module("storage")
GestionVendanges = vendanges_module.GestionVendanges
DataManager = storage_module.DataManager


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
                    "prix_hl_deg_vdp": 6.2837,
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
        "prix_hl_deg_vdp": 6.2837,
        "prix_hl_deg_vdt": 5.2713,
        "rendement_theorique": 73.0
    }

    # Ticket 1: 7560 kg, 12.1° (>= 10.5 -> VDP)
    m1 = gv.calculer_metriques_ticket(7560, 12.1, params)
    assert m1['categorie'] == "VDP"
    assert abs(m1['volume_hl'] - 55.188) < 1e-4  # 55.188 hL
    expected_hl_deg = 7560 * 12.1 * 0.73 / 100  # 667.7748
    assert abs(m1['hl_degres'] - expected_hl_deg) < 1e-4
    assert m1['prix_unitaire_applique'] == 6.2837
    assert abs(m1['montant_estime_eur'] - (expected_hl_deg * 6.2837)) < 1e-4


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

        # Volume Jus total = 20 940 * 0.73 / 100 = 152.862 hL (15 286.2 L)
        assert totaux['volume_total_hl'] == pytest.approx(152.862, rel=1e-4)
        assert totaux['production_litres'] == pytest.approx(15286.2, rel=1e-4)

        # Hl° attendu = (251 382 kg° * 73%) / 100 = 1835.0886 Hl°
        assert totaux['hl_degres_total'] == pytest.approx(1835.0886, rel=1e-4)

        # CA brut VDP @ 6.2837 € = 1835.0886 * 6.2837 = 11 531.336... €
        expected_ca_brut = 1835.0886 * 6.2837
        assert totaux['ca_brut'] == pytest.approx(expected_ca_brut, rel=1e-4)

        # Primes et Frais
        expected_prime = 0.0847 * 20940  # 1773.618 €
        expected_frais = 0.1573 * 20940  # 3293.862 €
        assert totaux['prime_total'] == pytest.approx(expected_prime, rel=1e-4)
        assert totaux['frais_total'] == pytest.approx(expected_frais, rel=1e-4)

        # Revenu Net
        expected_net = expected_ca_brut + expected_prime - expected_frais
        assert totaux['revenu_net'] == pytest.approx(expected_net, rel=1e-4)


def test_gsheets_separation_vendanges_et_tickets():
    dm = DataManager.__new__(DataManager)
    data = {
        'campagnes': [
            {
                'annee': 2025,
                'status': 'en_cours',
                'parametres': {'rendement_theorique': 73.0, 'prix_u': 100.0, 'prime_u': 0.0847, 'frais_vinif_u': 0.1573, 'prix_hl_deg_vdp': 6.2837, 'prix_hl_deg_vdt': 5.2713},
                'surface_vendangee': {'total_ha': 2.05, 'notes': ''},
                'validation': {'validee': False},
                'tickets': [
                    {'id': 1, 'date': '2025-09-15', 'num_ticket': 'B001', 'poids_kg': 7560, 'degre': 12.1, 'categorie': 'VDP', 'volume_hl': 55.188, 'hl_degres': 667.77, 'montant_estime_eur': 4196.0}
                ]
            }
        ]
    }

    # Verify campaign df (for 'vendanges' tab)
    df_camp = dm._json_to_df('vendanges', data)
    assert len(df_camp) == 1
    assert 'annee' in df_camp.columns
    assert 'prix_hl_deg_vdp' in df_camp.columns
    assert 'num_ticket' not in df_camp.columns  # No tickets in vendanges tab!

    # Verify tickets df (for 'tickets' tab)
    df_tick = dm._json_to_df('tickets', data)
    assert len(df_tick) == 1
    assert df_tick.iloc[0]['annee'] == 2025
    assert df_tick.iloc[0]['num_ticket'] == 'B001'
    assert df_tick.iloc[0]['poids_kg'] == 7560
