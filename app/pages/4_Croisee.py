# Page de la Partie 4 : analyse croisée météo × vélos × pollution, jointure sur ville + heure.
# Les réponses aux 4 questions sont calculées à partir des données : elles se mettent à jour avec les vraies tables Gold.
import pandas as pd
import plotly.express as px
import streamlit as st

from donnees import exiger, filtres

st.set_page_config(page_title="Analyse croisée – UrbanHub", page_icon="🔗", layout="wide")
st.title("🔗 Analyse croisée")

meteo, velos, pollution = exiger("meteo"), exiger("velos"), exiger("pollution")
df = (meteo.merge(velos.drop(columns="heure_locale"), on=["ville", "heure"], how="inner")
           .merge(pollution.drop(columns="heure_locale"), on=["ville", "heure"], how="inner"))
df = filtres(df)
if df.empty:
    st.warning("Aucune heure commune aux trois sources pour ces filtres.")
    st.stop()
# Un taux d'occupation bas veut dire beaucoup de vélos sortis : on l'inverse pour parler d'usage.
df["usage_velos"] = 1 - df["taux_occupation"]

st.caption(f"{len(df):,} heures communes aux trois sources, du {df['heure_locale'].min():%d/%m/%Y} "
           f"au {df['heure_locale'].max():%d/%m/%Y} (heure de Paris).")

METEO = {"temperature_c": "Température", "precipitation_mm": "Pluie", "wind_speed_ms": "Vent",
         "visibility_m": "Visibilité", "pressure_hpa": "Pression"}
POLLUANTS = {"pm25": "PM2.5", "pm10": "PM10", "no2": "NO2", "o3": "O3", "co": "CO"}
OMS = {"pm25": 15, "no2": 25}  # seuils journaliers OMS 2021 (µg/m³)

st.subheader("Vue d'ensemble : corrélations")
VARS = list(METEO) + ["usage_velos"] + list(POLLUANTS)
st.plotly_chart(px.imshow(df[VARS].corr(), text_auto=".2f", color_continuous_scale="RdBu_r", zmin=-1, zmax=1, aspect="auto"),
                width="stretch")
echantillon = df.sample(min(len(df), 5000), random_state=0)

# --- Question 1 ---------------------------------------------------------------
st.header("1. Relation entre météo et pollution")
corr_mp = df[list(METEO) + list(POLLUANTS)].corr().loc[list(METEO), list(POLLUANTS)]
var, pol = corr_mp.abs().stack().idxmax()
r = corr_mp.loc[var, pol]
st.markdown(f"Le lien le plus fort est entre **{METEO[var].lower()}** et **{POLLUANTS[pol]}** (r = {r:.2f}) : "
            f"quand {METEO[var].lower()} augmente, {POLLUANTS[pol]} {'augmente' if r > 0 else 'baisse'}.")
col_g, col_d = st.columns([1, 2])
with col_g:
    st.dataframe(corr_mp.rename(index=METEO, columns=POLLUANTS).round(2), width="stretch")
with col_d:
    x = st.selectbox("Variable météo", list(METEO), index=list(METEO).index(var), format_func=METEO.get, key="x_poll")
    y = st.selectbox("Polluant", list(POLLUANTS), index=list(POLLUANTS).index(pol), format_func=POLLUANTS.get)
    st.plotly_chart(px.scatter(echantillon, x=x, y=y, color="ville", opacity=0.4, trendline="ols", trendline_scope="overall"),
                    width="stretch")

# --- Question 2 ---------------------------------------------------------------
st.header("2. Influence de la météo sur l'usage des vélos")
df["pluie"] = df["precipitation_mm"].gt(0).map({True: "Pluie", False: "Sec"})
df["tranche_temp"] = pd.cut(df["temperature_c"], [-50, 5, 12, 20, 28, 60], labels=["< 5 °C", "5–12 °C", "12–20 °C", "20–28 °C", "> 28 °C"])
par_pluie = df.groupby("pluie")["usage_velos"].mean()
if {"Pluie", "Sec"} <= set(par_pluie.index):
    ecart = (par_pluie["Pluie"] / par_pluie["Sec"] - 1) * 100
    st.markdown(f"Quand il pleut, l'usage des vélos est **{ecart:+.0f} %** par rapport aux heures sèches "
                f"({par_pluie['Pluie']:.0%} contre {par_pluie['Sec']:.0%} des vélos sortis).")
col_g, col_d = st.columns(2)
with col_g:
    temp = df.groupby("tranche_temp", observed=True, as_index=False)["usage_velos"].mean()
    st.plotly_chart(px.bar(temp, x="tranche_temp", y="usage_velos", title="Usage moyen selon la température",
                           labels={"tranche_temp": "", "usage_velos": "Part des vélos sortis"}), width="stretch")
with col_d:
    # Même heure de la journée pour comparer pluie et sec sans l'effet des heures de pointe.
    profil = df.assign(h=df["heure_locale"].dt.hour).groupby(["h", "pluie"], as_index=False)["usage_velos"].mean()
    st.plotly_chart(px.line(profil, x="h", y="usage_velos", color="pluie", title="Usage par heure : pluie ou sec",
                            labels={"h": "Heure (Paris)", "usage_velos": "Part des vélos sortis", "pluie": ""}), width="stretch")

# --- Question 3 ---------------------------------------------------------------
st.header("3. Conditions favorables à la mobilité douce")
st.caption("Heure favorable : pas de pluie, entre 12 et 25 °C, vent sous 6 m/s, PM2.5 et NO2 sous les seuils OMS. "
           "Un polluant non mesuré ne compte pas comme un dépassement.")
favorable = (df["precipitation_mm"].eq(0) & df["temperature_c"].between(12, 25) & df["wind_speed_ms"].lt(6)
             & ~df["pm25"].gt(OMS["pm25"]) & ~df["no2"].gt(OMS["no2"]))
df["favorable"] = favorable
usage = df.groupby("favorable")["usage_velos"].mean()
texte = f"**{favorable.mean():.0%}** des heures sont favorables."
if {True, False} <= set(usage.index):
    texte += f" Pendant ces heures, {usage[True]:.0%} des vélos sont sortis, contre {usage[False]:.0%} le reste du temps."
st.markdown(texte)
part = df.groupby("ville", as_index=False)["favorable"].mean().sort_values("favorable", ascending=False)
st.plotly_chart(px.bar(part, x="ville", y="favorable", range_y=[0, 1], title="Part des heures favorables par ville",
                       labels={"favorable": "Part des heures", "ville": ""}).update_yaxes(tickformat=".0%"), width="stretch")

# --- Question 4 ---------------------------------------------------------------
st.header("4. Périodes où mobilité, pollution et météo interagissent fortement")
st.caption("Pour chaque ville et chaque jour, on mesure l'écart à la normale de la ville (z-score) de l'usage des vélos, "
           "du NO2 et de la température. Un jour est retenu quand les trois s'écartent fortement en même temps (|z| ≥ seuil).")
jour = df.assign(jour=df["heure_locale"].dt.date).groupby(["ville", "jour"], as_index=False)[["usage_velos", "no2", "temperature_c"]].mean()
for c in ["usage_velos", "no2", "temperature_c"]:
    jour[f"z_{c}"] = jour.groupby("ville")[c].transform(lambda s: (s - s.mean()) / s.std())
seuil = st.slider("Seuil d'écart (z-score)", 0.5, 2.5, 1.0, 0.1)
z = jour[["z_usage_velos", "z_no2", "z_temperature_c"]]
forts = jour[z.abs().ge(seuil).all(axis=1)].assign(intensite=z.abs().sum(axis=1)).sort_values("intensite", ascending=False)
st.markdown(f"**{len(forts)}** jours (ville × jour) sur {len(jour)} dépassent le seuil pour les trois à la fois.")
st.dataframe(forts.drop(columns="intensite").round(2), width="stretch", hide_index=True, column_config={
    "usage_velos": st.column_config.NumberColumn("Usage vélos", format="%.2f"),
    "no2": st.column_config.NumberColumn("NO2 (µg/m³)", format="%.1f"),
    "temperature_c": st.column_config.NumberColumn("Temp. (°C)", format="%.1f"),
})
