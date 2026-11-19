"""Paramètres de la partie météo, regroupés au même endroit."""

from datetime import datetime, timezone

# --- Sources NOAA -----------------------------------------------------------

# Liste officielle de toutes les stations météo du monde (une ligne par station).
URL_STATIONS = "https://www.ncei.noaa.gov/pub/data/noaa/isd-history.csv"

# Fichiers horaires : un fichier CSV par station et par année.
# L'ancienne adresse du sujet (ncei.noaa.gov/data/global-hourly/access/)
# redirige désormais vers ce bucket public AWS.
URL_FICHIER_HORAIRE = "https://noaa-global-hourly-pds.s3.amazonaws.com/{annee}/{station_id}.csv"

# Code pays de la France métropolitaine dans la liste NOAA.
CODE_PAYS = "FR"

# --- Période : les 5 dernières années (année en cours incluse) --------------

ANNEE_COURANTE = datetime.now(timezone.utc).year
ANNEES = list(range(ANNEE_COURANTE - 4, ANNEE_COURANTE + 1))

# --- Téléchargement parallèle -----------------------------------------------

NB_THREADS = 16          # téléchargements simultanés
TIMEOUT_SECONDES = 120   # délai maximal pour un fichier
NB_ESSAIS = 3            # nouvelles tentatives en cas d'erreur réseau

# --- Data Lake MinIO (voir CONTRAT.md) --------------------------------------

BUCKET_BRONZE = "bronze"
BUCKET_SILVER = "silver"
BUCKET_GOLD = "gold"
SOURCE = "meteo"

# Table des stations françaises, produite par stations.py.
CLE_STATIONS = f"{SOURCE}/stations/stations.parquet"


def partition_bronze(moment: datetime | None = None) -> str:
    """Dossier Bronze du jour de téléchargement, au format du contrat :
    meteo/year=AAAA/month=MM/day=JJ

    On partitionne Bronze par date de TÉLÉCHARGEMENT (et non par date des
    mesures) : un nouveau téléchargement va dans un nouveau dossier, donc
    Bronze n'est jamais modifié.
    """
    m = moment or datetime.now(timezone.utc)
    return f"{SOURCE}/year={m:%Y}/month={m:%m}/day={m:%d}"
