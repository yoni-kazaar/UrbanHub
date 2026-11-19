"""Configuration de la Partie 3, lue dans le fichier .env (jamais commité)."""

import os
from pathlib import Path

from dotenv import load_dotenv

RACINE = Path(__file__).resolve().parent.parent      # dossier UrbanHub/
load_dotenv(RACINE / ".env")

# --- OpenAQ ---
OPENAQ_API_KEY = os.environ.get("OPENAQ_API_KEY", "")
OPENAQ_BASE_URL = "https://api.openaq.org/v3"

# --- MinIO (vide = mode "dossier local", pratique pour démarrer sans MinIO) ---
MINIO_ENDPOINT = os.environ.get("MINIO_ENDPOINT", "")
MINIO_ACCESS_KEY = os.environ.get("MINIO_ACCESS_KEY", "")
MINIO_SECRET_KEY = os.environ.get("MINIO_SECRET_KEY", "")
MINIO_SECURE = os.environ.get("MINIO_SECURE", "false").lower() == "true"

# --- Collecte ---
SOURCE = "pollution"                                   # nom de la source dans le Data Lake
POLLUANTS = {"pm25", "pm10", "no2", "o3", "co"}        # polluants suivis (Personne.md)
INTERVALLE_MINUTES = int(os.environ.get("INTERVALLE_MINUTES", "15"))
REFRESH_CAPTEURS_HEURES = 24                           # on relance la découverte une fois par jour
CAPTEUR_ACTIF_JOURS = 7                                # capteur ignoré s'il n'a rien envoyé depuis 7 jours

# Dossiers locaux (montés en volume dans Docker)
DOSSIER_ETAT = RACINE / "partie3_pollution" / "etat"   # catalogue des capteurs
DOSSIER_LAC_LOCAL = RACINE / "partie3_pollution" / "data_lake"  # Data Lake en mode local / secours
