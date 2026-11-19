"""Fausses tables Gold au format du contrat, pour développer l'interface sans attendre les vraies.

    python -m common.fake_gold          # écrit dans data/fake_gold/
    URBANHUB_FAKE=1 streamlit run app/Accueil.py

Les fausses tables restent en local : elles ne vont jamais dans MinIO, pour ne pas écraser les vraies.
"""
import numpy as np
import pandas as pd

from common.lake import FAKE_DIR
from common.schemas import chemin_gold, valider
from common.villes import VILLES

JOURS = 90
rng = np.random.default_rng(42)


def base():
    heures = pd.date_range(end=pd.Timestamp.now(tz="UTC").floor("h"), periods=JOURS * 24, freq="h")
    df = pd.MultiIndex.from_product([list(VILLES), heures], names=["ville", "heure"]).to_frame(index=False)
    paris = df["heure"].dt.tz_convert("Europe/Paris")
    df["_h"] = paris.dt.hour
    df["_jour"] = paris.dt.day_of_year
    df["_semaine"] = paris.dt.day_of_week < 5
    df["_lat"] = df["ville"].map(lambda v: VILLES[v][0])
    return df


def meteo(df):
    n = len(df)
    m = df[["ville", "heure"]].copy()
    m["temperature_c"] = (12 - 9 * np.cos(2 * np.pi * (df["_jour"] - 15) / 365)
                          - 4 * np.cos(2 * np.pi * (df["_h"] - 3) / 24)
                          - 0.6 * (df["_lat"] - 45) + rng.normal(0, 1.5, n))
    m["precipitation_mm"] = np.where(rng.random(n) < 0.12, rng.gamma(1.2, 1.5, n), 0.0)
    m["wind_speed_ms"] = rng.gamma(2.0, 2.0, n)
    m["wind_direction_deg"] = rng.uniform(0, 360, n)
    m["visibility_m"] = np.clip(20000 - 2500 * m["precipitation_mm"] + rng.normal(0, 2000, n), 200, 30000)
    m["pressure_hpa"] = 1015 + rng.normal(0, 6, n)
    return m


def velos(df, m):
    n = len(df)
    pointe = np.exp(-((df["_h"] - 8) ** 2) / 2) + np.exp(-((df["_h"] - 18) ** 2) / 3)
    usage = 0.25 + 0.35 * pointe * df["_semaine"] + 0.1 * df["_h"].between(10, 20)
    usage -= 0.08 * np.minimum(m["precipitation_mm"], 3) - 0.01 * (m["temperature_c"] - 10)
    taux = np.clip(0.65 - usage + rng.normal(0, 0.05, n), 0.02, 0.98)
    capacite = df["ville"].map({v: 400 + 150 * i for i, v in enumerate(VILLES)})
    v = df[["ville", "heure"]].copy()
    v["bikes_available"] = taux * capacite
    v["free_slots"] = capacite - v["bikes_available"]
    v["taux_occupation"] = v["bikes_available"] / (v["bikes_available"] + v["free_slots"])
    return v


def pollution(df, m):
    n = len(df)
    trafic = 1 + 0.8 * (np.exp(-((df["_h"] - 8) ** 2) / 2) + np.exp(-((df["_h"] - 19) ** 2) / 3))
    dispersion = 1 / (1 + 0.15 * m["wind_speed_ms"])
    taille = df["ville"].map({"Paris": 1.5, "Lyon": 1.2, "Marseille": 1.2}).fillna(1.0)
    p = df[["ville", "heure"]].copy()
    p["pm25"] = 9 * dispersion * taille * (1 + 0.03 * np.maximum(10 - m["temperature_c"], 0)) * rng.lognormal(0, 0.3, n)
    p["pm10"] = p["pm25"] * 1.6 * rng.lognormal(0, 0.1, n)
    p["no2"] = 22 * trafic * dispersion * taille * rng.lognormal(0, 0.25, n)
    p["o3"] = np.maximum(10, 40 + 3 * (m["temperature_c"] - 12) - 0.5 * p["no2"] + rng.normal(0, 8, n))
    p["co"] = 250 * trafic * dispersion * rng.lognormal(0, 0.2, n)
    for col in ["pm25", "pm10", "no2", "o3", "co"]:  # quelques trous, laissés à null comme le veut le contrat
        p.loc[rng.random(n) < 0.03, col] = np.nan
    return p


def main():
    df = base()
    m = meteo(df)
    for source, table in {"meteo": m, "velos": velos(df, m), "pollution": pollution(df, m)}.items():
        valider(table, source)
        chemin = FAKE_DIR / chemin_gold(source)
        chemin.parent.mkdir(parents=True, exist_ok=True)
        table.to_parquet(chemin, index=False)
        print(f"{chemin} : {len(table)} lignes")


if __name__ == "__main__":
    main()
