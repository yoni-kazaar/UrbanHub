# Page de la Partie 2 : vélos en libre-service (CityBikes). Analyses sur Silver (par station) et Gold (par ville).
import plotly.express as px
import streamlit as st

from donnees import charger  # ajoute aussi la racine du dépôt au chemin Python
from partie2_velos import analyse
from partie2_velos.gold import lire_silver

st.set_page_config(page_title="Vélos - UrbanHub", page_icon="🚲", layout="wide")
st.title("Vélos en libre-service")


@st.cache_data(ttl=600, show_spinner="Chargement des relevés (Silver)...")
def donnees_silver():
    return analyse.preparer(lire_silver())


try:
    df = donnees_silver()
except (Exception, SystemExit) as e:
    st.warning(f"Table Silver indisponible ({e}). Lancez `python -m partie2_velos.silver` puis rechargez la page.")
    st.stop()

villes = sorted(df["ville"].unique())
choix = st.sidebar.multiselect("Villes", villes, default=villes)
df = df[df["ville"].isin(choix)]
if df.empty:
    st.info("Choisissez au moins une ville.")
    st.stop()

debut, fin = df["timestamp"].min().tz_convert("Europe/Paris"), df["timestamp"].max().tz_convert("Europe/Paris")
c1, c2, c3, c4 = st.columns(4)
c1.metric("Stations", f"{df['station_id'].nunique():,}")
c2.metric("Relevés", f"{df['timestamp'].nunique():,}")
c3.metric("Occupation moyenne", f"{df['taux'].mean():.0%}")
c4.metric("Période", f"{debut:%d/%m %H:%M} -> {fin:%H:%M}")
st.caption("Marseille est exclue : son réseau (LeVélo) annonce 0 vélo dans toutes ses stations, donc aucune disponibilité réelle. "
           "Les données commencent au lancement du collecteur : l'API ne donne pas d'historique.")

# --- carte : remplissage au dernier relevé ---
st.subheader("Remplissage des stations (dernier relevé)")
derniere = df.sort_values("timestamp").groupby(["reseau", "station_id"]).tail(1)
une_ville = len(choix) == 1
carte = px.scatter_map(
    derniere, lat="latitude", lon="longitude", color="taux", range_color=(0, 1),
    color_continuous_scale="RdYlGn", hover_name="station_name",
    hover_data={"ville": True, "free_bikes": True, "empty_slots": True, "taux": ":.0%", "latitude": False, "longitude": False},
    zoom=11 if une_ville else 5, height=560, map_style="carto-positron",
    labels={"taux": "Remplissage", "free_bikes": "Vélos", "empty_slots": "Places libres"},
)
st.plotly_chart(carte, width="stretch")
st.caption("Vert : beaucoup de vélos. Rouge : station presque vide.")

# --- courbe horaire par ville (Gold) ---
gold = charger("velos")
if gold is not None:
    st.subheader("Occupation par ville au fil des heures (Gold)")
    g = gold[gold["ville"].isin(choix)]
    st.plotly_chart(px.line(g, x="heure_locale", y="taux_occupation", color="ville", markers=True,
                            labels={"heure_locale": "Heure (Paris)", "taux_occupation": "Taux d'occupation"}),
                    width="stretch")

# --- Q1 / Q2 ---
gauche, droite = st.columns(2)
with gauche:
    st.subheader("Stations les plus utilisées")
    st.caption("Mouvements = vélos pris + déposés par heure. Rotation = mouvements par heure et par place.")
    st.dataframe(analyse.stations_plus_utilisees(df, 15)[["ville", "station_name", "mouvements_par_heure", "rotation", "taux_moyen"]],
                 hide_index=True, width="stretch")
with droite:
    st.subheader("Zones à l'offre insuffisante")
    st.caption("Carrés d'environ 1 km où les stations sont le plus souvent vides.")
    zones = analyse.zones_offre_insuffisante(df)
    st.dataframe(zones.rename(columns={"lat": "latitude", "lon": "longitude"}), hide_index=True, width="stretch")

# --- Q3 ---
st.subheader("Pics d'utilisation dans la journée")
pics = analyse.pics_journaliers(df)
st.plotly_chart(px.line(pics, x="heure_paris", y="mouvements_par_station_heure", color="ville", markers=True,
                        labels={"heure_paris": "Heure (Paris)", "mouvements_par_station_heure": "Mouvements par station et par heure"}),
                width="stretch")
st.caption(f"{pics['heure_paris'].nunique()} heure(s) couverte(s) par la collecte pour l'instant.")
st.dataframe(analyse.heures_de_pointe(pics), hide_index=True, width="stretch")

# --- Q4 ---
st.subheader("Déséquilibres géographiques")
st.caption("Remplissage selon la distance au centre-ville.")
deseq = analyse.desequilibres_geographiques(df)
st.plotly_chart(px.bar(deseq, x="ville", y="taux_moyen", color="zone", barmode="group",
                       labels={"taux_moyen": "Remplissage moyen", "zone": "Distance au centre"}),
                width="stretch")

# --- Q5 ---
st.subheader("Stations critiques à rééquilibrer")
seuil = st.slider("Une station est critique si elle est vide ou pleine plus de ... du temps", 0.1, 0.9, analyse.SEUIL_CRITIQUE, 0.05)
critiques = analyse.stations_critiques(df, seuil=seuil)
st.write(f"**{len(critiques)}** stations critiques sur {df['station_id'].nunique():,}.")
st.dataframe(critiques[["ville", "station_name", "probleme", "part_vide", "part_pleine", "capacite", "releves"]].head(200),
             hide_index=True, width="stretch")

# --- IA ---
st.subheader("IA : profils de remplissage (K-means)")
k = st.slider("Nombre de groupes", 2, 8, 4)
try:
    stations, centres = analyse.profils_kmeans(df, k=k)
except ValueError as e:
    st.info(f"Pas encore assez de données : {e} Relancez Silver et Gold quand la collecte couvre plusieurs heures.")
else:
    profil = centres.drop(columns="stations").reset_index().melt(id_vars="cluster", var_name="heure_paris", value_name="remplissage")
    profil["cluster"] = profil["cluster"].astype(str)
    st.plotly_chart(px.line(profil, x="heure_paris", y="remplissage", color="cluster", markers=True,
                            labels={"heure_paris": "Heure (Paris)", "remplissage": "Remplissage moyen"}),
                    width="stretch")
    st.write("Stations par groupe :", centres["stations"].to_dict())
    pos = stations.merge(derniere[["reseau", "station_id", "latitude", "longitude"]], on=["reseau", "station_id"])
    pos["cluster"] = pos["cluster"].astype(str)
    st.plotly_chart(px.scatter_map(pos, lat="latitude", lon="longitude", color="cluster", hover_name="station_name",
                                   zoom=11 if une_ville else 5, height=500, map_style="carto-positron"),
                    width="stretch")
