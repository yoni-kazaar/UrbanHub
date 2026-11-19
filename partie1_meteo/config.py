"""Paramètres de la partie météo, regroupés au même endroit."""

from datetime import datetime, timezone

# --- Source : Météo-France, données climatologiques de base horaires ---------
#
# Jeu de données ouvert (Licence Ouverte) publié sur data.gouv.fr :
#   https://www.data.gouv.fr/fr/datasets/donnees-climatologiques-de-base-horaires/
# Un fichier CSV compressé par département et par période :
#   H_<dép>_previous-2020-2024.csv.gz  (2020 à 2024)
#   H_<dép>_latest-2025-2026.csv.gz    (2025 à aujourd'hui, mis à jour chaque jour)
#
# Remplace NOAA Global Hourly (ISD), arrêté le 24/08/2025 : choix validé
# par le professeur pour couvrir 2026 et la période de collecte des Parties 2 et 3.

URL_CATALOGUE = "https://www.data.gouv.fr/api/1/datasets/donnees-climatologiques-de-base-horaires/"

# Périodes de fichiers à télécharger (les 5 dernières années sont dedans).
PERIODES = ["previous", "latest"]

# --- Période étudiée : les 5 dernières années (année en cours incluse) -------

ANNEE_COURANTE = datetime.now(timezone.utc).year
ANNEES = list(range(ANNEE_COURANTE - 4, ANNEE_COURANTE + 1))

# --- Téléchargement parallèle -----------------------------------------------

NB_THREADS = 8           # téléchargements simultanés
TIMEOUT_SECONDES = 300   # délai maximal pour un fichier
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
