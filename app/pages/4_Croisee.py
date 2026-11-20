# Page de la Partie 4 : analyse croisée météo × vélos × pollution, jointure sur ville + heure.
# Les réponses aux 4 questions sont calculées à partir des données : elles se mettent à jour avec les vraies tables Gold.
import pandas as pd
import plotly.express as px
import streamlit as st

from donnees import charger_croise, exiger, filtres

st.set_page_config(page_title="Analyse croisée - UrbanHub", page_icon="🔗", layout="wide")
st.title("Analyse croisée")

meteo, velos, pollution = exiger("meteo"), exiger("velos"), exiger("pollution")
df = (meteo.merge(velos.drop(columns="heure_locale"), on=["ville", "heure"], how="inner")
           .merge(pollution.drop(columns="heure_locale"), on=["ville", "heure"], how="inner"))
df = filtres(df)
if df.empty:
    st.warning("Aucune heure commune aux trois sources pour ces filtres.")
    st.stop()
# Un taux d'occupation bas veut dire beaucoup de vélos sortis : on l'inverse pour parler d'usage.
df["usage_velos"] = 1 - df["taux_occupation"]

nb_heures = df["heure"].nunique()
st.caption(f"{len(df):,} lignes (ville x heure) sur {nb_heures} heures communes aux trois sources, "
           f"du {df['heure_locale'].min():%d/%m/%Y %H:%M} au {df['heure_locale'].max():%d/%m/%Y %H:%M} (heure de Paris).")
if nb_heures < 24 * 14:
    st.warning(f"Seulement {nb_heures} heures communes : la collecte des vélos et de la pollution vient de démarrer. "
               "Les réponses ci-dessous sont indicatives et changeront avec plus de données.")

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
df["tranche_temp"] = pd.cut(df["temperature_c"], [-50, 5, 12, 20, 28, 60], labels=["< 5 °C", "5-12 °C", "12-20 °C", "20-28 °C", "> 28 °C"])
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
usage = df.dropna(subset=["usage_velos"]).groupby("favorable")["usage_velos"].mean()
texte = f"**{favorable.mean():.0%}** des heures sont favorables."
if {True, False} <= set(usage.index):
    texte += f" Pendant ces heures, {usage[True]:.0%} des vélos sont sortis, contre {usage[False]:.0%} le reste du temps."
st.markdown(texte)
part = df.groupby("ville", as_index=False)["favorable"].mean().sort_values("favorable", ascending=False)
st.plotly_chart(px.bar(part, x="ville", y="favorable", range_y=[0, 1], title="Part des heures favorables par ville",
                       labels={"favorable": "Part des heures", "ville": ""}).update_yaxes(tickformat=".0%"), width="stretch")

# --- Question 4 ---------------------------------------------------------------
st.header("4. Périodes où mobilité, pollution et météo interagissent fortement")
st.caption("Pour chaque ville et chaque heure, on mesure l'écart à la normale de la ville (z-score) de l'usage des vélos, "
           "du NO2 et de la température. Une heure est retenue quand les trois s'écartent fortement en même temps (|z| >= seuil).")
cols = ["usage_velos", "no2", "temperature_c"]
inter = df[["ville", "heure_locale"] + cols].copy()
for c in cols:
    inter[f"z_{c}"] = inter.groupby("ville")[c].transform(lambda s: (s - s.mean()) / s.std())
seuil = st.slider("Seuil d'écart (z-score)", 0.5, 2.5, 1.0, 0.1)
z = inter[[f"z_{c}" for c in cols]]
forts = inter[z.abs().ge(seuil).all(axis=1)].assign(intensite=z.abs().sum(axis=1)).sort_values("intensite", ascending=False)
st.markdown(f"**{len(forts)}** heures (ville x heure) sur {len(inter)} dépassent le seuil pour les trois à la fois.")
st.dataframe(forts.drop(columns="intensite").head(50).round(2), width="stretch", hide_index=True, column_config={
    "heure_locale": st.column_config.DatetimeColumn("Heure (Paris)", format="DD/MM HH:mm"),
    "usage_velos": st.column_config.NumberColumn("Usage vélos", format="%.2f"),
    "no2": st.column_config.NumberColumn("NO2 (µg/m³)", format="%.1f"),
    "temperature_c": st.column_config.NumberColumn("Temp. (°C)", format="%.1f"),
})

# --- Modèle IA -----------------------------------------------------------------
st.header("Modèle : usage des vélos prédit par la météo")
scores, metriques = charger_croise()
if scores is None:
    st.info("Modèle pas encore calculé : lancer `python -m partie4_croisee.modele`.")
    st.stop()
m, r = metriques["modele"], metriques["reference"]
st.caption("Régression linéaire (Ridge) sur la météo, l'heure de la journée, le week-end et la ville "
           "(partie4_croisee/modele.py). Validation sur les 20 % d'heures les plus récentes, pas au hasard.")
if not metriques["fiable"]:
    st.warning(f"Entraîné sur {metriques['heures_communes']} heures communes seulement ({metriques['lignes_train']} lignes "
               f"d'entraînement, {metriques['lignes_test']} de test). Ces chiffres ne permettent pas de conclure : "
               "il faut au moins deux semaines de collecte pour que le modèle ait du sens.")
c1, c2, c3 = st.columns(3)
c1.metric("Erreur moyenne du modèle (MAE)", f"{m['mae']:.3f}", f"{m['mae'] - r['mae']:+.3f} vs référence", delta_color="inverse")
c2.metric("R² du modèle", "-" if m["r2"] is None else f"{m['r2']:.2f}")
c3.metric("R² de la référence (moyenne par ville)", "-" if r["r2"] is None else f"{r['r2']:.2f}")

col_g, col_d = st.columns(2)
with col_g:
    effets = pd.DataFrame({"variable": [METEO[k] for k in metriques["effets_meteo"]], "effet": list(metriques["effets_meteo"].values())})
    st.plotly_chart(px.bar(effets, x="effet", y="variable", orientation="h", title="Effet de chaque variable météo",
                           labels={"effet": "Variation de l'usage pour +1 écart-type", "variable": ""}), width="stretch")
with col_d:
    st.markdown("**Score 'conditions favorables au vélo'** (0 à 100) : part de l'usage prédit due à la météo, "
                "classée en percentile, moins 20 points si l'air dépasse un seuil OMS.")
    scores["heure"] = pd.to_datetime(scores["heure"], utc=True)
    dernier = scores.sort_values("heure").groupby("ville", as_index=False).last().sort_values("score_velo", ascending=False)
    st.plotly_chart(px.bar(dernier, x="ville", y="score_velo", range_y=[0, 100], title="Dernière heure connue",
                           labels={"score_velo": "Score", "ville": ""}), width="stretch")
