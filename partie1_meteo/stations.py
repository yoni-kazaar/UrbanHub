"""Étape 2 : liste des stations météo françaises.

Météo-France ne publie pas de liste de stations séparée : chaque ligne des
fichiers horaires porte le numéro, le nom et les coordonnées de sa station.
Ce script :
1. lit, dans Bronze, la copie la plus récente de chaque fichier départemental
   (seulement les quelques colonnes utiles, pour aller vite) ;
2. construit une ligne par station : nom, coordonnées, période couverte,
   variables réellement mesurées ;
3. garde les stations actives sur la période étudiée ;
4. rattache chaque station à une des 8 villes du contrat (moins de 30 km) ;
5. écrit le résultat dans silver/meteo/stations/stations.parquet.

Lancement, depuis la racine du dépôt (après telechargement.py) :
    python -m partie1_meteo.stations
"""

from __future__ import annotations

import io
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

from partie1_meteo import config
from partie1_meteo.provisoire import (
    VILLES,
    client_minio,
    distance_km,
    ecrire_parquet,
    lire_octets,
    lister_cles,
    rattacher_ville,
)
from partie1_meteo.telechargement import MOTIF_FICHIER

# Colonnes Météo-France utiles ici (le fichier en compte plus de 200).
COLONNES = ["NUM_POSTE", "NOM_USUEL", "LAT", "LON", "ALTI", "AAAAMMJJHH", "T", "FF", "VV", "PMER", "RR1"]

# Variables du sujet et colonne Météo-France correspondante.
VARIABLES = {
    "mesure_temperature": "T",
    "mesure_vent": "FF",
    "mesure_visibilite": "VV",
    "mesure_pression": "PMER",
    "mesure_precipitation": "RR1",
}


def fichiers_les_plus_recents(s3) -> dict[str, str]:
    """Pour chaque nom de fichier, la clé de sa copie la plus récente dans Bronze.
    Les dossiers year=/month=/day= se trient dans l'ordre chronologique."""
    plus_recent: dict[str, str] = {}
    for cle in sorted(lister_cles(s3, config.BUCKET_BRONZE, f"{config.SOURCE}/")):
        if MOTIF_FICHIER.search(cle):
            plus_recent[cle.rsplit("/", 1)[-1]] = cle
    return plus_recent


def resumer_fichier(s3, cle: str) -> pd.DataFrame:
    """Une ligne par station présente dans un fichier départemental."""
    brut = lire_octets(s3, config.BUCKET_BRONZE, cle)
    df = pd.read_csv(
        io.BytesIO(brut), sep=";", compression="gzip",
        usecols=COLONNES, dtype={"NUM_POSTE": str, "AAAAMMJJHH": str, "NOM_USUEL": str},
    )
    groupes = df.groupby("NUM_POSTE")
    resume = groupes.agg(
        station_name=("NOM_USUEL", "last"),
        latitude=("LAT", "last"),
        longitude=("LON", "last"),
        altitude_m=("ALTI", "last"),
        debut=("AAAAMMJJHH", "min"),
        fin=("AAAAMMJJHH", "max"),
        nb_heures=("AAAAMMJJHH", "size"),
    )
    # Nombre d'heures avec une valeur, pour chaque variable.
    for nom, colonne in VARIABLES.items():
        resume[nom] = groupes[colonne].count()
    return resume.reset_index()


def construire_stations(s3) -> pd.DataFrame:
    cles = list(fichiers_les_plus_recents(s3).values())
    print(f"Lecture de {len(cles)} fichiers départementaux dans Bronze...")
    with ThreadPoolExecutor(max_workers=4) as pool:
        morceaux = list(pool.map(lambda cle: resumer_fichier(s3, cle), cles))

    # Une station apparaît dans 2 fichiers (2020-2024 et 2025-2026) : on fusionne.
    tout = pd.concat(morceaux, ignore_index=True)
    stations = tout.groupby("NUM_POSTE").agg(
        station_name=("station_name", "last"),
        latitude=("latitude", "last"),
        longitude=("longitude", "last"),
        altitude_m=("altitude_m", "last"),
        debut=("debut", "min"),
        fin=("fin", "max"),
        nb_heures=("nb_heures", "sum"),
        **{nom: (nom, "sum") for nom in VARIABLES},
    ).reset_index().rename(columns={"NUM_POSTE": "station_id"})

    # Dates Météo-France (AAAAMMJJHH, en UTC) -> vraies dates UTC.
    for col in ("debut", "fin"):
        stations[col] = pd.to_datetime(stations[col], format="%Y%m%d%H", utc=True)
    stations["departement"] = stations["station_id"].str[:2]

    # Une variable est 'mesurée' si la station la fournit au moins 1 heure sur 2.
    for nom in VARIABLES:
        stations[nom] = stations[nom] >= stations["nb_heures"] * 0.5

    # Stations actives pendant la période étudiée.
    debut_periode = pd.Timestamp(f"{config.ANNEES[0]}-01-01", tz="UTC")
    stations = stations[stations["fin"] >= debut_periode]

    # Rattachement à une ville (règle du contrat : < 30 km, sinon vide).
    villes, distances = [], []
    for lat, lon in zip(stations["latitude"], stations["longitude"]):
        ville = rattacher_ville(lat, lon)
        villes.append(ville)
        distances.append(round(distance_km(lat, lon, *VILLES[ville]), 1) if ville else None)
    stations["ville"] = villes
    stations["distance_ville_km"] = distances

    return stations.sort_values(["ville", "distance_ville_km", "station_id"], na_position="last").reset_index(drop=True)


def main() -> None:
    s3 = client_minio()
    stations = construire_stations(s3)
    ecrire_parquet(s3, stations, config.BUCKET_SILVER, config.CLE_STATIONS)
    print(f"Silver : {config.BUCKET_SILVER}/{config.CLE_STATIONS}\n")

    dans_villes = stations.dropna(subset=["ville"])
    print(f"{len(stations)} stations françaises actives depuis {config.ANNEES[0]}, "
          f"dernière mesure : {stations['fin'].max():%d/%m/%Y %H h} UTC.")
    print(f"{len(dans_villes)} rattachées à une des 8 villes "
          f"(T = température, V = vent, Vi = visibilité, P = pression, R = pluie) :\n")

    for ville in VILLES:
        s = dans_villes[dans_villes["ville"] == ville]
        if s.empty:
            print(f"  {ville:<11} aucune station à moins de 30 km")
            continue
        couverture = "".join(
            lettre if s[nom].any() else "-"
            for lettre, nom in zip(["T", "V", "Vi", "P", "R"], VARIABLES)
        )
        print(f"  {ville:<11} {len(s):>2} stations, variables {couverture:<7} "
              f"principale : {s.iloc[0]['station_name']} ({s.iloc[0]['distance_ville_km']} km)")


if __name__ == "__main__":
    main()
