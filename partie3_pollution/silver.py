"""
Étape 4 : nettoyage incrémental (Bronze -> Silver, Parquet).

À chaque passage, on ne traite que les nouveaux fichiers Bronze
(la liste des fichiers déjà traités est dans etat/silver_fait.txt).
Les jours touchés par ces nouveaux fichiers sont fusionnés avec le Silver existant.
Un passage ne relit donc plus tout le Bronze : quelques secondes au lieu de plusieurs minutes.

1. Lit les nouveaux fichiers bruts de bronze/pollution/ :
   - collecte  (pollution_*.json)  : dernières mesures, champ datetime.utc
   - historique (historique_*.json): moyennes horaires, champ period.datetimeTo.utc
     (on prend la fin de la période, comme la date des dernières mesures)
2. Ajoute les infos du capteur (polluant, unité, ville, position) depuis le catalogue.
3. Nettoie :
   - unités : ppb / ppm -> µg/m³ (à 25 °C) ; en France tout est déjà en µg/m³ ;
   - valeurs impossibles : vides, négatives ou au-dessus d'un plafond réaliste ;
   - doublons : une seule ligne par capteur et par date de mesure
     (le collecteur passe toutes les 15 min, les stations publient 1 fois par heure) ;
   - mesures périmées : l'API 'latest' renvoie la dernière valeur connue d'un capteur,
     même s'il est en panne depuis des années. Une valeur collectée plus de 48 h après
     sa date de mesure n'est pas 'en direct' : on l'écarte.
4. Écrit un fichier Parquet par jour : silver/pollution/year=AAAA/month=MM/day=JJ/pollution_AAAAMMJJ.parquet

Lancement :
  python -m partie3_pollution.silver            -> seulement les nouveaux fichiers Bronze
  python -m partie3_pollution.silver --complet  -> tout retraiter depuis zéro
"""

import argparse
import io
from pathlib import Path

import pandas as pd

from . import config
from .decouverte_capteurs import charger_catalogue
from .stockage import Lac, chemin_partitionne

# 1 ppb -> µg/m³ à 25 °C et 1 atm (masse molaire / 24,45)
FACTEUR_PPB = {"no2": 1.88, "o3": 1.96, "co": 1.145}

# Plafonds au-delà desquels une valeur est considérée comme une erreur de capteur (µg/m³)
PLAFOND = {"pm25": 1000, "pm10": 2000, "no2": 1000, "o3": 800, "co": 50000}

COLONNES = ["ville", "latitude", "longitude", "timestamp", "heure", "sensor_id", "location_id",
            "location_name", "pollutant", "value", "unit", "unit_origine", "is_monitor", "origine"]

FICHIER_FAIT = config.DOSSIER_ETAT / "silver_fait.txt"
TAILLE_LOT = 300          # nombre de fichiers Bronze traités d'un coup (limite la mémoire)
PERIME = pd.Timedelta(hours=48)


def lire_bronze(lac, fichiers):
    lignes = []
    for chemin in fichiers:
        nom = chemin.rsplit("/", 1)[-1]
        if nom.startswith("pollution_"):
            d = lac.lire_json("bronze", chemin)
            for releve in d.get("releves", []):
                for r in releve.get("results", []):
                    lignes.append((r.get("sensorsId"), (r.get("datetime") or {}).get("utc"),
                                   r.get("value"), "collecte", d.get("collecte_utc")))
        elif nom.startswith("historique_"):
            d = lac.lire_json("bronze", chemin)
            for r in d.get("results", []):
                fin = ((r.get("period") or {}).get("datetimeTo") or {}).get("utc")
                lignes.append((d["sensor_id"], fin, r.get("value"), "historique", None))
    return pd.DataFrame(lignes, columns=["sensor_id", "timestamp", "value", "origine", "collecte_utc"])


def en_microgrammes(df):
    """Convertit value en µg/m³ selon l'unité d'origine du capteur."""
    unite = df["unit_origine"].fillna("").str.lower().str.replace("µ", "u").str.replace("³", "3")
    facteur = df["pollutant"].map(FACTEUR_PPB)
    valeur = df["value"].astype(float)
    valeur = valeur.where(~unite.eq("ppb"), valeur * facteur)
    valeur = valeur.where(~unite.eq("ppm"), valeur * 1000 * facteur)
    connue = unite.isin(["ug/m3", "ppb", "ppm"])
    return valeur.where(connue)          # unité inconnue -> valeur vide


def dedoublonner(df):
    """Une ligne par capteur et par date ; on garde la donnée historique (moyenne validée) si elle existe."""
    return (df.sort_values(["sensor_id", "timestamp", "origine"])      # "historique" > "collecte"
              .drop_duplicates(["sensor_id", "timestamp"], keep="last"))


def nettoyer(brut, capteurs):
    """Mesures brutes -> mesures propres au format Silver. Renvoie (df, nb_invalides)."""
    df = brut.merge(capteurs, on="sensor_id", how="inner")
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    collecte = pd.to_datetime(df["collecte_utc"], utc=True, errors="coerce")
    perime = df["origine"].eq("collecte") & ((collecte - df["timestamp"]) > PERIME)
    df["value"] = en_microgrammes(df)
    df["unit"] = "µg/m³"

    plafond = df["pollutant"].map(PLAFOND)
    valide = (df["timestamp"].notna() & df["value"].notna() & (df["value"] >= 0)
              & (df["value"] <= plafond) & ~perime)
    n_invalides = int((~valide).sum())
    df = dedoublonner(df[valide])
    df["heure"] = df["timestamp"].dt.floor("h")
    return df[COLONNES], n_invalides


def chemin_jour(jour):
    dt = pd.Timestamp(jour)
    return chemin_partitionne(f"pollution_{dt:%Y%m%d}.parquet", dt)


def fusionner_et_ecrire(lac, nouveau, existants):
    """Pour chaque jour touché : Silver existant + nouvelles mesures -> réécrit le fichier du jour."""
    for jour, groupe in nouveau.groupby(nouveau["timestamp"].dt.date):
        chemin = chemin_jour(jour)
        if chemin in existants:
            ancien = pd.read_parquet(io.BytesIO(lac.lire("silver", chemin)))
            groupe = dedoublonner(pd.concat([ancien, groupe], ignore_index=True))
        groupe = groupe[COLONNES].sort_values(["timestamp", "sensor_id"]).reset_index(drop=True)
        buf = io.BytesIO()
        groupe.to_parquet(buf, index=False)
        lac.ecrire("silver", chemin, buf.getvalue())
        existants.add(chemin)
    return nouveau["timestamp"].dt.date.nunique()


def vider_silver(lac):
    """Mode --complet : supprime l'ancien Silver pollution pour repartir d'une base propre."""
    fichiers = lac.lister("silver", "pollution/")
    for f in fichiers:
        if lac.client:
            lac.client.remove_object("silver", f)
        else:
            (Path(config.DOSSIER_LAC_LOCAL) / "silver" / f).unlink()
    print(f"Ancien Silver supprimé : {len(fichiers)} fichiers", flush=True)


def main(complet=False):
    lac = Lac()
    print("Stockage :", lac.mode(), flush=True)
    cat = charger_catalogue()
    if not cat:
        raise RuntimeError("Catalogue introuvable : lancer d'abord le collecteur ou decouverte_capteurs.")
    capteurs = pd.DataFrame(cat["capteurs"]).rename(columns={"unit": "unit_origine"})

    config.DOSSIER_ETAT.mkdir(parents=True, exist_ok=True)
    if complet:
        vider_silver(lac)
        if FICHIER_FAIT.exists():
            FICHIER_FAIT.unlink()
    fait = set(FICHIER_FAIT.read_text().split()) if FICHIER_FAIT.exists() else set()

    tous = lac.lister("bronze", "pollution/")
    nouveaux = [f for f in tous if f.endswith(".json") and f not in fait
                and f.rsplit("/", 1)[-1].startswith(("pollution_", "historique_"))]
    existants = set(lac.lister("silver", "pollution/"))
    print(f"Bronze : {len(tous)} fichiers, {len(nouveaux)} nouveaux à traiter", flush=True)
    if not nouveaux:
        print("Rien de nouveau : Silver déjà à jour.", flush=True)
        return

    total_brut, total_gardes, total_invalides = 0, 0, 0
    for i in range(0, len(nouveaux), TAILLE_LOT):
        lot = nouveaux[i:i + TAILLE_LOT]
        brut = lire_bronze(lac, lot)
        df, n_invalides = nettoyer(brut, capteurs)
        nb_jours = fusionner_et_ecrire(lac, df, existants) if len(df) else 0
        with open(FICHIER_FAIT, "a") as f:            # noté comme traité seulement après l'écriture
            f.write("\n".join(lot) + "\n")
        total_brut += len(brut)
        total_gardes += len(df)
        total_invalides += n_invalides
        print(f"  lot {i // TAILLE_LOT + 1} : {min(i + TAILLE_LOT, len(nouveaux))}/{len(nouveaux)} fichiers | "
              f"{len(brut)} mesures brutes -> {len(df)} gardées | {nb_jours} jours mis à jour", flush=True)

    print(f"Silver à jour : {total_brut} mesures brutes, {total_gardes} gardées, "
          f"{total_invalides} écartées (invalides ou périmées)", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--complet", action="store_true", help="tout retraiter depuis zéro")
    main(complet=parser.parse_args().complet)