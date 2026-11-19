"""Version provisoire de `common/` (villes et accès MinIO) pour la partie météo.

Écrit avant que `common/` soit disponible, pour ne pas bloquer la partie météo.
Les villes et la règle des 30 km sont les mêmes que dans `common/villes.py`.
L'accès MinIO passe ici par boto3 (et non s3fs comme `common/lake.py`).
Plus tard : remplacer les imports `from partie1_meteo.provisoire import ...`
par ceux de `common`, puis supprimer ce fichier.
"""

from __future__ import annotations

import io
import math
import os

import boto3
import pandas as pd
from botocore.config import Config
from dotenv import find_dotenv, load_dotenv

# --- Villes (futur common/villes.py) ---

# Centre de chaque ville (hôtel de ville), en degrés décimaux.
VILLES: dict[str, tuple[float, float]] = {
    "Paris": (48.8566, 2.3522),
    "Lyon": (45.7640, 4.8357),
    "Marseille": (43.2965, 5.3698),
    "Toulouse": (43.6047, 1.4442),
    "Lille": (50.6292, 3.0573),
    "Bordeaux": (44.8378, -0.5792),
    "Nantes": (47.2184, -1.5536),
    "Strasbourg": (48.5734, 7.7521),
}

RAYON_KM = 30  # règle du contrat


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distance à vol d'oiseau entre deux points (formule de haversine)."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def rattacher_ville(latitude: float, longitude: float) -> str | None:
    """Ville la plus proche à moins de 30 km, sinon None (règle du contrat)."""
    meilleure, meilleure_dist = None, RAYON_KM
    for ville, (lat, lon) in VILLES.items():
        d = distance_km(latitude, longitude, lat, lon)
        if d <= meilleure_dist:
            meilleure, meilleure_dist = ville, d
    return meilleure


# --- Accès MinIO (futur common/lake.py) ---

load_dotenv(find_dotenv(usecwd=True))


def client_minio():
    """Client S3 vers MinIO, configuré par le fichier .env."""
    return boto3.client(
        "s3",
        endpoint_url=os.environ["MINIO_ENDPOINT"],
        aws_access_key_id=os.environ["MINIO_ACCESS_KEY"],
        aws_secret_access_key=os.environ["MINIO_SECRET_KEY"],
        config=Config(
            signature_version="s3v4",
            retries={"max_attempts": 5, "mode": "standard"},
            max_pool_connections=50,  # assez pour les téléchargements parallèles
        ),
        region_name="us-east-1",
    )


def ecrire_octets(s3, bucket: str, cle: str, donnees: bytes, content_type: str = "application/octet-stream") -> None:
    s3.put_object(Bucket=bucket, Key=cle, Body=donnees, ContentType=content_type)


def lire_octets(s3, bucket: str, cle: str) -> bytes:
    return s3.get_object(Bucket=bucket, Key=cle)["Body"].read()


def ecrire_parquet(s3, df: pd.DataFrame, bucket: str, cle: str) -> None:
    tampon = io.BytesIO()
    df.to_parquet(tampon, index=False, compression="zstd")
    ecrire_octets(s3, bucket, cle, tampon.getvalue())


def lire_parquet(s3, bucket: str, cle: str) -> pd.DataFrame:
    return pd.read_parquet(io.BytesIO(lire_octets(s3, bucket, cle)))


def lister_cles(s3, bucket: str, prefixe: str) -> list[str]:
    """Toutes les clés d'un bucket qui commencent par `prefixe`."""
    cles: list[str] = []
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefixe):
        cles.extend(obj["Key"] for obj in page.get("Contents", []))
    return cles
