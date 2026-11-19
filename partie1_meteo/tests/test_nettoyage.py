"""Tests des règles de nettoyage (étape 3).

Lancement, depuis la racine du dépôt :
    docker compose -f partie1_meteo/docker-compose.yml run --rm meteo python -m pytest partie1_meteo/tests -q
"""

import math

import pandas as pd

from partie1_meteo.nettoyage import VARIABLES, nettoyer

DEBUT = pd.Timestamp("2022-01-01", tz="UTC")


def ligne(**valeurs):
    """Une ligne Météo-France : toutes les mesures vides, code qualité 1 (validé)."""
    base = {"NUM_POSTE": "69029001", "AAAAMMJJHH": "2024071514"}
    for code in VARIABLES:
        base[code] = None
        base["Q" + code] = 1
    base.update(valeurs)
    return base


def nettoyer_lignes(*lignes):
    return nettoyer(pd.DataFrame(list(lignes)), DEBUT)


def test_date_convertie_en_utc():
    df, _ = nettoyer_lignes(ligne(T=21.5))
    assert df.loc[0, "timestamp"] == pd.Timestamp("2024-07-15 14:00", tz="UTC")
    assert str(df["timestamp"].dt.tz) == "UTC"


def test_valeur_douteuse_videe():
    df, compteurs = nettoyer_lignes(ligne(T=21.5, QT=2, FF=3.0))
    assert math.isnan(df.loc[0, "temperature_c"])
    assert df.loc[0, "wind_speed_ms"] == 3.0
    assert compteurs["valeurs_douteuses"] == 1


def test_codes_qualite_0_1_9_conserves():
    df, _ = nettoyer_lignes(ligne(T=10.0, QT=0), ligne(AAAAMMJJHH="2024071515", T=11.0, QT=9))
    assert df["temperature_c"].tolist() == [10.0, 11.0]


def test_valeur_impossible_videe():
    df, compteurs = nettoyer_lignes(ligne(T=85.0, U=130, PMER=1013.2))
    assert math.isnan(df.loc[0, "temperature_c"])
    assert math.isnan(df.loc[0, "humidity_pct"])
    assert df.loc[0, "pressure_hpa"] == 1013.2
    assert compteurs["valeurs_impossibles"] == 2


def test_vent_calme_sans_direction():
    df, _ = nettoyer_lignes(ligne(FF=0.0, DD=0))
    assert df.loc[0, "wind_speed_ms"] == 0.0
    assert math.isnan(df.loc[0, "wind_direction_deg"])


def test_nord_360_devient_0():
    df, _ = nettoyer_lignes(ligne(FF=4.0, DD=360))
    assert df.loc[0, "wind_direction_deg"] == 0.0


def test_pluie_nulle_gardee_a_zero():
    """0 mm de pluie est une vraie mesure : elle ne doit pas devenir vide."""
    df, _ = nettoyer_lignes(ligne(RR1=0.0))
    assert df.loc[0, "precipitation_mm"] == 0.0


def test_hors_periode_doublons_et_lignes_vides():
    df, compteurs = nettoyer_lignes(
        ligne(AAAAMMJJHH="2021123123", T=5.0),   # avant 2022 → supprimée
        ligne(T=20.0),
        ligne(T=20.5),                           # même station, même heure → doublon
        ligne(AAAAMMJJHH="2024071516"),          # aucune mesure → supprimée
    )
    assert len(df) == 1
    assert df.loc[0, "temperature_c"] == 20.5    # la dernière valeur est gardée
    assert compteurs["lignes_hors_periode"] == 1
    assert compteurs["doublons"] == 1
    assert compteurs["lignes_sans_mesure"] == 1
