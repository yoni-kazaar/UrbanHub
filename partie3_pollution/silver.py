"""
Étape 4 – Nettoyage : Bronze -> Silver (Parquet).

1. Lit tous les fichiers bruts de bronze/pollution/ :
   - collecte  (pollution_*.json)  : dernières mesures, champ datetime.utc
   - historique (historique_*.json): moyennes horaires, champ period.datetimeTo.utc
     (on prend la FIN de la période, comme la date des dernières mesures)
2. Ajoute les infos du capteur (polluant, unité, ville, position) depuis le catalogue.
3. Nettoie :
   - unités : ppb / ppm -> µg/m³ (à 25 °C) ; en France tout est déjà en µg/m³ ;
   - valeurs impossibles : vides, négatives ou au-dessus d'un plafond réaliste ;
   - doublons : une seule ligne par capteur et par date de mesure
     (le collecteur passe toutes les 15 min, les stations publient 1 fois par heure).
4. Écrit un fichier Parquet par jour : silver/pollution/year=AAAA/month=MM/day=JJ/pollution_AAAAMMJJ.parquet

Lancement : python -m partie3_pollution.silver
"""

import io

import pandas as pd

from .decouverte_capteurs import charger_catalogue
from .stockage import Lac, chemin_partitionne

# 1 ppb -> µg/m³ à 25 °C et 1 atm (masse molaire / 24,45)
FACTEUR_PPB = {"no2": 1.88, "o3": 1.96, "co": 1.145}

# Plafonds au-delà desquels une valeur est considérée comme une erreur de capteur (µg/m³)
PLAFOND = {"pm25": 1000, "pm10": 2000, "no2": 1000, "o3": 800, "co": 50000}


def lire_bronze(lac):
    lignes = []
    fichiers = lac.lister("bronze", "pollution/")
    for chemin in fichiers:
        nom = chemin.rsplit("/", 1)[-1]
        if nom.startswith("pollution_"):
            d = lac.lire_json("bronze", chemin)
            for releve in d.get("releves", []):
                for r in releve.get("results", []):
                    lignes.append((r.get("sensorsId"), (r.get("datetime") or {}).get("utc"),
                                   r.get("value"), "collecte"))
        elif nom.startswith("historique_"):
            d = lac.lire_json("bronze", chemin)
            for r in d.get("results", []):
                fin = ((r.get("period") or {}).get("datetimeTo") or {}).get("utc")
                lignes.append((d["sensor_id"], fin, r.get("value"), "historique"))
    print(f"{len(fichiers)} fichiers Bronze lus, {len(lignes)} mesures brutes", flush=True)
    return pd.DataFrame(lignes, columns=["sensor_id", "timestamp", "value", "origine"])


def en_microgrammes(df):
    """Convertit value en µg/m³ selon l'unité d'origine du capteur."""
    unite = df["unit_origine"].fillna("").str.lower().str.replace("µ", "u").str.replace("³", "3")
    facteur = df["pollutant"].map(FACTEUR_PPB)
    valeur = df["value"].astype(float)
    valeur = valeur.where(~unite.eq("ppb"), valeur * facteur)
    valeur = valeur.where(~unite.eq("ppm"), valeur * 1000 * facteur)
    connue = unite.isin(["ug/m3", "ppb", "ppm"])
    return valeur.where(connue)          # unité inconnue -> valeur vide


def construire_silver(lac):
    cat = charger_catalogue()
    if not cat:
        raise RuntimeError("Catalogue introuvable : lance d'abord le collecteur ou decouverte_capteurs.")
    capteurs = pd.DataFrame(cat["capteurs"]).rename(columns={"unit": "unit_origine"})

    brut = lire_bronze(lac)
    n0 = len(brut)
    df = brut.merge(capteurs, on="sensor_id", how="inner")

    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    df["value"] = en_microgrammes(df)
    df["unit"] = "µg/m³"

    plafond = df["pollutant"].map(PLAFOND)
    valide = df["timestamp"].notna() & df["value"].notna() & (df["value"] >= 0) & (df["value"] <= plafond)
    n_invalides = int((~valide).sum())
    df = df[valide]

    # Doublons : on garde la donnée historique (moyenne validée) si elle existe, sinon la collecte
    df = (df.sort_values(["sensor_id", "timestamp", "origine"])
            .drop_duplicates(["sensor_id", "timestamp"], keep="last"))
    df["heure"] = df["timestamp"].dt.floor("h")

    colonnes = ["ville", "latitude", "longitude", "timestamp", "heure", "sensor_id", "location_id",
                "location_name", "pollutant", "value", "unit", "unit_origine", "is_monitor", "origine"]
    df = df[colonnes].sort_values(["timestamp", "sensor_id"]).reset_index(drop=True)
    print(f"Nettoyage : {n0} mesures brutes -> {len(df)} gardées "
          f"({n_invalides} invalides, {n0 - n_invalides - len(df)} doublons ou capteurs hors catalogue)", flush=True)
    return df


def ecrire_silver(lac, df):
    for jour, groupe in df.groupby(df["timestamp"].dt.date):
        buf = io.BytesIO()
        groupe.to_parquet(buf, index=False)
        dt = pd.Timestamp(jour)
        lac.ecrire("silver", chemin_partitionne(f"pollution_{dt:%Y%m%d}.parquet", dt), buf.getvalue())
    print(f"Silver : {df['timestamp'].dt.date.nunique()} fichiers journaliers écrits "
          f"({df['timestamp'].min()} -> {df['timestamp'].max()})", flush=True)


def main():
    lac = Lac()
    print("Stockage :", lac.mode(), flush=True)
    ecrire_silver(lac, construire_silver(lac))


if __name__ == "__main__":
    main()