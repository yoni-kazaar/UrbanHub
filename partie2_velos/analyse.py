"""Analyses vélos (partie 2) : les 5 questions métier + K-means, sur Silver (une ligne par station et par relevé).

    python -m partie2_velos.analyse      # affiche un résumé de chaque analyse

Chaque fonction prend le DataFrame retourné par `preparer(...)` et renvoie un tableau prêt à afficher
(page Streamlit `app/pages/2_Velos.py`).
"""
import numpy as np
import pandas as pd

from common.villes import VILLES, distance_km
from partie2_velos.gold import lire_silver

ECART_MAX_MIN = 10   # au-delà, deux relevés successifs d'une station ne sont plus comparables (trou de collecte)
SEUIL_CRITIQUE = 0.3  # une station est critique si elle est vide (ou pleine) plus de 30 % du temps
MIN_RELEVES = 10


def preparer(silver):
    """Silver -> données exploitables : stations en service, dans une ville, avec une vraie disponibilité."""
    df = silver[silver["en_service"] & silver["ville"].notna()].copy()
    # un réseau qui annonce 0 vélo partout ne publie pas de disponibilité (Marseille) : exclu des analyses
    avec_mesure = df.groupby("ville")["free_bikes"].max() > 0
    df = df[df["ville"].isin(avec_mesure[avec_mesure].index)]

    df = df.sort_values(["reseau", "station_id", "timestamp"]).reset_index(drop=True)
    df["heure_paris"] = df["timestamp"].dt.tz_convert("Europe/Paris").dt.hour
    df["taux"] = (df["free_bikes"] / df["capacite"]).where(df["capacite"] > 0)
    df["vide"] = df["free_bikes"] == 0
    df["pleine"] = df["empty_slots"] == 0

    # mouvement = vélos pris ou déposés entre deux relevés consécutifs d'une même station
    par_station = df.groupby(["reseau", "station_id"])
    duree_h = par_station["timestamp"].diff().dt.total_seconds() / 3600
    mouvement = par_station["free_bikes"].diff().abs()
    valide = duree_h.notna() & (duree_h <= ECART_MAX_MIN / 60)
    df["duree_h"] = duree_h.where(valide)
    df["mouvement"] = mouvement.where(valide)
    df["mouvement_par_heure"] = df["mouvement"] / df["duree_h"]
    return df


def stations_plus_utilisees(df, n=20, min_heures=0.5):
    """Q1 : les stations où il se passe le plus de mouvements (vélos pris + déposés) par heure.

    Une station observée moins de `min_heures` est écartée : sur quelques minutes, le taux n'est que du bruit.
    """
    g = df.groupby(["ville", "reseau", "station_id", "station_name"])
    t = g.agg(
        mouvements=("mouvement", "sum"),
        heures=("duree_h", "sum"),
        capacite=("capacite", "mean"),
        taux_moyen=("taux", "mean"),
    ).reset_index()
    t = t[t["heures"] >= min_heures].copy()
    t["mouvements_par_heure"] = t["mouvements"] / t["heures"]
    t["rotation"] = t["mouvements_par_heure"] / t["capacite"]  # mouvements par heure et par place
    return t.sort_values("mouvements_par_heure", ascending=False).head(n).round(3).reset_index(drop=True)


def zones_offre_insuffisante(df, pas=0.01, min_stations=3, n=15):
    """Q2 : zones (carrés d'environ 1 km) où les stations sont le plus souvent vides."""
    d = df.assign(
        lat=(df["latitude"] / pas).round() * pas,
        lon=(df["longitude"] / pas).round() * pas,
    )
    t = d.groupby(["ville", "lat", "lon"]).agg(
        stations=("station_id", "nunique"),
        part_vide=("vide", "mean"),
        taux_moyen=("taux", "mean"),
    ).reset_index()
    t = t[t["stations"] >= min_stations]
    return t.sort_values("part_vide", ascending=False).head(n).round(3).reset_index(drop=True)


def pics_journaliers(df):
    """Q3 : activité (mouvements par station et par heure) selon l'heure de la journée (heure de Paris)."""
    return (df.groupby(["ville", "heure_paris"])
              .agg(mouvements_par_station_heure=("mouvement_par_heure", "mean"),
                   taux_moyen=("taux", "mean"),
                   relevés=("station_id", "size"))
              .reset_index().round(3))


def heures_de_pointe(pics, n=2):
    """Les n heures les plus actives de chaque ville."""
    return (pics.sort_values("mouvements_par_station_heure", ascending=False)
                .groupby("ville").head(n).sort_values(["ville", "heure_paris"]).reset_index(drop=True))


def desequilibres_geographiques(df):
    """Q4 : remplissage selon la distance au centre-ville."""
    centre = df["ville"].map(VILLES)
    d = df.assign(distance_km=[distance_km(la, lo, c[0], c[1])
                               for la, lo, c in zip(df["latitude"], df["longitude"], centre)])
    d["zone"] = pd.cut(d["distance_km"], [0, 2, 5, np.inf], labels=["< 2 km", "2 à 5 km", "> 5 km"], right=False)
    return (d.groupby(["ville", "zone"], observed=True)
              .agg(stations=("station_id", "nunique"), taux_moyen=("taux", "mean"),
                   part_vide=("vide", "mean"), part_pleine=("pleine", "mean"))
              .reset_index().round(3))


def stations_critiques(df, seuil=SEUIL_CRITIQUE, min_releves=MIN_RELEVES):
    """Q5 : stations à rééquilibrer : souvent vides (à réapprovisionner) ou souvent pleines (à vider)."""
    t = df.groupby(["ville", "reseau", "station_id", "station_name"]).agg(
        releves=("vide", "size"), part_vide=("vide", "mean"), part_pleine=("pleine", "mean"),
        capacite=("capacite", "mean")).reset_index()
    t = t[t["releves"] >= min_releves]
    t["probleme"] = np.select(
        [(t["part_vide"] >= seuil) & (t["part_vide"] >= t["part_pleine"]), t["part_pleine"] >= seuil],
        ["souvent vide : à réapprovisionner", "souvent pleine : à vider"], default="")
    t["gravite"] = t[["part_vide", "part_pleine"]].max(axis=1)
    t = t[t["probleme"] != ""]
    return t.sort_values("gravite", ascending=False).round(3).reset_index(drop=True)


def profils_kmeans(df, k=4, min_releves=MIN_RELEVES):
    """IA : K-means sur le profil de remplissage de chaque station selon l'heure (heure de Paris).

    Retourne (stations avec leur cluster, profil moyen de chaque cluster par heure).
    """
    from sklearn.cluster import KMeans

    profils = df.pivot_table(index=["ville", "reseau", "station_id", "station_name"],
                             columns="heure_paris", values="taux", aggfunc="mean")
    profils = profils[df.groupby(["ville", "reseau", "station_id", "station_name"]).size().reindex(profils.index) >= min_releves]
    if profils.shape[1] < 2 or len(profils) < k:
        raise ValueError(f"Pas assez de données pour {k} groupes ({len(profils)} stations, {profils.shape[1]} heure(s)).")
    # une heure sans relevé pour une station : on prend son remplissage moyen
    X = profils.apply(lambda ligne: ligne.fillna(ligne.mean()), axis=1)

    modele = KMeans(n_clusters=k, n_init=10, random_state=0).fit(X)
    stations = X.assign(cluster=modele.labels_).reset_index()[["ville", "reseau", "station_id", "station_name", "cluster"]]
    centres = pd.DataFrame(modele.cluster_centers_, columns=X.columns).round(3)
    centres.index.name = "cluster"
    centres["stations"] = stations.groupby("cluster").size()
    return stations, centres


def main():
    pd.set_option("display.width", 200)
    df = preparer(lire_silver())
    print(f"{len(df):,} lignes, {df['station_id'].nunique()} stations, villes : {sorted(df['ville'].unique())}\n")
    print("Q1 stations les plus utilisées\n", stations_plus_utilisees(df, 5).to_string(), "\n")
    print("Q2 zones à l'offre insuffisante\n", zones_offre_insuffisante(df).head(5).to_string(), "\n")
    print("Q3 heures de pointe\n", heures_de_pointe(pics_journaliers(df)).to_string(), "\n")
    print("Q4 déséquilibres géographiques\n", desequilibres_geographiques(df).to_string(), "\n")
    critiques = stations_critiques(df)
    print(f"Q5 stations critiques : {len(critiques)}\n", critiques.head(5).to_string(), "\n")
    try:
        stations, centres = profils_kmeans(df)
        print("K-means : profil moyen par groupe\n", centres.to_string())
    except ValueError as e:
        print("K-means :", e)


if __name__ == "__main__":
    main()
