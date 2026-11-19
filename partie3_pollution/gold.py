"""
Étape 5 – Table Gold du contrat : gold/pollution/pollution_ville_heure.parquet

Une ligne par ville et par heure (UTC), colonnes pm25, pm10, no2, o3, co en µg/m³.
Agrégation (CONTRAT.md) : moyenne des capteurs de la ville.
  1. moyenne par capteur et par heure ;
  2. moyenne de ces capteurs, par ville, heure et polluant.
Une valeur absente reste vide (null), jamais 0.
Quand la table est écrite, on dépose gold/pollution/_SUCCESS pour signaler qu'elle est prête.

Lancement : python -m partie3_pollution.gold
"""

import io

import pandas as pd

from .stockage import Lac

COLONNES = ["ville", "heure", "pm25", "pm10", "no2", "o3", "co"]
CHEMIN_GOLD = "pollution/pollution_ville_heure.parquet"


def lire_silver(lac):
    fichiers = [f for f in lac.lister("silver", "pollution/") if f.endswith(".parquet")]
    if not fichiers:
        raise RuntimeError("Aucun fichier Silver : lance d'abord partie3_pollution.silver")
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


def verifier(gold):
    """Contrôles du contrat avant publication."""
    assert list(gold.columns) == COLONNES, gold.columns
    assert str(gold["heure"].dt.tz) == "UTC", "heure doit être en UTC"
    assert not gold.duplicated(["ville", "heure"]).any(), "une seule ligne par ville et par heure"
    villes_hors_contrat = set(gold["ville"]) - {"Paris", "Lyon", "Marseille", "Toulouse",
                                                "Lille", "Bordeaux", "Nantes", "Strasbourg"}
    assert not villes_hors_contrat, villes_hors_contrat


def main():
    lac = Lac()
    print("Stockage :", lac.mode(), flush=True)
    gold = construire_gold(lire_silver(lac))
    verifier(gold)
    buf = io.BytesIO()
    gold.to_parquet(buf, index=False)
    print("Gold ->", lac.ecrire("gold", CHEMIN_GOLD, buf.getvalue()), flush=True)
    print("Prêt ->", lac.ecrire("gold", "pollution/_SUCCESS", b""), flush=True)
    print(f"{len(gold)} lignes | {gold['ville'].nunique()} villes | "
          f"{gold['heure'].min()} -> {gold['heure'].max()}", flush=True)
    print("Valeurs renseignées par polluant :", gold[COLONNES[2:]].notna().sum().to_dict(), flush=True)


if __name__ == "__main__":
    main()