"""Silver vélos : JSON bruts de bronze -> une table par jour, une ligne par station et par relevé.

    python -m partie2_velos.silver                      # aujourd'hui (UTC)
    python -m partie2_velos.silver --jour 2026-11-19    # un jour précis
    python -m partie2_velos.silver --tout               # tous les jours présents dans bronze

Sortie : silver/velos/year=AAAA/month=MM/day=JJ/velos.parquet (réécrit à chaque exécution)
"""
import argparse
import json
import logging
import re
from datetime import datetime, timezone

import pandas as pd

from common import lake
from common.villes import rattacher_ville

log = logging.getLogger("velos.silver")

COLONNES = [
    "ville", "reseau", "station_id", "station_name", "latitude", "longitude",
    "timestamp", "free_bikes", "empty_slots", "capacite", "en_service",
]
MOTIF_NOM = re.compile(r"velos_(\d{8}T\d{6}Z)_(.+)\.json$")


def aplatir(contenu, chemin):
    """Un JSON CityBikes -> une ligne par station. `timestamp` = heure du relevé (UTC)."""
    m = MOTIF_NOM.search(chemin)
    releve = pd.to_datetime(m.group(1), format="%Y%m%dT%H%M%SZ", utc=True)
    lignes = []
    for s in json.loads(contenu)["network"]["stations"]:
        extra = s.get("extra") or {}
        lignes.append({
            "reseau": m.group(2),
            "station_id": s.get("id"),
            "station_name": s.get("name"),
            "latitude": s.get("latitude"),
            "longitude": s.get("longitude"),
            "timestamp": releve,
            "free_bikes": s.get("free_bikes"),
            "empty_slots": s.get("empty_slots"),
            # hors service seulement si le réseau dit explicitement ne plus louer ou rendre
            "en_service": extra.get("renting") is not False and extra.get("returning") is not False,
        })
    return pd.DataFrame(lignes)


def nettoyer(df):
    """Écarte les lignes inutilisables, rattache la ville (règle des 30 km), dédoublonne."""
    avant = len(df)
    for c in ["latitude", "longitude", "free_bikes", "empty_slots"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["station_id", "latitude", "longitude", "free_bikes", "empty_slots"])
    df = df[(df["free_bikes"] >= 0) & (df["empty_slots"] >= 0)]
    df = df.drop_duplicates(["reseau", "station_id", "timestamp"]).copy()

    # la ville se calcule une fois par station, pas une fois par ligne
    villes = {
        (la, lo): rattacher_ville(la, lo)
        for la, lo in df[["latitude", "longitude"]].drop_duplicates().itertuples(index=False)
    }
    df["ville"] = [villes[(la, lo)] for la, lo in zip(df["latitude"], df["longitude"])]
    df["capacite"] = df["free_bikes"] + df["empty_slots"]
    log.info("%d lignes lues, %d conservées", avant, len(df))
    return df[COLONNES].sort_values(["ville", "reseau", "station_id", "timestamp"]).reset_index(drop=True)


def jours_en_bronze():
    """Jours (datetime UTC) pour lesquels bronze contient des relevés."""
    jours = set()
    for c in lake.fs().find("bronze/velos"):
        m = re.search(r"year=(\d{4})/month=(\d{2})/day=(\d{2})/", c)
        if m:
            jours.add(datetime(*map(int, m.groups()), tzinfo=timezone.utc))
    return sorted(jours)


def construire(jour):
    """Silver d'un jour. Retourne le nombre de lignes écrites (0 s'il n'y a rien)."""
    dossier = f"bronze/{lake.partition('velos', jour)}"
    chemins = [c for c in lake.fs().find(dossier) if MOTIF_NOM.search(c)]
    if not chemins:
        log.warning("aucun relevé dans %s", dossier)
        return 0
    morceaux = []
    for i in range(0, len(chemins), 200):  # par lots : lecture en parallèle, mémoire bornée
        contenus = lake.fs().cat(chemins[i:i + 200])
        morceaux += [aplatir(contenus[c], c) for c in chemins[i:i + 200]]
    df = nettoyer(pd.concat(morceaux, ignore_index=True))
    lake.ecrire_parquet(df, "silver", f"{lake.partition('velos', jour)}/velos.parquet")
    log.info("%s : %d relevés -> %d lignes dans silver", jour.date(), len(chemins), len(df))
    return len(df)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--jour", help="AAAA-MM-JJ (UTC), par défaut aujourd'hui")
    parser.add_argument("--tout", action="store_true", help="tous les jours présents dans bronze")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if args.tout:
        jours = jours_en_bronze()
    elif args.jour:
        jours = [datetime.strptime(args.jour, "%Y-%m-%d").replace(tzinfo=timezone.utc)]
    else:
        jours = [datetime.now(timezone.utc)]
    for jour in jours:
        construire(jour)


if __name__ == "__main__":
    main()
