"""Gold vélos : Silver -> une ligne par ville et par heure (UTC), au format du contrat.

    python -m partie2_velos.gold

Sortie : gold/velos/velos_ville_heure.parquet (+ gold/velos/_SUCCESS)
Colonnes : ville, heure, bikes_available, free_slots, taux_occupation
"""
import logging

import pandas as pd

from common import lake

log = logging.getLogger("velos.gold")


def lire_silver():
    """Toutes les tables Silver journalières, concaténées."""
    cles = [c for c in lake.fs().find("silver/velos") if c.endswith("velos.parquet")]
    if not cles:
        raise SystemExit("Aucune table Silver : lancer d'abord `python -m partie2_velos.silver`.")
    log.info("%d jour(s) de Silver", len(cles))
    return pd.concat((lake.lire_parquet("silver", c.removeprefix("silver/")) for c in cles), ignore_index=True)


def construire(silver):
    """Silver (par station) -> Gold (par ville et par heure)."""
    # stations hors service et stations hors des 8 villes ne comptent pas
    df = silver[silver["en_service"] & silver["ville"].notna()].copy()
    df["heure"] = df["timestamp"].dt.floor("h")

    # 1) moyenne par station sur l'heure, 2) moyenne des stations de la ville : chaque station pèse pareil
    par_station = df.groupby(["ville", "heure", "reseau", "station_id"], as_index=False)[["free_bikes", "empty_slots"]].mean()
    gold = par_station.groupby(["ville", "heure"], as_index=False).agg(
        bikes_available=("free_bikes", "mean"),
        free_slots=("empty_slots", "mean"),
        max_velos=("free_bikes", "max"),
    )

    total = gold["bikes_available"] + gold["free_slots"]
    gold["taux_occupation"] = (gold["bikes_available"] / total).where(total > 0)

    # Un réseau qui annonce 0 vélo dans toutes ses stations ne publie pas de disponibilité (cas de
    # Marseille / LeVélo) : ce 0 est une donnée absente, pas une mesure (contrat : null, jamais 0).
    sans_mesure = gold["max_velos"] == 0
    for ville in gold.loc[sans_mesure, "ville"].unique():
        log.warning("%s : 0 vélo annoncé partout, disponibilité mise à null", ville)
    gold.loc[sans_mesure, ["bikes_available", "taux_occupation"]] = float("nan")
    return gold[["ville", "heure", "bikes_available", "free_slots", "taux_occupation"]].sort_values(["ville", "heure"]).reset_index(drop=True)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    gold = construire(lire_silver())
    lake.publier_gold(gold, "velos")  # valide le contrat, écrit la table puis dépose _SUCCESS
    log.info("gold/velos publié : %d lignes, %d villes, du %s au %s",
             len(gold), gold["ville"].nunique(), gold["heure"].min(), gold["heure"].max())


if __name__ == "__main__":
    main()
