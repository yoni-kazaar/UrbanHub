"""
Étape 5 : tables Gold de la pollution.

1. gold/pollution/pollution_ville_heure.parquet  (table du contrat, utilisée par la Partie 4)
   Une ligne par ville et par heure (UTC), colonnes pm25, pm10, no2, o3, co en µg/m³.
   Agrégation (CONTRAT.md) : moyenne des capteurs de la ville.
     1. moyenne par capteur et par heure ;
     2. moyenne de ces capteurs, par ville, heure et polluant.
   Une valeur absente reste vide (null), jamais 0.

2. gold/pollution/capteurs_pollution.parquet  (table en plus, pour la carte de la page Streamlit)
   Une ligne par capteur : position, polluant, dernière mesure et moyenne des 7 derniers jours.
   (Le contrat autorise chaque partie à produire d'autres tables pour ses propres besoins.)

Quand les tables sont écrites, on dépose gold/pollution/_SUCCESS pour signaler qu'elles sont prêtes.

Lancement : python -m partie3_pollution.gold
"""

import io

import pandas as pd

from .stockage import Lac

COLONNES = ["ville", "heure", "pm25", "pm10", "no2", "o3", "co"]
CHEMIN_GOLD = "pollution/pollution_ville_heure.parquet"
CHEMIN_CAPTEURS = "pollution/capteurs_pollution.parquet"


def lire_silver(lac):
    fichiers = [f for f in lac.lister("silver", "pollution/") if f.endswith(".parquet")]
    if not fichiers:
        raise RuntimeError("Aucun fichier Silver : lancer d'abord partie3_pollution.silver")
    return pd.concat([pd.read_parquet(io.BytesIO(lac.lire("silver", f))) for f in fichiers], ignore_index=True)


def construire_gold(silver):
    df = silver[silver["ville"].notna()]
    par_capteur = df.groupby(["ville", "heure", "pollutant", "sensor_id"], as_index=False)["value"].mean()
    par_ville = par_capteur.groupby(["ville", "heure", "pollutant"])["value"].mean().unstack("pollutant")
    gold = par_ville.reindex(columns=COLONNES[2:]).reset_index()      # les 5 colonnes, même si un polluant manque
    gold.columns.name = None
    gold["heure"] = pd.to_datetime(gold["heure"], utc=True)           # datetime avec fuseau UTC (contrat)
    gold[COLONNES[2:]] = gold[COLONNES[2:]].astype("float64")
    return gold[COLONNES].sort_values(["ville", "heure"]).reset_index(drop=True)


def construire_capteurs(silver):
    """Une ligne par capteur : où il est, ce qu'il mesure, sa dernière valeur et sa moyenne sur 7 jours."""
    df = silver[silver["ville"].notna()].sort_values("timestamp")
    infos = df.groupby("sensor_id").agg(
        ville=("ville", "last"), location_name=("location_name", "last"), pollutant=("pollutant", "last"),
        latitude=("latitude", "last"), longitude=("longitude", "last"),
        derniere_mesure=("timestamp", "last"), derniere_valeur=("value", "last"))
    depuis = df["timestamp"].max() - pd.Timedelta(days=7)
    recent = df[df["timestamp"] >= depuis].groupby("sensor_id")["value"].agg(moyenne_7j="mean", nb_mesures_7j="count")
    capteurs = infos.join(recent).reset_index()
    capteurs["nb_mesures_7j"] = capteurs["nb_mesures_7j"].fillna(0).astype("int64")
    return capteurs.sort_values(["ville", "pollutant", "location_name"]).reset_index(drop=True)


def verifier(gold):
    """Contrôles du contrat avant publication."""
    assert list(gold.columns) == COLONNES, gold.columns
    assert str(gold["heure"].dt.tz) == "UTC", "heure doit être en UTC"
    assert not gold.duplicated(["ville", "heure"]).any(), "une seule ligne par ville et par heure"
    villes_hors_contrat = set(gold["ville"]) - {"Paris", "Lyon", "Marseille", "Toulouse",
                                                "Lille", "Bordeaux", "Nantes", "Strasbourg"}
    assert not villes_hors_contrat, villes_hors_contrat


def ecrire_parquet(lac, chemin, df):
    buf = io.BytesIO()
    df.to_parquet(buf, index=False)
    return lac.ecrire("gold", chemin, buf.getvalue())


def main():
    lac = Lac()
    print("Stockage :", lac.mode(), flush=True)
    silver = lire_silver(lac)
    gold = construire_gold(silver)
    verifier(gold)
    capteurs = construire_capteurs(silver)
    print("Gold ->", ecrire_parquet(lac, CHEMIN_GOLD, gold), flush=True)
    print("Capteurs ->", ecrire_parquet(lac, CHEMIN_CAPTEURS, capteurs), flush=True)
    print("Prêt ->", lac.ecrire("gold", "pollution/_SUCCESS", b""), flush=True)
    print(f"{len(gold)} lignes | {gold['ville'].nunique()} villes | "
          f"{gold['heure'].min()} -> {gold['heure'].max()} | {len(capteurs)} capteurs", flush=True)
    print("Valeurs renseignées par polluant :", gold[COLONNES[2:]].notna().sum().to_dict(), flush=True)


if __name__ == "__main__":
    main()