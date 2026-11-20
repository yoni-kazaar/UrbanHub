"""Partie IA de D : prédire l'usage des vélos à partir de la météo, et score "conditions favorables au vélo".

    python -m partie4_croisee.modele                      # vraies tables Gold (MinIO du VPS)
    URBANHUB_FAKE=1 python -m partie4_croisee.modele      # fausses tables (common/fake_gold.py)

Usage des vélos = 1 - taux_occupation (moins il reste de vélos en station, plus ils sont utilisés).

Choix du modèle : une régression linéaire régularisée (Ridge), volontairement simple.
- Avec quelques dizaines d'heures communes aux 3 tables, un modèle plus complexe apprendrait le bruit.
- Ses coefficients se lisent directement : effet de chaque variable météo sur l'usage.

Validation : on entraîne sur le passé et on teste sur les 20 % d'heures les plus récentes, jamais au hasard.
Résultats écrits dans gold/croise/ : score_velo.parquet (une ligne par ville et par heure) et modele.json.
"""
import json
import os

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from common.lake import FAKE_DIR, METRIQUES, SCORE, ecrire_objet, ecrire_parquet, lire_gold
from common.schemas import GOLD

METEO = ["temperature_c", "precipitation_mm", "wind_speed_ms", "visibility_m", "pressure_hpa"]
TEMPS = ["heure_sin", "heure_cos", "week_end"]  # variables de contrôle : heure de pointe, week-end
PART_TEST = 0.2
HEURES_MIN_FIABLE = 24 * 14  # en dessous de 2 semaines de données communes, le modèle est indicatif
OMS = {"pm25": 15, "no2": 25}  # seuils journaliers OMS 2021 (µg/m³) : au-dessus, le score perd 20 points


# --- Données ---------------------------------------------------------------

def donnees():
    """Jointure interne des 3 tables Gold sur ville + heure : seule la période commune est gardée."""
    tables = {s: lire_gold(s) for s in GOLD}
    absentes = [s for s, t in tables.items() if t is None]
    if absentes:
        raise SystemExit(f"Tables Gold absentes : {absentes}.")
    df = tables["meteo"].merge(tables["velos"], on=["ville", "heure"]).merge(tables["pollution"], on=["ville", "heure"])
    df["heure"] = pd.to_datetime(df["heure"], utc=True)
    locale = df["heure"].dt.tz_convert("Europe/Paris")
    angle = 2 * np.pi * locale.dt.hour / 24
    df["heure_sin"], df["heure_cos"] = np.sin(angle), np.cos(angle)
    df["week_end"] = (locale.dt.day_of_week >= 5).astype(int)
    df["usage_velos"] = 1 - df["taux_occupation"]
    return df.dropna(subset=["usage_velos"]).sort_values("heure").reset_index(drop=True)


def separer(df):
    """Coupure dans le temps : les 20 % d'heures les plus récentes servent au test."""
    heures = np.sort(df["heure"].unique())
    limite = heures[int(len(heures) * (1 - PART_TEST))]
    return df[df["heure"] < limite], df[df["heure"] >= limite]


# --- Modèle ----------------------------------------------------------------

def creer_modele():
    preparation = ColumnTransformer([
        ("meteo", make_pipeline(SimpleImputer(strategy="median"), StandardScaler()), METEO),
        ("temps", "passthrough", TEMPS),
        ("ville", OneHotEncoder(handle_unknown="ignore"), ["ville"]),
    ])
    return make_pipeline(preparation, Ridge(alpha=1.0))


def effets_meteo(modele):
    """Coefficient de chaque variable météo : variation de l'usage pour +1 écart-type de la variable."""
    coefs = modele[-1].coef_[: len(METEO)]
    return dict(zip(METEO, map(float, coefs)))


def evaluer(df):
    train, test = separer(df)
    modele = creer_modele().fit(train, train["usage_velos"])
    prediction = modele.predict(test)
    # Référence naïve : l'usage moyen de la ville sur la période d'entraînement.
    reference = test["ville"].map(train.groupby("ville")["usage_velos"].mean()).fillna(train["usage_velos"].mean())
    heures = df["heure"].nunique()
    return {
        "periode": [df["heure"].min().isoformat(), df["heure"].max().isoformat()],
        "heures_communes": int(heures),
        "lignes": int(len(df)),
        "lignes_train": int(len(train)),
        "lignes_test": int(len(test)),
        "test_depuis": test["heure"].min().isoformat(),
        "modele": {"mae": float(mean_absolute_error(test["usage_velos"], prediction)),
                   "r2": float(r2_score(test["usage_velos"], prediction)) if len(test) > 1 else None},
        "reference": {"mae": float(mean_absolute_error(test["usage_velos"], reference)),
                      "r2": float(r2_score(test["usage_velos"], reference)) if len(test) > 1 else None},
        "fiable": bool(heures >= HEURES_MIN_FIABLE),
    }


def score(modele, df):
    """Score de 0 à 100 : la météo de cette heure est-elle plus ou moins propice au vélo que d'habitude ?

    On ne garde que la part de la prédiction due à la météo (somme coefficient × variable centrée),
    ce qui retire l'effet de l'heure de pointe et de la ville, puis on la classe en percentile.
    On retire 20 points si l'air dépasse un seuil OMS (PM2.5 ou NO2).
    """
    meteo_centree = modele[0].named_transformers_["meteo"].transform(df[METEO])
    effet_meteo = meteo_centree @ modele[-1].coef_[: len(METEO)]
    out = df[["ville", "heure"]].copy()
    out["usage_predit"] = modele.predict(df)
    out["effet_meteo"] = effet_meteo
    pollue = np.zeros(len(df), dtype=bool)
    for p, seuil in OMS.items():
        pollue |= df[p].gt(seuil).to_numpy()
    out["air_pollue"] = pollue
    out["score_velo"] = (100 * pd.Series(effet_meteo).rank(pct=True).to_numpy() - 20 * pollue).clip(0, 100)
    return out


# --- Lancement -------------------------------------------------------------

def main():
    df = donnees()
    metriques = evaluer(df)
    modele = creer_modele().fit(df, df["usage_velos"])  # pour le score : toute la période disponible
    metriques["effets_meteo"] = effets_meteo(modele)
    resultat = score(modele, df)

    m, r = metriques["modele"], metriques["reference"]
    print(f"{metriques['heures_communes']} heures communes ({metriques['lignes']} lignes ville x heure), "
          f"test sur {metriques['lignes_test']} lignes depuis {metriques['test_depuis']}")
    print(f"Modèle    : MAE = {m['mae']:.3f}   R2 = {m['r2']}")
    print(f"Référence : MAE = {r['mae']:.3f}   R2 = {r['r2']}")
    print("Effet de +1 écart-type sur l'usage :", {k: round(v, 3) for k, v in metriques["effets_meteo"].items()})
    if not metriques["fiable"]:
        print(f"ATTENTION : moins de {HEURES_MIN_FIABLE} heures communes, résultats seulement indicatifs.")

    if os.environ.get("URBANHUB_FAKE") == "1":
        (FAKE_DIR / SCORE).parent.mkdir(parents=True, exist_ok=True)
        resultat.to_parquet(FAKE_DIR / SCORE, index=False)
        (FAKE_DIR / METRIQUES).write_text(json.dumps(metriques, indent=2), "utf-8")
        print(f"Écrit dans {FAKE_DIR / 'croise'}")
    else:
        ecrire_parquet(resultat, "gold", SCORE)
        ecrire_objet("gold", METRIQUES, json.dumps(metriques, indent=2).encode())
        print("Écrit dans gold/croise/")


if __name__ == "__main__":
    main()
