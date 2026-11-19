# Page de la Partie 3 (Personne C) : pollution de l'air, capteurs OpenAQ.
# Lit gold/pollution/pollution_ville_heure.parquet (table du contrat) et
# gold/pollution/capteurs_pollution.parquet (une ligne par capteur, pour la carte).
# Stockage en UTC, affichage à l'heure de Paris (colonne heure_locale fournie par donnees.py).
import os

import pandas as pd
import plotly.express as px
import streamlit as st

from donnees import exiger
from common.lake import lire_parquet

st.set_page_config(page_title="Pollution – UrbanHub", page_icon="🌫️", layout="wide")
st.title("🌫️ Pollution de l'air")

POLLUANTS = ["pm25", "pm10", "no2", "o3", "co"]
NOMS = {"pm25": "PM2.5", "pm10": "PM10", "no2": "NO2", "o3": "O3", "co": "CO"}
VILLES = ["Paris", "Lyon", "Marseille", "Toulouse", "Lille", "Bordeaux", "Nantes", "Strasbourg"]
# Lignes directrices de l'OMS (2021), en µg/m³ : 24 h (O3 : maximum de la moyenne sur 8 h)
OMS_JOUR = {"pm25": 15, "pm10": 45, "no2": 25, "o3": 100, "co": 4000}
PERIODES = {"7 derniers jours": 7, "30 derniers jours": 30, "90 derniers jours": 90, "12 derniers mois": 365, "Tout": None}


@st.cache_data(ttl=600)
def charger_capteurs():
    """Table des capteurs (position, moyenne sur 7 jours), ou None si elle n'existe pas (fausses tables)."""
    if os.environ.get("URBANHUB_FAKE") == "1":
        return None
    try:
        return lire_parquet("gold", "pollution/capteurs_pollution.parquet")
    except Exception:
        return None


def indicateurs_journaliers(g):
    """Indicateur comparable à l'OMS, par jour (heure de Paris) : moyenne 24 h, ou max de la moyenne 8 h pour l'O3."""
    h = g.set_index("heure_locale").sort_index()[POLLUANTS].asfreq("h")
    nb = h.notna().resample("D").sum()
    jour = h.resample("D").mean()
    jour["o3"] = h["o3"].rolling(8, min_periods=6).mean().resample("D").max()
    jour = jour.where(nb >= 18)                       # journée gardée si au moins 18 h mesurées
    jour.index = jour.index.tz_localize(None)
    jour.index.name = "jour"
    return jour


pollution = exiger("pollution")
capteurs = charger_capteurs()
derniere_heure = pollution["heure_locale"].max()

# ----------------------------------------------------------------------------- filtres
st.sidebar.header("Pollution")
ville = st.sidebar.selectbox("Ville", VILLES, index=0)
polluant = st.sidebar.selectbox("Polluant", POLLUANTS, format_func=NOMS.get, index=0)
periode = st.sidebar.radio("Période", list(PERIODES), index=1)
st.sidebar.caption(f"Seuil OMS 24 h pour {NOMS[polluant]} : **{OMS_JOUR[polluant]} µg/m³**"
                   + (" (max de la moyenne sur 8 h)" if polluant == "o3" else ""))

nb_jours = PERIODES[periode]
debut = derniere_heure - pd.Timedelta(days=nb_jours) if nb_jours else pollution["heure_locale"].min()
g_ville = pollution[pollution["ville"] == ville]
g_periode = g_ville[g_ville["heure_locale"] >= debut]
jours = indicateurs_journaliers(g_ville)
jours_p = jours[jours.index >= debut.tz_localize(None).normalize()]

st.caption(f"Capteurs OpenAQ (flux IoT) · données jusqu'au {derniere_heure:%d/%m/%Y à %H h} (heure de Paris) · "
           f"seuils : lignes directrices de l'OMS 2021")

# ----------------------------------------------------------------------------- dernières mesures
st.subheader(f"{ville} : dernières mesures")
for col, p in zip(st.columns(len(POLLUANTS)), POLLUANTS):
    serie = g_ville.dropna(subset=[p])
    if serie.empty:
        col.metric(NOMS[p], "non mesuré")
        continue
    derniere = serie.sort_values("heure").iloc[-1]
    col.metric(NOMS[p], f"{derniere[p]:.0f} µg/m³", f"{derniere[p] / OMS_JOUR[p]:.1f} × seuil OMS", delta_color="inverse",
               help=f"Mesure du {derniere['heure_locale']:%d/%m à %H h}. Seuil OMS 24 h : {OMS_JOUR[p]} µg/m³.")

# ----------------------------------------------------------------------------- alertes
st.subheader("Alertes de dépassement")
veille = jours.dropna(how="all").tail(1)
if veille.empty:
    st.info("Pas assez de mesures pour calculer la dernière journée.")
else:
    depasses = [f"{NOMS[p]} : {veille[p].iloc[0]:.0f} µg/m³ (seuil {OMS_JOUR[p]})"
                for p in POLLUANTS if pd.notna(veille[p].iloc[0]) and veille[p].iloc[0] > OMS_JOUR[p]]
    titre = f"**{ville}, journée du {veille.index[0]:%d/%m/%Y}**"
    if depasses:
        st.error(f"{titre} : seuil OMS dépassé pour " + " · ".join(depasses))
    else:
        st.success(f"{titre} : aucun polluant au-dessus des seuils OMS.")

dep = jours_p.stack().rename("valeur").reset_index()
dep.columns = ["jour", "polluant", "valeur"]
dep["seuil OMS"] = dep["polluant"].map(OMS_JOUR)
dep = dep[dep["valeur"] > dep["seuil OMS"]].copy()
dep["× seuil"] = dep["valeur"] / dep["seuil OMS"]
dep["polluant"] = dep["polluant"].map(NOMS)

col_resume, col_liste = st.columns([1, 2])
with col_resume:
    resume = pd.DataFrame({"jours au-dessus": (jours_p > pd.Series(OMS_JOUR)).sum(),
                           "jours mesurés": jours_p.notna().sum()}).rename(index=NOMS)
    st.dataframe(resume, width="stretch")
with col_liste:
    if dep.empty:
        st.write("Aucun dépassement sur la période.")
    else:
        st.dataframe(dep.sort_values("jour", ascending=False).reset_index(drop=True), width="stretch", height=250,
                     column_config={"jour": st.column_config.DateColumn("jour", format="DD/MM/YYYY"),
                                    "valeur": st.column_config.NumberColumn("valeur (µg/m³)", format="%.1f"),
                                    "× seuil": st.column_config.NumberColumn(format="%.1f")})

# ----------------------------------------------------------------------------- carte des capteurs
st.subheader(f"Carte des capteurs – {NOMS[polluant]} (moyenne des 7 derniers jours)")
if capteurs is None:
    st.info("Table des capteurs pas encore publiée (gold/pollution/capteurs_pollution.parquet).")
else:
    carte = capteurs[(capteurs["pollutant"] == polluant) & capteurs["moyenne_7j"].notna()].copy()
    if carte.empty:
        st.info(f"Aucun capteur {NOMS[polluant]} actif ces 7 derniers jours.")
    else:
        carte["× seuil OMS"] = carte["moyenne_7j"] / OMS_JOUR[polluant]
        carte["niveau"] = pd.cut(carte["× seuil OMS"], [-1, 1, 2, float("inf")],
                                 labels=["sous le seuil OMS", "1 à 2 × le seuil", "plus de 2 × le seuil"])
        centre = carte[carte["ville"] == ville]
        zoom, centre = (10, centre) if not centre.empty else (4.6, carte)
        fig = px.scatter_map(carte, lat="latitude", lon="longitude", color="niveau", hover_name="location_name",
                             hover_data={"ville": True, "moyenne_7j": ":.1f", "× seuil OMS": ":.1f",
                                         "latitude": False, "longitude": False, "niveau": False},
                             color_discrete_map={"sous le seuil OMS": "#2ca02c", "1 à 2 × le seuil": "#ff9f0e",
                                                 "plus de 2 × le seuil": "#d62728"},
                             category_orders={"niveau": ["sous le seuil OMS", "1 à 2 × le seuil", "plus de 2 × le seuil"]},
                             zoom=zoom, center={"lat": centre["latitude"].mean(), "lon": centre["longitude"].mean()},
                             height=480)
        fig.update_traces(marker={"size": 12})
        fig.update_layout(map_style="open-street-map", margin=dict(l=0, r=0, t=0, b=0), legend_title_text="")
        st.plotly_chart(fig, width="stretch")

# ----------------------------------------------------------------------------- courbe sur 24 h
st.subheader(f"{ville} – {NOMS[polluant]} au cours de la journée ({periode.lower()})")
profil = g_periode.dropna(subset=[polluant])
if profil.empty:
    st.info(f"{NOMS[polluant]} n'est pas mesuré à {ville} sur cette période.")
else:
    profil = profil.assign(heure_du_jour=profil["heure_locale"].dt.hour,
                           jours=profil["heure_locale"].dt.dayofweek.map(lambda j: "samedi-dimanche" if j >= 5 else "lundi-vendredi"))
    courbe = profil.groupby(["heure_du_jour", "jours"], as_index=False)[polluant].mean()
    fig = px.line(courbe, x="heure_du_jour", y=polluant, color="jours", markers=True,
                  labels={"heure_du_jour": "heure (Paris)", polluant: "µg/m³", "jours": ""})
    fig.update_xaxes(dtick=2)
    st.plotly_chart(fig, width="stretch")

# ----------------------------------------------------------------------------- évolution jour par jour
st.subheader(f"{ville} – {NOMS[polluant]} jour par jour")
evol = jours_p[polluant].dropna()
if evol.empty:
    st.info("Pas de données journalières sur cette période.")
else:
    fig = px.line(evol.reset_index(), x="jour", y=polluant, labels={"jour": "", polluant: "µg/m³"})
    fig.add_hline(y=OMS_JOUR[polluant], line_dash="dash", line_color="red",
                  annotation_text=f"seuil OMS 24 h ({OMS_JOUR[polluant]})")
    st.plotly_chart(fig, width="stretch")

# ----------------------------------------------------------------------------- comparaison des villes
st.subheader(f"Comparaison des villes – {NOMS[polluant]} moyen ({periode.lower()})")
comp = (pollution[pollution["heure_locale"] >= debut].groupby("ville")[polluant].mean()
        .reindex(VILLES).dropna().sort_values().reset_index())
if not comp.empty:
    comp["sélection"] = comp["ville"].eq(ville).map({True: ville, False: "autres villes"})
    fig = px.bar(comp, x=polluant, y="ville", orientation="h", color="sélection",
                 color_discrete_map={ville: "#d62728", "autres villes": "#4c72b0"},
                 labels={polluant: "µg/m³", "ville": "", "sélection": ""})
    fig.update_layout(showlegend=False)
    st.plotly_chart(fig, width="stretch")