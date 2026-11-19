import pandas as pd
import plotly.express as px
import streamlit as st

from donnees import charger
from common.villes import VILLES

st.set_page_config(page_title="UrbanHub", page_icon="🏙️", layout="wide")
st.title("UrbanHub – Observatoire urbain")
st.caption("Météo, vélos en libre-service et qualité de l'air dans 8 grandes villes françaises.")

meteo, velos, pollution = charger("meteo"), charger("velos"), charger("pollution")


def dernier(df, cols):
    """Dernière valeur connue par ville pour les colonnes demandées."""
    if df is None:
        return pd.DataFrame({"ville": list(VILLES)})
    return df.sort_values("heure").groupby("ville")[cols].last().reset_index()


villes = pd.DataFrame([(v, lat, lon) for v, (lat, lon) in VILLES.items()], columns=["ville", "latitude", "longitude"])
villes = (villes.merge(dernier(meteo, ["temperature_c", "wind_speed_ms"]), on="ville", how="left")
                .merge(dernier(velos, ["taux_occupation"]), on="ville", how="left")
                .merge(dernier(pollution, ["pm25", "no2"]), on="ville", how="left"))

col_carte, col_kpi = st.columns([3, 2])
with col_carte:
    indicateur = st.radio("Couleur de la carte", ["pm25", "temperature_c", "taux_occupation"], horizontal=True,
                          format_func={"pm25": "PM2.5", "temperature_c": "Température", "taux_occupation": "Occupation vélos"}.get)
    fig = px.scatter_map(villes, lat="latitude", lon="longitude", color=indicateur, hover_name="ville",
                         hover_data={c: ":.1f" for c in ["temperature_c", "pm25", "no2"]} | {"taux_occupation": ":.0%", "latitude": False, "longitude": False},
                         size=[18] * len(villes), size_max=18, zoom=4.6, center={"lat": 46.6, "lon": 2.4},
                         color_continuous_scale="RdYlGn_r" if indicateur == "pm25" else "Viridis", height=560)
    fig.update_layout(map_style="open-street-map", margin=dict(l=0, r=0, t=0, b=0))
    st.plotly_chart(fig, width="stretch")

with col_kpi:
    st.subheader("Dernières mesures")
    affichage = villes.drop(columns=["latitude", "longitude"]).set_index("ville")
    st.dataframe(affichage, width="stretch", column_config={
        "temperature_c": st.column_config.NumberColumn("Temp. (°C)", format="%.1f"),
        "wind_speed_ms": st.column_config.NumberColumn("Vent (m/s)", format="%.1f"),
        "taux_occupation": st.column_config.ProgressColumn("Occupation vélos", min_value=0, max_value=1, format="%.2f"),
        "pm25": st.column_config.NumberColumn("PM2.5 (µg/m³)", format="%.1f"),
        "no2": st.column_config.NumberColumn("NO2 (µg/m³)", format="%.1f"),
    })
    for nom, df in [("Météo", meteo), ("Vélos", velos), ("Pollution", pollution)]:
        if df is None:
            st.warning(f"{nom} : table Gold absente.")
        else:
            st.caption(f"{nom} : {len(df):,} lignes, du {df['heure_locale'].min():%d/%m/%Y} au {df['heure_locale'].max():%d/%m/%Y %H:%M} (heure de Paris)")

st.info("Utilisez le menu à gauche pour explorer chaque thème, puis l'analyse croisée.")
