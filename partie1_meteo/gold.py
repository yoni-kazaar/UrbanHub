"""Étape 4 – Tables Gold : Silver → Gold.

Lit toute la Silver météo en une passe (en parallèle) et produit :

| Table (bucket gold)                          | Contenu                                         |
| -------------------------------------------- | ----------------------------------------------- |
| meteo/meteo_ville_heure.parquet  (CONTRAT)   | 1 ligne par ville et par heure, format du contrat |
| meteo/meteo_ville_heure_detail.parquet       | idem + humidité, point de rosée, rafales, min/max |
| meteo/meteo_ville_jour.parquet               | 1 ligne par ville et par jour (heure de Paris)  |
| meteo/meteo_france_jour.parquet              | moyenne nationale par jour (toutes les stations) |
| meteo/meteo_stations.parquet                 | les stations, pour la carte                     |

Règles (CONTRAT.md) :
- `heure` = timestamp arrondi à l'heure, datetime UTC ;
- valeur d'une ville = MOYENNE des stations de la ville (y compris min, max et
  rafales : une station de sommet ou de cap venté ne décide pas pour la ville) ;
- direction du vent = moyenne VECTORIELLE (la moyenne de 350° et 10° vaut 0°, pas 180°) ;
- valeur absente = vide, jamais 0.

La table du contrat est publiée en DERNIER avec common.lake.publier_gold, qui
vérifie le format puis dépose gold/meteo/_SUCCESS : quand _SUCCESS existe,
toutes les tables météo sont prêtes.

Lancement, depuis la racine du dépôt (après nettoyage.py) :
    python -m partie1_meteo.gold
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd

from common.lake import publier_gold
from common.schemas import colonnes as colonnes_contrat
from partie1_meteo import config
from partie1_meteo.provisoire import client_minio, ecrire_parquet, lire_parquet, lister_cles

TZ = "Europe/Paris"
MIN_HEURES_JOUR = 18  # une journée n'est calculée que si au moins 18 h sur 24 sont mesurées

# Variables moyennées entre les stations d'une ville (règle du contrat), y compris
# les minimums, maximums et rafales : prendre la valeur la plus extrême de toutes
# les stations laisserait une seule station atypique (sommet, cap venté) décider
# pour toute la ville.
MOYENNES = ["temperature_c", "temperature_min_c", "temperature_max_c", "dew_point_c", "humidity_pct",
            "precipitation_mm", "wind_speed_ms", "wind_gust_ms", "visibility_m", "pressure_hpa"]


# ============================================================================
# Agrégats partiels : calculés fichier par fichier, puis fusionnés.
# (Une ville est répartie sur plusieurs départements, et un jour en heure de
#  Paris peut être à cheval sur deux fichiers mensuels en UTC.)
# ============================================================================

def partiel_ville_heure(df: pd.DataFrame) -> pd.DataFrame:
    d = df[df["ville"].notna()].copy()
    if d.empty:
        return pd.DataFrame()
    d["heure"] = d["timestamp"].dt.floor("h")
    rad = np.deg2rad(d["wind_direction_deg"])
    d["dir_sin"], d["dir_cos"] = np.sin(rad), np.cos(rad)
    agg = {f"{c}__sum": (c, "sum") for c in MOYENNES} | {f"{c}__n": (c, "count") for c in MOYENNES}
    agg |= {
        "dir_sin__sum": ("dir_sin", "sum"), "dir_cos__sum": ("dir_cos", "sum"), "dir__n": ("dir_sin", "count"),
        "nb_stations": ("station_id", "nunique"),
    }
    return d.groupby(["ville", "heure"]).agg(**agg).reset_index()


def partiel_station_jour(df: pd.DataFrame) -> pd.DataFrame:
    d = df[["station_id", "timestamp", "temperature_c", "temperature_min_c", "temperature_max_c",
            "precipitation_mm", "wind_gust_ms"]].copy()
    d["jour"] = d["timestamp"].dt.tz_convert(TZ).dt.date
    return d.groupby(["station_id", "jour"]).agg(
        t__sum=("temperature_c", "sum"), t__n=("temperature_c", "count"),
        tmin=("temperature_min_c", "min"), tmax=("temperature_max_c", "max"),
        rr__sum=("precipitation_mm", "sum"), rr__n=("precipitation_mm", "count"),
        rafale=("wind_gust_ms", "max"),
    ).reset_index()


def traiter_fichier(s3, cle: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    df = lire_parquet(s3, config.BUCKET_SILVER, cle)
    return partiel_ville_heure(df), partiel_station_jour(df)


# ============================================================================
# Fusion des agrégats partiels
# ============================================================================

def moyenne(somme: pd.Series, effectif: pd.Series) -> pd.Series:
    """Somme / effectif, vide si aucune mesure (jamais 0 par défaut)."""
    return (somme / effectif).where(effectif > 0)


def fusion_ville_heure(partiels: pd.DataFrame) -> pd.DataFrame:
    sommes = [c for c in partiels.columns if c.endswith("__sum") or c.endswith("__n")]
    g = partiels.groupby(["ville", "heure"]).agg(
        **{c: (c, "sum") for c in sommes},
        nb_stations=("nb_stations", "sum"),
    ).reset_index()

    out = g[["ville", "heure"]].copy()
    for c in MOYENNES:
        out[c] = moyenne(g[f"{c}__sum"], g[f"{c}__n"])
    # Moyenne vectorielle de la direction du vent, ramenée entre 0 et 360°.
    direction = np.rad2deg(np.arctan2(g["dir_sin__sum"], g["dir_cos__sum"])) % 360
    out["wind_direction_deg"] = direction.where(g["dir__n"] > 0)
    out["nb_stations"] = g["nb_stations"]
    return out.sort_values(["ville", "heure"]).reset_index(drop=True)


def ville_jour(detail: pd.DataFrame) -> pd.DataFrame:
    d = detail.copy()
    d["jour"] = d["heure"].dt.tz_convert(TZ).dt.date
    g = d.groupby(["ville", "jour"]).agg(
        temperature_moy_c=("temperature_c", "mean"),
        temperature_min_c=("temperature_min_c", "min"),
        temperature_max_c=("temperature_max_c", "max"),
        precipitation_mm=("precipitation_mm", lambda s: s.sum(min_count=1)),
        heures_pluie=("precipitation_mm", lambda s: int((s > 0.1).sum())),
        wind_speed_moy_ms=("wind_speed_ms", "mean"),
        rafale_max_ms=("wind_gust_ms", "max"),
        visibility_min_m=("visibility_m", "min"),
        heures_brouillard=("visibility_m", lambda s: int((s < 1000).sum())),
        humidity_moy_pct=("humidity_pct", "mean"),
        pressure_moy_hpa=("pressure_hpa", "mean"),
        pressure_min_hpa=("pressure_hpa", "min"),
        heures_mesurees=("temperature_c", "count"),
    ).reset_index()
    incomplet = g["heures_mesurees"] < MIN_HEURES_JOUR
    g.loc[incomplet, ["temperature_moy_c", "precipitation_mm"]] = np.nan
    g["jour"] = pd.to_datetime(g["jour"])
    return g


def france_jour(partiels: pd.DataFrame) -> pd.DataFrame:
    s = partiels.groupby(["station_id", "jour"]).agg(
        t__sum=("t__sum", "sum"), t__n=("t__n", "sum"),
        tmin=("tmin", "min"), tmax=("tmax", "max"),
        rr__sum=("rr__sum", "sum"), rr__n=("rr__n", "sum"),
        rafale=("rafale", "max"),
    ).reset_index()
    s["tmoy"] = moyenne(s["t__sum"], s["t__n"]).where(s["t__n"] >= MIN_HEURES_JOUR)
    s["rr"] = s["rr__sum"].where(s["rr__n"] >= MIN_HEURES_JOUR)
    f = s.groupby("jour").agg(
        temperature_moy_c=("tmoy", "mean"),
        temperature_min_c=("tmin", "mean"),
        temperature_max_c=("tmax", "mean"),
        precipitation_moy_mm=("rr", "mean"),
        rafale_max_ms=("rafale", "max"),
        nb_stations=("tmoy", "count"),
    ).reset_index()
    f["jour"] = pd.to_datetime(f["jour"])
    # Températures moyennes par station sur toute la période, pour la carte.
    par_station = s.groupby("station_id").agg(temperature_moy_periode_c=("tmoy", "mean")).reset_index()
    return f.sort_values("jour").reset_index(drop=True), par_station


# ============================================================================
# Programme principal
# ============================================================================

def main() -> None:
    s3 = client_minio()
    cles = [c for c in lister_cles(s3, config.BUCKET_SILVER, f"{config.SOURCE}/year=") if c.endswith(".parquet")]
    print(f"Lecture de {len(cles)} fichiers Silver…")

    t0 = time.time()
    p_ville, p_station = [], []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futurs = [pool.submit(traiter_fichier, s3, cle) for cle in cles]
        for i, futur in enumerate(as_completed(futurs), start=1):
            a, b = futur.result()
            if not a.empty:
                p_ville.append(a)
            p_station.append(b)
            if i % 500 == 0 or i == len(futurs):
                print(f"  {i}/{len(futurs)} fichiers lus")

    detail = fusion_ville_heure(pd.concat(p_ville, ignore_index=True))
    jour = ville_jour(detail)
    france, temp_station = france_jour(pd.concat(p_station, ignore_index=True))

    stations = lire_parquet(s3, config.BUCKET_SILVER, config.CLE_STATIONS)
    stations = stations.merge(temp_station, on="station_id", how="inner")

    # Tables complémentaires d'abord…
    sorties = {
        "meteo_ville_heure_detail.parquet": detail,
        "meteo_ville_jour.parquet": jour,
        "meteo_france_jour.parquet": france,
        "meteo_stations.parquet": stations,
    }
    for nom, table in sorties.items():
        ecrire_parquet(s3, table, config.BUCKET_GOLD, f"{config.SOURCE}/{nom}")
        print(f"  gold/{config.SOURCE}/{nom} : {len(table):,} lignes".replace(",", " "))

    # … puis la table du contrat, validée, avec _SUCCESS.
    contrat = detail[colonnes_contrat("meteo")].copy()
    publier_gold(contrat, "meteo")
    print(f"  gold/meteo/meteo_ville_heure.parquet (CONTRAT) : {len(contrat):,} lignes, "
          f"du {contrat['heure'].min():%d/%m/%Y} au {contrat['heure'].max():%d/%m/%Y %H h} UTC".replace(",", " "))
    print("  gold/meteo/_SUCCESS déposé")

    print(f"\nTerminé en {(time.time() - t0) / 60:.1f} min")
    couverture = contrat.groupby("ville").agg(
        heures=("heure", "size"),
        temperature=("temperature_c", "count"),
        visibilite=("visibility_m", "count"),
        pression=("pressure_hpa", "count"),
    )
    for c in ["temperature", "visibilite", "pression"]:
        couverture[c] = (couverture[c] / couverture["heures"] * 100).round(1).astype(str) + " %"
    print("\nCouverture de la table du contrat (part des heures avec une valeur) :")
    print(couverture.to_string())


if __name__ == "__main__":
    main()
