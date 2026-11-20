"""Étape 5 : les 4 questions métier et la détection d'anomalies (IA).

Lit les tables Gold météo, calcule les réponses et les enregistre dans
gold/meteo/analyses/ (lues ensuite par la page Streamlit) :

- Q1 périodes anormales : anomalies_jour, periodes_anormales
- Q2 visibilité : visibilite_correlations, visibilite_classes, brouillard_mois_heure
- Q3 saisons : saisons_mois, tendance_mois
- Q4 jours extrêmes : jours_extremes
- chiffres clés pour le rapport : resultats.json

Lancement, depuis la racine du dépôt (après gold.py) :
    python -m partie1_meteo.analyses
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler
from statsmodels.tsa.seasonal import STL

from partie1_meteo import config
from partie1_meteo.provisoire import client_minio, ecrire_octets, ecrire_parquet, lire_parquet

TZ = "Europe/Paris"
DOSSIER = f"{config.SOURCE}/analyses"

# Q1 : seuils
FENETRE_NORMALE_JOURS = 7   # normale d'un jour = moyenne des jours ±7 autour, toutes années confondues
SEUIL_Z = 2.0               # écart à la normale, en nombre d'écarts-types
DUREE_MIN_JOURS = 3         # une 'période' anormale dure au moins 3 jours de suite
PART_ANOMALIES_IA = 0.01    # Isolation Forest : 1 % des jours les plus atypiques

# Q4 : seuils absolus (complétés par des seuils relatifs à chaque ville)
SEUILS_EXTREMES = {
    "chaleur_35c": ("temperature_max_c", ">=", 35.0),
    "gel_moins5c": ("temperature_min_c", "<=", -5.0),
    "pluie_30mm": ("precipitation_mm", ">=", 30.0),
    "rafale_100kmh": ("rafale_max_ms", ">=", 27.8),   # 100 km/h
    "brouillard_200m": ("visibility_min_m", "<", 200.0),
}


# --- Q1 : Périodes météorologiques anormales ---

def normale_saisonniere(jours: pd.DataFrame, colonne: str, groupe: str) -> pd.DataFrame:
    """Ajoute la normale (moyenne et écart-type) du jour de l'année, lissée sur ±7 jours."""
    d = jours.copy()
    d["jour_annee"] = d["jour"].dt.day_of_year.clip(upper=365)
    resultats = []
    for nom, g in d.groupby(groupe):
        par_jour = g.groupby("jour_annee")[colonne].agg(["sum", "count"]).reindex(range(1, 366), fill_value=0)
        carres = (g[colonne] ** 2).groupby(g["jour_annee"]).sum().reindex(range(1, 366), fill_value=0)
        # Fenêtre circulaire : fin décembre et début janvier sont voisins.
        largeur = 2 * FENETRE_NORMALE_JOURS + 1
        def lisser(s):
            etendu = pd.concat([s.iloc[-FENETRE_NORMALE_JOURS:], s, s.iloc[:FENETRE_NORMALE_JOURS]])
            return etendu.rolling(largeur, center=True).sum().iloc[FENETRE_NORMALE_JOURS:-FENETRE_NORMALE_JOURS]
        n, somme, somme2 = lisser(par_jour["count"]), lisser(par_jour["sum"]), lisser(carres)
        moyenne = somme / n
        ecart_type = np.sqrt((somme2 / n - moyenne ** 2).clip(lower=0))
        resultats.append(pd.DataFrame({groupe: nom, "jour_annee": moyenne.index,
                                       "normale": moyenne.values, "ecart_type": ecart_type.values}))
    return d.merge(pd.concat(resultats), on=[groupe, "jour_annee"], how="left")


def periodes(anomalies: pd.DataFrame, groupe: str) -> pd.DataFrame:
    """Suites d'au moins 3 jours consécutifs au-delà de ±2 écarts-types."""
    lignes = []
    for nom, g in anomalies.sort_values("jour").groupby(groupe):
        for sens, masque in (("chaud", g["z"] > SEUIL_Z), ("froid", g["z"] < -SEUIL_Z)):
            # Nouveau bloc à chaque changement d'état, ou si un jour manque.
            rupture = (masque != masque.shift()) | (g["jour"].diff() != pd.Timedelta(days=1))
            for _, bloc in g[masque].groupby(rupture.cumsum()[masque]):
                if len(bloc) >= DUREE_MIN_JOURS:
                    lignes.append({
                        groupe: nom, "type": sens,
                        "debut": bloc["jour"].min(), "fin": bloc["jour"].max(), "duree_jours": len(bloc),
                        "ecart_moyen_c": round(bloc["ecart_c"].mean(), 1),
                        "z_max": round(bloc["z"].abs().max(), 1),
                        "temperature_moy_c": round(bloc["temperature_moy_c"].mean(), 1),
                    })
    colonnes = [groupe, "type", "debut", "fin", "duree_jours", "ecart_moyen_c", "z_max", "temperature_moy_c"]
    return pd.DataFrame(lignes, columns=colonnes).sort_values("debut").reset_index(drop=True)


def isolation_forest(jours: pd.DataFrame) -> pd.DataFrame:
    """IA : repère les jours atypiques sur l'ensemble des variables, ville par ville.
    La température est prise en écart à la normale, sinon tous les jours
    d'hiver et d'été seraient jugés 'anormaux'."""
    variables = ["ecart_c", "amplitude_c", "precipitation_mm", "rafale_max_ms",
                 "pressure_min_hpa", "visibility_min_m", "humidity_moy_pct"]
    sorties = []
    for ville, g in jours.groupby("ville"):
        g = g.copy()
        X = g[variables].fillna(g[variables].median())
        modele = IsolationForest(contamination=PART_ANOMALIES_IA, n_estimators=300, random_state=42)
        Xs = StandardScaler().fit_transform(X)
        modele.fit(Xs)
        g["score_ia"] = -modele.score_samples(Xs)          # plus c'est haut, plus le jour est atypique
        g["anomalie_ia"] = modele.predict(Xs) == -1
        # Variable qui s'écarte le plus de la médiane : l'explication du jour atypique.
        z = (X - X.median()) / X.std()
        g["cause_ia"] = z.abs().idxmax(axis=1)
        sorties.append(g)
    return pd.concat(sorties)


def q1(jours: pd.DataFrame, france: pd.DataFrame) -> tuple[dict, dict]:
    v = normale_saisonniere(jours, "temperature_moy_c", "ville")
    v["ecart_c"] = v["temperature_moy_c"] - v["normale"]
    v["z"] = v["ecart_c"] / v["ecart_type"]
    v["amplitude_c"] = v["temperature_max_c"] - v["temperature_min_c"]
    v = isolation_forest(v)
    p_villes = periodes(v, "ville")

    f = france.assign(zone="France")
    f = normale_saisonniere(f, "temperature_moy_c", "zone")
    f["ecart_c"] = f["temperature_moy_c"] - f["normale"]
    f["z"] = f["ecart_c"] / f["ecart_type"]
    p_france = periodes(f, "zone").rename(columns={"zone": "ville"})

    anomalies = v[["ville", "jour", "temperature_moy_c", "temperature_min_c", "temperature_max_c",
                   "precipitation_mm", "rafale_max_ms", "visibility_min_m", "pressure_min_hpa",
                   "normale", "ecart_c", "z", "score_ia", "anomalie_ia", "cause_ia"]]
    periodes_toutes = pd.concat([p_france, p_villes], ignore_index=True)

    top_france = p_france.sort_values(["duree_jours", "z_max"], ascending=False).head(5)
    chiffres = {
        "nb_periodes_france": {t: int((p_france["type"] == t).sum()) for t in ("chaud", "froid")},
        "plus_longues_periodes_france": [
            {"type": r.type, "debut": f"{r.debut:%d/%m/%Y}", "fin": f"{r.fin:%d/%m/%Y}",
             "duree_jours": int(r.duree_jours), "ecart_moyen_c": float(r.ecart_moyen_c)}
            for r in top_france.itertuples()
        ],
        "nb_periodes_par_ville": p_villes.groupby("ville")["type"].value_counts().unstack(fill_value=0).to_dict("index"),
        "nb_jours_anomalie_ia": int(anomalies["anomalie_ia"].sum()),
        "causes_ia": anomalies[anomalies["anomalie_ia"]]["cause_ia"].value_counts().to_dict(),
    }
    return {"anomalies_jour": anomalies, "periodes_anormales": periodes_toutes}, chiffres


# --- Q2 : Conditions météo et visibilité ---

def q2(detail: pd.DataFrame) -> tuple[dict, dict]:
    d = detail.copy()
    d["ecart_rosee_c"] = d["temperature_c"] - d["dew_point_c"]  # proche de 0 = air saturé = brouillard
    variables = {
        "humidity_pct": "Humidité (%)",
        "ecart_rosee_c": "Écart température - point de rosée (°C)",
        "precipitation_mm": "Pluie (mm/h)",
        "wind_speed_ms": "Vent (m/s)",
        "temperature_c": "Température (°C)",
        "pressure_hpa": "Pression (hPa)",
    }
    lignes = []
    for zone, g in [("Toutes villes", d)] + list(d.groupby("ville")):
        for col, libelle in variables.items():
            paire = g[["visibility_m", col]].dropna()
            lignes.append({"ville": zone, "variable": col, "libelle": libelle,
                           "spearman": round(paire["visibility_m"].corr(paire[col], method="spearman"), 3),
                           "nb_heures": len(paire)})
    correlations = pd.DataFrame(lignes)

    # Visibilité médiane selon des classes d'humidité et de pluie.
    d["classe_humidite"] = pd.cut(d["humidity_pct"], [0, 60, 80, 90, 95, 100.1],
                                  labels=["< 60 %", "60-80 %", "80-90 %", "90-95 %", "> 95 %"], right=False)
    d["classe_pluie"] = pd.cut(d["precipitation_mm"], [-0.1, 0.05, 1, 4, 1000],
                               labels=["sèche", "faible (< 1 mm)", "modérée (1-4 mm)", "forte (> 4 mm)"])
    classes = pd.concat([
        d.groupby("classe_humidite", observed=True)["visibility_m"].agg(["median", "size"])
         .reset_index().rename(columns={"classe_humidite": "classe"}).assign(critere="humidité"),
        d.groupby("classe_pluie", observed=True)["visibility_m"].agg(["median", "size"])
         .reset_index().rename(columns={"classe_pluie": "classe"}).assign(critere="pluie"),
    ], ignore_index=True).rename(columns={"median": "visibilite_mediane_m", "size": "nb_heures"})
    classes["classe"] = classes["classe"].astype(str)

    # Brouillard (visibilité < 1 km) : fréquence par mois et heure locale.
    locale = d["heure"].dt.tz_convert(TZ)
    d["mois"], d["heure_locale"] = locale.dt.month, locale.dt.hour
    d["brouillard"] = d["visibility_m"] < 1000
    brouillard = (d.groupby(["ville", "mois", "heure_locale"])["brouillard"].mean() * 100).round(2) \
        .rename("part_heures_pct").reset_index()

    toutes = correlations[correlations["ville"] == "Toutes villes"].set_index("variable")["spearman"]
    par_ville_brouillard = (d.groupby("ville")["brouillard"].mean() * 100).round(2).sort_values(ascending=False)
    chiffres = {
        "spearman_toutes_villes": toutes.to_dict(),
        "visibilite_mediane_par_humidite_m": classes[classes["critere"] == "humidité"]
            .set_index("classe")["visibilite_mediane_m"].to_dict(),
        "visibilite_mediane_par_pluie_m": classes[classes["critere"] == "pluie"]
            .set_index("classe")["visibilite_mediane_m"].to_dict(),
        "part_heures_brouillard_pct_par_ville": par_ville_brouillard.to_dict(),
        "mois_le_plus_brumeux": int(d.groupby("mois")["brouillard"].mean().idxmax()),
        "heure_locale_la_plus_brumeuse": int(d.groupby("heure_locale")["brouillard"].mean().idxmax()),
    }
    return {"visibilite_correlations": correlations, "visibilite_classes": classes,
            "brouillard_mois_heure": brouillard}, chiffres


# --- Q3 : Évolution saisonnière de la température ---

def q3(jours: pd.DataFrame, france: pd.DataFrame) -> tuple[dict, dict]:
    v = jours[["ville", "jour", "temperature_moy_c"]].rename(columns={"ville": "zone"})
    f = france[["jour", "temperature_moy_c"]].assign(zone="France")
    tout = pd.concat([f, v], ignore_index=True)
    tout["mois_date"] = tout["jour"].dt.to_period("M").dt.to_timestamp()
    mensuel = tout.groupby(["zone", "mois_date"])["temperature_moy_c"].agg(["mean", "count"]).reset_index()
    mensuel = mensuel[mensuel["count"] >= 20].rename(columns={"mean": "temperature_moy_c"}).drop(columns="count")
    mensuel["annee"], mensuel["mois"] = mensuel["mois_date"].dt.year, mensuel["mois_date"].dt.month

    # Décomposition STL : tendance + saisonnalité + résidu (période 12 mois).
    tendances = []
    for zone, g in mensuel.groupby("zone"):
        serie = g.set_index("mois_date")["temperature_moy_c"].asfreq("MS").interpolate()
        stl = STL(serie, period=12, robust=True).fit()
        tendances.append(pd.DataFrame({"zone": zone, "mois_date": serie.index, "observe": serie.values,
                                       "tendance": stl.trend.values, "saisonnier": stl.seasonal.values}))
    tendance = pd.concat(tendances, ignore_index=True)

    # Profil saisonnier : moyenne de chaque mois sur toutes les années complètes.
    profil = mensuel.groupby(["zone", "mois"])["temperature_moy_c"].mean()
    resume = {}
    for zone in profil.index.get_level_values(0).unique():
        p = profil[zone]
        # Pas de 'tendance climatique' chiffrée : 5 ans sont bien trop courts pour cela.
        resume[zone] = {
            "mois_le_plus_chaud": int(p.idxmax()), "temperature_mois_chaud_c": round(p.max(), 1),
            "mois_le_plus_froid": int(p.idxmin()), "temperature_mois_froid_c": round(p.min(), 1),
            "amplitude_saisonniere_c": round(p.max() - p.min(), 1),
        }
    annuel = (mensuel[mensuel["zone"] == "France"].groupby("annee")
              .filter(lambda g: len(g) == 12).groupby("annee")["temperature_moy_c"].mean().round(2))
    chiffres = {"par_zone": resume, "temperature_annuelle_france_c": annuel.to_dict()}
    return {"saisons_mois": mensuel, "tendance_mois": tendance}, chiffres


# --- Q4 : Jours aux conditions extrêmes ---

def q4(jours: pd.DataFrame) -> tuple[dict, dict]:
    d = jours.copy()
    criteres = list(SEUILS_EXTREMES)
    for nom, (col, op, seuil) in SEUILS_EXTREMES.items():
        d[nom] = {">=": d[col] >= seuil, "<=": d[col] <= seuil, "<": d[col] < seuil}[op]

    # Seuils relatifs : le 1 % des jours les plus extrêmes de chaque ville.
    relatifs = {"chaleur_p99": ("temperature_max_c", 0.99, ">="), "froid_p1": ("temperature_min_c", 0.01, "<="),
                "pluie_p99": ("precipitation_mm", 0.99, ">="), "rafale_p99": ("rafale_max_ms", 0.99, ">=")}
    for nom, (col, q, op) in relatifs.items():
        seuil = d.groupby("ville")[col].transform(lambda s: s.quantile(q))
        d[nom] = d[col] >= seuil if op == ">=" else d[col] <= seuil
    criteres += list(relatifs)

    d["nb_criteres"] = d[criteres].sum(axis=1)
    d["criteres"] = d[criteres].apply(lambda r: ", ".join(c for c in criteres if r[c]), axis=1)
    extremes = d[d["nb_criteres"] > 0][["ville", "jour", "nb_criteres", "criteres", "temperature_min_c",
                                        "temperature_max_c", "precipitation_mm", "rafale_max_ms",
                                        "visibility_min_m"] + criteres].sort_values(["nb_criteres", "jour"],
                                                                                    ascending=[False, False])
    absolus = list(SEUILS_EXTREMES)
    chiffres = {
        "nb_jours_par_critere_absolu": {c: int(d[c].sum()) for c in absolus},
        "nb_jours_par_ville_et_critere": d.groupby("ville")[absolus].sum().astype(int).to_dict("index"),
        "record_chaleur": d.loc[d["temperature_max_c"].idxmax(), ["ville", "jour", "temperature_max_c"]]
            .astype(str).to_dict(),
        "record_froid": d.loc[d["temperature_min_c"].idxmin(), ["ville", "jour", "temperature_min_c"]]
            .astype(str).to_dict(),
        "record_pluie": d.loc[d["precipitation_mm"].idxmax(), ["ville", "jour", "precipitation_mm"]]
            .astype(str).to_dict(),
        "record_rafale": d.loc[d["rafale_max_ms"].idxmax(), ["ville", "jour", "rafale_max_ms"]]
            .astype(str).to_dict(),
    }
    return {"jours_extremes": extremes}, chiffres


# --- Programme principal ---

def main() -> None:
    s3 = client_minio()
    lire = lambda nom: lire_parquet(s3, config.BUCKET_GOLD, f"{config.SOURCE}/{nom}.parquet")
    jours, france, detail = lire("meteo_ville_jour"), lire("meteo_france_jour"), lire("meteo_ville_heure_detail")
    for t in (jours, france):
        t["jour"] = pd.to_datetime(t["jour"])

    resultats, tables = {}, {}
    for nom, fonction, args in [("q1_periodes_anormales", q1, (jours, france)),
                                ("q2_visibilite", q2, (detail,)),
                                ("q3_saisons", q3, (jours, france)),
                                ("q4_jours_extremes", q4, (jours,))]:
        print(f"Calcul de {nom}...")
        t, chiffres = fonction(*args)
        tables |= t
        resultats[nom] = chiffres

    for nom, table in tables.items():
        ecrire_parquet(s3, table, config.BUCKET_GOLD, f"{DOSSIER}/{nom}.parquet")
        print(f"  gold/{DOSSIER}/{nom}.parquet : {len(table):,} lignes".replace(",", " "))

    resultats["periode"] = {"debut": f"{jours['jour'].min():%d/%m/%Y}", "fin": f"{jours['jour'].max():%d/%m/%Y}"}
    texte = json.dumps(resultats, ensure_ascii=False, indent=2, default=str)
    ecrire_octets(s3, config.BUCKET_GOLD, f"{DOSSIER}/resultats.json", texte.encode("utf-8"), "application/json")
    print(f"  gold/{DOSSIER}/resultats.json\n")
    print(texte)


if __name__ == "__main__":
    main()
