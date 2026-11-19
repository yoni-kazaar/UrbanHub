# Page de la Partie 4 : analyse croisée météo × vélos × pollution, jointure sur ville + heure.
import plotly.express as px
import streamlit as st

from donnees import exiger, filtres

st.set_page_config(page_title="Analyse croisée – UrbanHub", page_icon="🔗", layout="wide")
st.title("🔗 Analyse croisée")

meteo, velos, pollution = exiger("meteo"), exiger("velos"), exiger("pollution")
df = (meteo.merge(velos.drop(columns="heure_locale"), on=["ville", "heure"], how="inner")
           .merge(pollution.drop(columns="heure_locale"), on=["ville", "heure"], how="inner"))
df = filtres(df)
# Un taux d'occupation bas veut dire beaucoup de vélos sortis : on l'inverse pour parler d'usage.
df["usage_velos"] = 1 - df["taux_occupation"]

st.caption(f"{len(df):,} heures communes aux trois sources.")

VARS = ["temperature_c", "precipitation_mm", "wind_speed_ms", "visibility_m", "pressure_hpa",
        "usage_velos", "pm25", "pm10", "no2", "o3", "co"]
st.subheader("Corrélations")
st.plotly_chart(px.imshow(df[VARS].corr(), text_auto=".2f", color_continuous_scale="RdBu_r", zmin=-1, zmax=1, aspect="auto"),
                width="stretch")

col_g, col_d = st.columns(2)
echantillon = df.sample(min(len(df), 5000), random_state=0)
with col_g:
    st.subheader("Météo et pollution")
    x = st.selectbox("Variable météo", ["wind_speed_ms", "temperature_c", "precipitation_mm"], key="x_poll")
    y = st.selectbox("Polluant", ["no2", "pm25", "pm10", "o3", "co"])
    st.plotly_chart(px.scatter(echantillon, x=x, y=y, color="ville", opacity=0.4, trendline="ols", trendline_scope="overall"),
                    width="stretch")
with col_d:
    st.subheader("Météo et usage des vélos")
    x2 = st.selectbox("Variable météo", ["temperature_c", "precipitation_mm", "wind_speed_ms"], key="x_velo")
    st.plotly_chart(px.scatter(echantillon, x=x2, y="usage_velos", color="ville", opacity=0.4, trendline="ols", trendline_scope="overall"),
                    width="stretch")

st.subheader("Score « conditions favorables au vélo »")
st.caption("Score simple de 0 à 100 : température douce, pas de pluie, vent faible, air propre. À remplacer par le modèle de la Partie 4.")
score = (100
         - 3 * (df["temperature_c"] - 18).abs()
         - 15 * df["precipitation_mm"].clip(upper=4)
         - 3 * (df["wind_speed_ms"] - 4).clip(lower=0)
         - 1 * (df["pm25"].fillna(0) - 15).clip(lower=0)).clip(0, 100)
df["score_velo"] = score
par_ville = df.groupby("ville", as_index=False)["score_velo"].mean().sort_values("score_velo", ascending=False)
st.plotly_chart(px.bar(par_ville, x="ville", y="score_velo", range_y=[0, 100], labels={"score_velo": "Score moyen"}),
                width="stretch")
