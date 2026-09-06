import pytest
import os
import json
import importlib
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
                "annee": 2026,
                "status": "en_cours",
                "tickets": [],
                "parametres": {
                    "rendement_theorique": 73.0,
                    "prix_u": 100.0,
                    "frais_vinif_u": 15.73,
                    "prime_u": 0.0,
                    "prix_hl_deg_vdp": 6.28,
                    "prix_hl_deg_vdt": 5.2713,
                    "ratio_kg_hl": 130.0
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
        "ratio_kg_hl": 130.0
    }

    # Ticket 1: degre = 11.2 (>= 10.5 -> VDP)
    m1 = gv.calculer_metriques_ticket(5050, 11.2, params)
    assert m1['categorie'] == "VDP"
    assert m1['volume_hl'] == round(5050 / 130.0, 2)  # 38.85
    assert abs(m1['hl_degres'] - (38.85 * 11.2)) < 1e-4  # 435.12
    assert m1['prix_unitaire_applique'] == 6.28
    assert abs(m1['montant_estime_eur'] - (38.85 * 11.2 * 6.28)) < 1e-4

    # Ticket 2: degre = 10.1 (< 10.5 -> VDT)
    m2 = gv.calculer_metriques_ticket(1240, 10.1, params)
    assert m2['categorie'] == "VDT"
    assert m2['volume_hl'] == round(1240 / 130.0, 2)  # 9.54
    assert abs(m2['hl_degres'] - (9.54 * 10.1)) < 1e-4  # 96.354
    assert m2['prix_unitaire_applique'] == 5.2713
    assert abs(m2['montant_estime_eur'] - (9.54 * 10.1 * 5.2713)) < 1e-4


def test_ajouter_ticket_et_totaux_campagne(temp_vendanges_file):
    with patch('storage.DataManager.load_data') as mock_load, \
         patch('storage.DataManager.save_data') as mock_save:

        with open(temp_vendanges_file, 'r', encoding='utf-8') as f:
            initial_data = json.load(f)

        mock_load.return_value = initial_data

        gv = GestionVendanges(fichier='test_vendanges')

        # Ticket 1: VDP (5050 kg, 11.2°)
        t1 = {'poids_kg': 5050, 'degre': 11.2, 'notes': 'Benne 1'}
        success, msg = gv.ajouter_ticket("2026-09-10", t1)
        assert success is True

        # Ticket 2: VDT (1240 kg, 10.1°)
        t2 = {'poids_kg': 1240, 'degre': 10.1, 'notes': 'Benne 2'}
        success, msg = gv.ajouter_ticket("2026-09-11", t2)
        assert success is True

        totaux = gv.calculer_totaux(2026)

        assert totaux['nb_tickets'] == 2
        assert totaux['poids_total'] == 6290
        assert totaux['poids_vdp'] == 5050
        assert totaux['poids_vdt'] == 1240

        expected_deg_moyen = (5050 * 11.2 + 1240 * 10.1) / 6290
        assert abs(totaux['degre_moyen'] - expected_deg_moyen) < 1e-4

        vol_vdp = round(5050 / 130.0, 2)  # 38.85
        vol_vdt = round(1240 / 130.0, 2)  # 9.54
        assert totaux['volume_vdp_hl'] == vol_vdp
        assert totaux['volume_vdt_hl'] == vol_vdt
        assert totaux['volume_total_hl'] == round(vol_vdp + vol_vdt, 2)

        hl_deg_vdp = vol_vdp * 11.2
        hl_deg_vdt = vol_vdt * 10.1
        assert abs(totaux['hl_degres_vdp'] - hl_deg_vdp) < 1e-4
        assert abs(totaux['hl_degres_vdt'] - hl_deg_vdt) < 1e-4
        assert abs(totaux['hl_degres_total'] - (hl_deg_vdp + hl_deg_vdt)) < 1e-4

        ca_vdp = hl_deg_vdp * 6.28
        ca_vdt = hl_deg_vdt * 5.2713
        assert abs(totaux['ca_vdp_estime'] - ca_vdp) < 1e-4
        assert abs(totaux['ca_vdt_estime'] - ca_vdt) < 1e-4
        assert abs(totaux['ca_total_estime'] - (ca_vdp + ca_vdt)) < 1e-4

        prix_moyen = (ca_vdp + ca_vdt) / (hl_deg_vdp + hl_deg_vdt)
        assert abs(totaux['prix_moyen_pondere_hl_deg'] - prix_moyen) < 1e-4
