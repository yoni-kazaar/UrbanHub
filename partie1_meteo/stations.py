"""Étape 1 – Liste des stations météo françaises.

1. Télécharge la liste officielle des stations NOAA (isd-history.csv).
2. La dépose telle quelle (compressée) dans Bronze.
3. Garde les stations françaises actives sur la période étudiée.
4. Rattache chaque station à une des 8 villes du contrat (moins de 30 km).
5. Écrit le résultat dans silver/meteo/stations/stations.parquet.

Lancement, depuis la racine du dépôt :
    python -m partie1_meteo.stations
"""

from __future__ import annotations

import gzip
import io
from datetime import datetime, timezone

import pandas as pd
import requests

from partie1_meteo import config
from partie1_meteo.provisoire import (
    VILLES,
    client_minio,
    distance_km,
    ecrire_octets,
    ecrire_parquet,
    rattacher_ville,
)


def telecharger_liste_stations() -> bytes:
    """Contenu brut du fichier isd-history.csv."""
    reponse = requests.get(config.URL_STATIONS, timeout=config.TIMEOUT_SECONDES)
    reponse.raise_for_status()
    return reponse.content


def filtrer_stations_francaises(brut: bytes) -> pd.DataFrame:
    """Stations françaises actives pendant la période, avec leur ville."""
    df = pd.read_csv(io.BytesIO(brut), dtype=str, encoding="latin-1")

    # 1. Pays = France métropolitaine.
    df = df[df["CTRY"] == config.CODE_PAYS].copy()

    # 2. Coordonnées utilisables (certaines lignes sont vides ou à 0).
    df["latitude"] = pd.to_numeric(df["LAT"], errors="coerce")
    df["longitude"] = pd.to_numeric(df["LON"], errors="coerce")
    df = df.dropna(subset=["latitude", "longitude"])
    df = df[(df["latitude"] != 0) | (df["longitude"] != 0)]

    # 3. Active pendant la période : a fonctionné après le 1er janvier
    #    de la première année étudiée.
    debut_periode = f"{config.ANNEES[0]}0101"
    df = df[df["END"] >= debut_periode]

    # 4. Identifiant NOAA = USAF + WBAN (ex. 071490 + 99999 = 07149099999,
    #    c'est aussi le nom du fichier horaire).
    df["station_id"] = df["USAF"] + df["WBAN"]

    resultat = pd.DataFrame(
        {
            "station_id": df["station_id"],
            "station_name": df["STATION NAME"].str.strip(),
            "icao": df["ICAO"],
            "latitude": df["latitude"],
            "longitude": df["longitude"],
            "altitude_m": pd.to_numeric(df["ELEV(M)"], errors="coerce"),
            "debut": pd.to_datetime(df["BEGIN"], format="%Y%m%d", errors="coerce"),
            "fin": pd.to_datetime(df["END"], format="%Y%m%d", errors="coerce"),
        }
    ).drop_duplicates("station_id")

    # 5. Rattachement à une ville (règle du contrat : < 30 km, sinon vide).
    villes, distances = [], []
    for lat, lon in zip(resultat["latitude"], resultat["longitude"]):
        ville = rattacher_ville(lat, lon)
        villes.append(ville)
        distances.append(round(distance_km(lat, lon, *VILLES[ville]), 1) if ville else None)
    resultat["ville"] = villes
    resultat["distance_ville_km"] = distances

    return resultat.sort_values(["ville", "station_id"], na_position="last").reset_index(drop=True)


def main() -> None:
    s3 = client_minio()
    maintenant = datetime.now(timezone.utc)

    print(f"Téléchargement de la liste des stations : {config.URL_STATIONS}")
    brut = telecharger_liste_stations()

    # Bronze : le fichier d'origine, compressé, jamais modifié.
    cle_bronze = f"{config.partition_bronze(maintenant)}/isd-history_{maintenant:%Y%m%dT%H%M%SZ}.csv.gz"
    ecrire_octets(s3, config.BUCKET_BRONZE, cle_bronze, gzip.compress(brut), "application/gzip")
    print(f"Bronze : {config.BUCKET_BRONZE}/{cle_bronze}")

    stations = filtrer_stations_francaises(brut)
    ecrire_parquet(s3, stations, config.BUCKET_SILVER, config.CLE_STATIONS)
    print(f"Silver : {config.BUCKET_SILVER}/{config.CLE_STATIONS}")

    # Résumé lisible.
    print(f"\n{len(stations)} stations françaises actives depuis {config.ANNEES[0]}.")
    print(f"{stations['ville'].notna().sum()} rattachées à une des 8 villes :\n")
    par_ville = (
        stations.dropna(subset=["ville"])
        .groupby("ville")["station_name"]
        .apply(lambda noms: ", ".join(noms))
    )
    for ville in VILLES:
        print(f"  {ville:<11} {par_ville.get(ville, '⚠ aucune station à moins de 30 km')}")


if __name__ == "__main__":
    main()
