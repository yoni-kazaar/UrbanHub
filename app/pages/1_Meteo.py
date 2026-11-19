# Page de la Partie 1 : météo (Météo-France, 2022 à aujourd'hui).
# Les calculs sont faits par partie1_meteo/analyses.py ; la page ne fait que les afficher.
import json

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import donnees  # noqa: F401  (rend common/ importable)
from common.lake import fs, lire_parquet
from common.villes import VILLES

st.set_page_config(page_title="Météo - UrbanHub", page_icon="🌦️", layout="wide")
st.title("Météo")
st.caption("Données horaires Météo-France (data.gouv.fr), toutes les stations de France métropolitaine. "
           "Une ville = moyenne de ses stations à moins de 30 km.")

MOIS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]
LIBELLES_CRITERES = {
    "chaleur_35c": "Chaleur ≥ 35 °C", "gel_moins5c": "Gel ≤ -5 °C", "pluie_30mm": "Pluie ≥ 30 mm",
    "rafale_100kmh": "Rafales ≥ 100 km/h", "brouillard_200m": "Brouillard < 200 m",
    "chaleur_p99": "Chaleur (1 % des jours les plus chauds)", "froid_p1": "Froid (1 % des plus froids)",
    "pluie_p99": "Pluie (1 % des plus pluvieux)", "rafale_p99": "Rafales (1 % des plus venteux)",
}


@st.cache_data(ttl=600)
def lire(nom):
    """Table Gold météo, ou None si elle n'est pas encore produite."""
    try:
        return lire_parquet("gold", f"meteo/{nom}.parquet")
    except FileNotFoundError:
        return None


@st.cache_data(ttl=600)
def resultats():
    try:
        with fs().open("gold/meteo/analyses/resultats.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None


jours = lire("meteo_ville_jour")
if jours is None:
    st.warning("Tables Gold météo pas encore produites : lancez `partie1_meteo.gold` puis `partie1_meteo.analyses`.")
    st.stop()
chiffres = resultats() or {}
jours["jour"] = pd.to_datetime(jours["jour"])

# --- Filtres (barre latérale) ---
villes = st.sidebar.multiselect("Villes", list(VILLES), default=list(VILLES))
debut, fin = jours["jour"].min().date(), jours["jour"].max().date()
periode = st.sidebar.date_input("Période", (debut, fin), min_value=debut, max_value=fin)
if len(periode) != 2 or not villes:
    st.info("Choisissez au moins une ville et une période complète.")
    st.stop()
d0, d1 = pd.Timestamp(periode[0]), pd.Timestamp(periode[1])


def filtrer(df, col="jour", ville_col="ville"):
    df = df[(df[col] >= d0) & (df[col] <= d1)]
    return df[df[ville_col].isin(villes)] if ville_col in df.columns else df


# --- Indicateurs ---
j = filtrer(jours)
stations = lire("meteo_stations")
k1, k2, k3, k4 = st.columns(4)
k1.metric("Stations en France", f"{len(stations):,}".replace(",", " ") if stations is not None else "-")
k2.metric("Jours analysés", f"{j['jour'].nunique():,}".replace(",", " "))
k3.metric("Température moyenne", f"{j['temperature_moy_c'].mean():.1f} °C")
k4.metric("Dernier jour disponible", f"{jours['jour'].max():%d/%m/%Y}")

onglets = st.tabs(["Saisons", "Périodes anormales", "Visibilité", "Jours extrêmes", "Stations"])

# --- Q3 : Évolution saisonnière ---
with onglets[0]:
    st.subheader("Quelle est l'évolution saisonnière de la température, en France et dans les villes ?")
    saisons = lire("analyses/saisons_mois")
    saisons["mois_date"] = pd.to_datetime(saisons["mois_date"])
    s = saisons[saisons["zone"].isin(["France"] + villes) & (saisons["mois_date"] >= d0.to_period("M").to_timestamp())
                & (saisons["mois_date"] <= d1)]
    fig = px.line(s, x="mois_date", y="temperature_moy_c", color="zone",
                  labels={"mois_date": "", "temperature_moy_c": "Température moyenne (°C)", "zone": ""})
    fig.update_traces(selector={"name": "France"}, line={"width": 4, "color": "black"})
    st.plotly_chart(fig, width="stretch")

    col_g, col_d = st.columns(2)
    with col_g:
        profil = s.groupby(["zone", "mois"], as_index=False)["temperature_moy_c"].mean()
        profil["mois_nom"] = profil["mois"].map(lambda m: MOIS[m - 1])
        fig = px.line(profil, x="mois_nom", y="temperature_moy_c", color="zone", markers=True,
                      title="Profil saisonnier moyen", category_orders={"mois_nom": MOIS},
                      labels={"mois_nom": "", "temperature_moy_c": "°C", "zone": ""})
        st.plotly_chart(fig, width="stretch")
    with col_d:
        zone = st.selectbox("Zone", ["France"] + villes, key="zone_saison")
        z = saisons[saisons["zone"] == zone].pivot(index="annee", columns="mois", values="temperature_moy_c")
        z.columns = [MOIS[m - 1] for m in z.columns]
        fig = px.imshow(z, text_auto=".1f", aspect="auto", color_continuous_scale="RdBu_r",
                        title=f"Température moyenne par mois - {zone}", labels={"color": "°C", "x": "", "y": ""})
        st.plotly_chart(fig, width="stretch")

    par_zone = chiffres.get("q3_saisons", {}).get("par_zone", {})
    if par_zone:
        tableau = pd.DataFrame(par_zone).T.loc[[z for z in ["France"] + villes if z in par_zone]]
        tableau["mois_le_plus_chaud"] = tableau["mois_le_plus_chaud"].map(lambda m: MOIS[int(m) - 1])
        tableau["mois_le_plus_froid"] = tableau["mois_le_plus_froid"].map(lambda m: MOIS[int(m) - 1])
        st.dataframe(tableau, width="stretch", column_config={
            "mois_le_plus_chaud": "Mois le plus chaud", "temperature_mois_chaud_c": st.column_config.NumberColumn("Temp. (°C)", format="%.1f"),
            "mois_le_plus_froid": "Mois le plus froid", "temperature_mois_froid_c": st.column_config.NumberColumn("Temp. (°C)", format="%.1f"),
            "amplitude_saisonniere_c": st.column_config.NumberColumn("Écart été - hiver (°C)", format="%.1f"),
        })
    st.caption("Cinq ans suffisent pour décrire le cycle des saisons, pas pour mesurer une tendance climatique.")

# --- Q1 : Périodes anormales ---
with onglets[1]:
    st.subheader("Peut-on identifier des périodes météorologiques anormales ?")
    st.markdown("Pour chaque jour, on compare la température à la **normale** du même jour de l'année "
                "(moyenne 2022-2026, lissée sur ±7 jours). Une **période anormale** = au moins 3 jours de suite "
                "à plus de 2 écarts-types de la normale. En complément, un modèle d'IA (**Isolation Forest**) "
                "repère les 1 % de jours les plus atypiques en combinant toutes les variables.")
    anomalies = lire("analyses/anomalies_jour")
    anomalies["jour"] = pd.to_datetime(anomalies["jour"])
    periodes = lire("analyses/periodes_anormales")
    for c in ("debut", "fin"):
        periodes[c] = pd.to_datetime(periodes[c])

    ville = st.selectbox("Ville", villes, key="ville_anomalie")
    a = anomalies[(anomalies["ville"] == ville) & anomalies["jour"].between(d0, d1)]
    fig = go.Figure()
    fig.add_bar(x=a["jour"], y=a["ecart_c"], name="Écart à la normale (°C)",
                marker_color=a["ecart_c"].map(lambda e: "#d62728" if e > 0 else "#1f77b4"))
    ia = a[a["anomalie_ia"]]
    fig.add_scatter(x=ia["jour"], y=ia["ecart_c"], mode="markers", name="Jour atypique (IA)",
                    marker={"symbol": "x", "size": 10, "color": "black"},
                    customdata=ia["cause_ia"], hovertemplate="%{x|%d/%m/%Y}<br>cause : %{customdata}<extra></extra>")
    for p in periodes[(periodes["ville"] == ville) & (periodes["fin"] >= d0) & (periodes["debut"] <= d1)].itertuples():
        fig.add_vrect(x0=p.debut, x1=p.fin + pd.Timedelta(days=1), opacity=0.25, line_width=0,
                      fillcolor="red" if p.type == "chaud" else "blue")
    fig.update_layout(yaxis_title="Écart à la normale (°C)", height=420, legend={"orientation": "h"})
    st.plotly_chart(fig, width="stretch")

    col_g, col_d = st.columns(2)
    with col_g:
        st.markdown("**Périodes anormales (France et villes choisies)**")
        p = periodes[periodes["ville"].isin(["France"] + villes) & (periodes["fin"] >= d0) & (periodes["debut"] <= d1)]
        st.dataframe(p.sort_values("debut", ascending=False), hide_index=True, width="stretch", column_config={
            "debut": st.column_config.DateColumn("Début", format="DD/MM/YYYY"),
            "fin": st.column_config.DateColumn("Fin", format="DD/MM/YYYY"),
            "duree_jours": "Durée (j)", "ecart_moyen_c": "Écart moyen (°C)", "z_max": "Écart max (σ)",
            "temperature_moy_c": "Temp. moyenne (°C)",
        })
    with col_d:
        st.markdown("**Jours atypiques selon l'IA : variable en cause**")
        causes = anomalies[anomalies["anomalie_ia"] & anomalies["ville"].isin(villes)]["cause_ia"].value_counts()
        st.plotly_chart(px.bar(x=causes.index, y=causes.values, labels={"x": "", "y": "Nombre de jours"}),
                        width="stretch")

# --- Q2 : Visibilité ---
with onglets[2]:
    st.subheader("Existe-t-il une corrélation entre conditions météorologiques et visibilité ?")
    correlations = lire("analyses/visibilite_correlations")
    classes = lire("analyses/visibilite_classes")
    brouillard = lire("analyses/brouillard_mois_heure")

    zone = st.selectbox("Zone", ["Toutes villes"] + villes, key="zone_visi")
    c = correlations[correlations["ville"] == zone].sort_values("spearman")
    fig = px.bar(c, x="spearman", y="libelle", orientation="h", range_x=[-1, 1],
                 color="spearman", color_continuous_scale="RdBu", range_color=[-1, 1],
                 labels={"spearman": "Corrélation de Spearman avec la visibilité", "libelle": ""})
    st.plotly_chart(fig, width="stretch")
    st.caption("Négatif : quand la variable augmente, la visibilité baisse. Spearman mesure un lien monotone, "
               "même non linéaire, et résiste aux valeurs extrêmes.")

    col_g, col_d = st.columns(2)
    with col_g:
        fig = px.bar(classes, x="classe", y="visibilite_mediane_m", facet_col="critere",
                     labels={"classe": "", "visibilite_mediane_m": "Visibilité médiane (m)"},
                     title="Visibilité selon l'humidité et la pluie (toutes villes)")
        fig.update_xaxes(matches=None)
        fig.for_each_annotation(lambda a: a.update(text=a.text.split("=")[-1].capitalize()))
        st.plotly_chart(fig, width="stretch")
    with col_d:
        ville_b = st.selectbox("Ville", villes, key="ville_brouillard")
        b = brouillard[brouillard["ville"] == ville_b].pivot(index="mois", columns="heure_locale", values="part_heures_pct")
        b.index = [MOIS[m - 1] for m in b.index]
        fig = px.imshow(b, aspect="auto", color_continuous_scale="Greys",
                        labels={"x": "Heure (Paris)", "y": "", "color": "% des heures"},
                        title=f"Brouillard (visibilité < 1 km) - {ville_b}")
        st.plotly_chart(fig, width="stretch")

# --- Q4 : Jours extrêmes ---
with onglets[3]:
    st.subheader("Quels sont les jours présentant des conditions météorologiques extrêmes ?")
    st.markdown("Deux types de seuils : **absolus** (35 °C, -5 °C, 30 mm de pluie, rafales de 100 km/h, "
                "brouillard < 200 m) et **relatifs** à chaque ville (le 1 % des jours les plus extrêmes).")
    extremes = lire("analyses/jours_extremes")
    extremes["jour"] = pd.to_datetime(extremes["jour"])
    e = filtrer(extremes)

    absolus = ["chaleur_35c", "gel_moins5c", "pluie_30mm", "rafale_100kmh", "brouillard_200m"]
    compte = e.groupby("ville")[absolus].sum().reset_index().melt("ville", var_name="critere", value_name="jours")
    compte["critere"] = compte["critere"].map(LIBELLES_CRITERES)
    st.plotly_chart(px.bar(compte, x="ville", y="jours", color="critere", barmode="group",
                           labels={"ville": "", "jours": "Nombre de jours", "critere": ""}), width="stretch")

    ville_e = st.selectbox("Ville", villes, key="ville_extremes")
    cal = jours[(jours["ville"] == ville_e) & jours["jour"].between(d0, d1)][["jour"]].merge(
        e[e["ville"] == ville_e][["jour", "nb_criteres", "criteres"]], on="jour", how="left").fillna({"nb_criteres": 0})
    cal["annee"], cal["semaine"] = cal["jour"].dt.year, cal["jour"].dt.isocalendar().week
    fig = px.density_heatmap(cal, x="semaine", y="annee", z="nb_criteres", histfunc="max", nbinsx=53,
                             color_continuous_scale="OrRd", labels={"semaine": "Semaine de l'année", "annee": "",
                                                                    "nb_criteres": "Critères"},
                             title=f"Calendrier des jours extrêmes - {ville_e}")
    fig.update_yaxes(type="category")
    st.plotly_chart(fig, width="stretch")

    top = e[e["ville"] == ville_e].sort_values(["nb_criteres", "jour"], ascending=[False, False]).head(10).copy()
    top["criteres"] = top["criteres"].map(lambda t: ", ".join(LIBELLES_CRITERES.get(c, c) for c in t.split(", ")))
    st.markdown(f"**Les 10 jours les plus extrêmes - {ville_e}**")
    st.dataframe(top[["jour", "criteres", "temperature_min_c", "temperature_max_c", "precipitation_mm",
                      "rafale_max_ms", "visibility_min_m"]], hide_index=True, width="stretch", column_config={
        "jour": st.column_config.DateColumn("Jour", format="DD/MM/YYYY"), "criteres": "Critères",
        "temperature_min_c": st.column_config.NumberColumn("Min (°C)", format="%.1f"),
        "temperature_max_c": st.column_config.NumberColumn("Max (°C)", format="%.1f"),
        "precipitation_mm": st.column_config.NumberColumn("Pluie (mm)", format="%.1f"),
        "rafale_max_ms": st.column_config.NumberColumn("Rafale (m/s)", format="%.1f"),
        "visibility_min_m": st.column_config.NumberColumn("Visibilité min (m)", format="%.0f"),
    })

# --- Carte des stations ---
with onglets[4]:
    st.subheader("Stations météo")
    if stations is not None:
        carte = stations.copy()
        carte["rattachement"] = carte["ville"].fillna("Hors des 8 villes")
        seulement = st.toggle("Seulement les stations des villes choisies", value=False)
        if seulement:
            carte = carte[carte["ville"].isin(villes)]
        fig = px.scatter_map(carte, lat="latitude", lon="longitude", color="temperature_moy_periode_c",
                             color_continuous_scale="RdYlBu_r", hover_name="station_name",
                             hover_data={"rattachement": True, "altitude_m": True, "temperature_moy_periode_c": ":.1f",
                                         "latitude": False, "longitude": False},
                             labels={"temperature_moy_periode_c": "Temp. moyenne (°C)"},
                             zoom=4.6 if not seulement else 5, center={"lat": 46.6, "lon": 2.4}, height=620)
        fig.update_layout(map_style="open-street-map", margin=dict(l=0, r=0, t=0, b=0))
        st.plotly_chart(fig, width="stretch")
        st.caption(f"{len(stations):,} stations actives depuis 2022, dont "
                   f"{stations['ville'].notna().sum()} rattachées aux 8 villes.".replace(",", " "))
