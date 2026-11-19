"""Format des 3 tables Gold (CONTRAT.md) et validation avant écriture."""
import pandas as pd

from common.villes import VILLES

GOLD = {
    "meteo": ["temperature_c", "precipitation_mm", "wind_speed_ms", "wind_direction_deg", "visibility_m", "pressure_hpa"],
    "velos": ["bikes_available", "free_slots", "taux_occupation"],
    "pollution": ["pm25", "pm10", "no2", "o3", "co"],
}


def colonnes(source):
    return ["ville", "heure"] + GOLD[source]


def chemin_gold(source):
    """Clé de la table Gold dans le bucket gold, ex. meteo/meteo_ville_heure.parquet."""
    return f"{source}/{source}_ville_heure.parquet"


def valider(df, source):
    """Lève ValueError avec la liste des écarts au contrat. À appeler avant d'écrire une table Gold."""
    erreurs = []
    manquantes = set(colonnes(source)) - set(df.columns)
    if manquantes:
        erreurs.append(f"colonnes manquantes : {sorted(manquantes)}")
    if "heure" in df.columns and not (isinstance(df["heure"].dtype, pd.DatetimeTZDtype) and str(df["heure"].dt.tz) == "UTC"):
        erreurs.append("heure doit être un datetime avec fuseau UTC, pas du texte")
    if "ville" in df.columns:
        inconnues = set(df["ville"].dropna()) - set(VILLES)
        if inconnues:
            erreurs.append(f"villes inconnues : {sorted(inconnues)}")
    if {"ville", "heure"} <= set(df.columns) and df.duplicated(["ville", "heure"]).any():
        erreurs.append("plusieurs lignes pour un même couple ville + heure")
    for c in set(GOLD[source]) & set(df.columns):
        if not pd.api.types.is_numeric_dtype(df[c]):
            erreurs.append(f"{c} doit être numérique")
    if source == "velos" and "taux_occupation" in df.columns and not df["taux_occupation"].dropna().between(0, 1).all():
        erreurs.append("taux_occupation doit être entre 0 et 1")
    if erreurs:
        raise ValueError(f"Table Gold {source} non conforme : " + " ; ".join(erreurs))
