"""Étape 3 – Nettoyage : Bronze → Silver.

Pour chaque département, lit les fichiers Météo-France de Bronze (copie la plus
récente), les nettoie, puis écrit dans Silver un fichier Parquet par mois :

    silver/meteo/year=AAAA/month=MM/dep_<dép>.parquet

Règles de nettoyage (dans l'ordre) :
1. Période : on garde les 5 dernières années (depuis le 1er janvier 2022).
2. Date : AAAAMMJJHH (heure UTC chez Météo-France) → vrai `timestamp` UTC.
3. Qualité : une valeur dont le code qualité vaut 2 (« douteuse ») est vidée.
   Codes conservés : 0 (protégée), 1 (validée), 9 (filtrée).
4. Valeurs impossibles : une valeur hors des bornes physiques est vidée.
5. Vent : direction vidée quand le vent est calme (vitesse 0) ; 360° → 0°.
6. Doublons (même station, même heure) supprimés ; lignes sans aucune mesure
   supprimées.
7. Ajout de la station : nom, coordonnées, ville (table de l'étape 2).

Une valeur absente reste vide (null), jamais remplacée par 0 (règle du contrat).

Lancement, depuis la racine du dépôt (après stations.py) :
    python -m partie1_meteo.nettoyage                       # toute la France
    python -m partie1_meteo.nettoyage --departements 69 75  # test rapide
"""

from __future__ import annotations

import argparse
import io
import json
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from partie1_meteo import config
from partie1_meteo.provisoire import client_minio, ecrire_octets, ecrire_parquet, lire_octets, lire_parquet
from partie1_meteo.stations import fichiers_les_plus_recents

# Colonne Météo-France → colonne Silver (unités déjà correctes chez Météo-France).
VARIABLES = {
    "T": "temperature_c",          # température sous abri (°C)
    "TN": "temperature_min_c",     # minimum dans l'heure (°C)
    "TX": "temperature_max_c",     # maximum dans l'heure (°C)
    "TD": "dew_point_c",           # point de rosée (°C)
    "U": "humidity_pct",           # humidité relative (%)
    "RR1": "precipitation_mm",     # pluie tombée en 1 heure (mm)
    "FF": "wind_speed_ms",         # vent moyen sur 10 min (m/s)
    "FXI": "wind_gust_ms",         # rafale maximale dans l'heure (m/s)
    "DD": "wind_direction_deg",    # direction du vent (degrés, 0 = nord)
    "VV": "visibility_m",          # visibilité (m)
    "PMER": "pressure_hpa",        # pression ramenée au niveau de la mer (hPa)
}

# Bornes physiques : en dehors, la valeur est jugée impossible.
BORNES = {
    "temperature_c": (-40, 50),
    "temperature_min_c": (-40, 50),
    "temperature_max_c": (-40, 50),
    "dew_point_c": (-50, 40),
    "humidity_pct": (0, 100),
    "precipitation_mm": (0, 150),
    "wind_speed_ms": (0, 60),
    "wind_gust_ms": (0, 90),
    "wind_direction_deg": (0, 360),
    "visibility_m": (0, 100_000),
    "pressure_hpa": (900, 1080),
}

CODE_QUALITE_DOUTEUX = 2

COLONNES_STATION = ["station_id", "station_name", "ville", "departement", "latitude", "longitude", "altitude_m"]


# ============================================================================
# Nettoyage d'un tableau (fonction pure, testée dans tests/test_nettoyage.py)
# ============================================================================

def nettoyer(brut: pd.DataFrame, debut: pd.Timestamp) -> tuple[pd.DataFrame, dict]:
    """Nettoie un tableau Météo-France. Renvoie (tableau propre, compteurs)."""
    compteurs: dict[str, int] = {"lignes_lues": len(brut)}

    df = pd.DataFrame({"station_id": brut["NUM_POSTE"].astype(str).str.zfill(8)})

    # 2. Date : AAAAMMJJHH en UTC → timestamp UTC.
    df["timestamp"] = pd.to_datetime(brut["AAAAMMJJHH"].astype(str), format="%Y%m%d%H", utc=True)

    # 1. Période étudiée.
    dans_periode = df["timestamp"] >= debut
    df, brut = df[dans_periode], brut[dans_periode]
    compteurs["lignes_hors_periode"] = int((~dans_periode).sum())

    compteurs["valeurs_douteuses"] = 0
    compteurs["valeurs_impossibles"] = 0
    for code_mf, colonne in VARIABLES.items():
        valeurs = pd.to_numeric(brut[code_mf], errors="coerce").astype("float64")

        # 3. Qualité : code 2 = douteuse → vidée.
        qualite = brut.get("Q" + code_mf)
        if qualite is not None:
            douteuses = (qualite == CODE_QUALITE_DOUTEUX) & valeurs.notna()
            compteurs["valeurs_douteuses"] += int(douteuses.sum())
            valeurs = valeurs.mask(douteuses)

        # 4. Valeurs impossibles → vidées.
        mini, maxi = BORNES[colonne]
        impossibles = valeurs.notna() & ((valeurs < mini) | (valeurs > maxi))
        compteurs["valeurs_impossibles"] += int(impossibles.sum())
        df[colonne] = valeurs.mask(impossibles).to_numpy()

    # 5. Vent calme : pas de direction. Nord noté 360° → 0°.
    calme = df["wind_speed_ms"] == 0
    compteurs["directions_vent_calme"] = int((calme & df["wind_direction_deg"].notna()).sum())
    df.loc[calme, "wind_direction_deg"] = np.nan
    df.loc[df["wind_direction_deg"] == 360, "wind_direction_deg"] = 0.0

    # 6. Doublons et lignes vides.
    avant = len(df)
    df = df.drop_duplicates(["station_id", "timestamp"], keep="last")
    compteurs["doublons"] = avant - len(df)

    mesures = list(VARIABLES.values())
    vides = df[mesures].isna().all(axis=1)
    compteurs["lignes_sans_mesure"] = int(vides.sum())
    df = df[~vides]

    compteurs["lignes_gardees"] = len(df)
    return df.reset_index(drop=True), compteurs


# ============================================================================
# Traitement d'un département (exécuté dans un processus séparé)
# ============================================================================

def traiter_departement(departement: str, cles: list[str], debut_iso: str) -> dict:
    s3 = client_minio()
    debut = pd.Timestamp(debut_iso)
    colonnes = ["NUM_POSTE", "AAAAMMJJHH"] + [c for code in VARIABLES for c in (code, "Q" + code)]

    morceaux = []
    for cle in cles:
        brut = pd.read_csv(
            io.BytesIO(lire_octets(s3, config.BUCKET_BRONZE, cle)),
            sep=";", compression="gzip", usecols=colonnes,
            dtype={"NUM_POSTE": str, "AAAAMMJJHH": str},
        )
        morceaux.append(brut)
    brut = pd.concat(morceaux, ignore_index=True)

    propre, compteurs = nettoyer(brut, debut)

    # 7. Infos de la station (nom, coordonnées, ville).
    stations = lire_parquet(s3, config.BUCKET_SILVER, config.CLE_STATIONS)[COLONNES_STATION]
    propre = propre.merge(stations, on="station_id", how="inner")
    propre = propre[COLONNES_STATION + ["timestamp"] + list(VARIABLES.values())]

    # Écriture : un fichier par mois.
    nb_fichiers = 0
    for (annee, mois), partie in propre.groupby([propre["timestamp"].dt.year, propre["timestamp"].dt.month]):
        cle = f"{config.SOURCE}/year={annee}/month={mois:02d}/dep_{departement}.parquet"
        ecrire_parquet(s3, partie.sort_values(["station_id", "timestamp"]), config.BUCKET_SILVER, cle)
        nb_fichiers += 1

    compteurs.update(
        departement=departement,
        stations=int(propre["station_id"].nunique()),
        fichiers_ecrits=nb_fichiers,
        derniere_mesure=propre["timestamp"].max().isoformat() if len(propre) else None,
    )
    return compteurs


# ============================================================================
# Programme principal
# ============================================================================

def main() -> None:
    parser = argparse.ArgumentParser(description="Nettoyage Bronze → Silver des données météo")
    parser.add_argument("--departements", nargs="+", help="codes de départements (ex. 69 75), pour tester")
    parser.add_argument("--processus", type=int, default=4)
    args = parser.parse_args()

    s3 = client_minio()
    debut = pd.Timestamp(f"{config.ANNEES[0]}-01-01", tz="UTC")

    # Fichiers à lire, groupés par département.
    par_departement: dict[str, list[str]] = {}
    for nom, cle in fichiers_les_plus_recents(s3).items():
        departement = nom.split("_")[1]
        par_departement.setdefault(departement, []).append(cle)
    if args.departements:
        par_departement = {d: c for d, c in par_departement.items() if d in args.departements}

    print(f"Nettoyage de {len(par_departement)} départements depuis le {debut:%d/%m/%Y}, "
          f"{args.processus} en parallèle…")
    t0 = time.time()
    rapports = []
    with ProcessPoolExecutor(max_workers=args.processus) as pool:
        futurs = {pool.submit(traiter_departement, d, c, debut.isoformat()): d for d, c in par_departement.items()}
        for i, futur in enumerate(as_completed(futurs), start=1):
            try:
                rapports.append(futur.result())
            except Exception as erreur:
                print(f"  ERREUR département {futurs[futur]} : {erreur}")
            if i % 10 == 0 or i == len(futurs):
                print(f"  {i}/{len(futurs)} départements traités")

    # --- Bilan ---
    total = pd.DataFrame(rapports).sum(numeric_only=True)
    print(f"\nTerminé en {(time.time() - t0) / 60:.1f} min")
    print(f"  Lignes lues                 : {int(total['lignes_lues']):>12,}".replace(",", " "))
    print(f"  Hors période (avant {config.ANNEES[0]})   : {int(total['lignes_hors_periode']):>12,}".replace(",", " "))
    print(f"  Doublons supprimés          : {int(total['doublons']):>12,}".replace(",", " "))
    print(f"  Lignes sans aucune mesure   : {int(total['lignes_sans_mesure']):>12,}".replace(",", " "))
    print(f"  Lignes gardées dans Silver  : {int(total['lignes_gardees']):>12,}".replace(",", " "))
    print(f"  Valeurs douteuses vidées    : {int(total['valeurs_douteuses']):>12,}".replace(",", " "))
    print(f"  Valeurs impossibles vidées  : {int(total['valeurs_impossibles']):>12,}".replace(",", " "))
    print(f"  Directions de vent calme    : {int(total['directions_vent_calme']):>12,}".replace(",", " "))
    print(f"  Stations                    : {int(total['stations']):>12,}".replace(",", " "))
    print(f"  Fichiers Parquet écrits     : {int(total['fichiers_ecrits']):>12,}".replace(",", " "))

    # Rapport de nettoyage, utile pour le rapport final.
    rapport = {
        "date": datetime.now(timezone.utc).isoformat(),
        "debut_periode": debut.isoformat(),
        "regles": {"code_qualite_rejete": CODE_QUALITE_DOUTEUX, "bornes": BORNES},
        "total": {k: int(v) for k, v in total.items()},
        "departements": rapports,
    }
    ecrire_octets(
        s3, config.BUCKET_SILVER, f"{config.SOURCE}/_rapport_nettoyage.json",
        json.dumps(rapport, ensure_ascii=False, indent=2).encode("utf-8"), "application/json",
    )
    print(f"  Rapport : {config.BUCKET_SILVER}/{config.SOURCE}/_rapport_nettoyage.json")


if __name__ == "__main__":
    main()
