"""Lecture et écriture dans le Data Lake MinIO.

Variables lues dans .env : MINIO_ENDPOINT, MINIO_ACCESS_KEY, MINIO_SECRET_KEY.
Avec URBANHUB_FAKE=1, lire_gold lit les fausses tables locales (data/fake_gold/) au lieu de MinIO.
"""
import io
import os
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import s3fs
from dotenv import load_dotenv

from common.schemas import chemin_gold, valider

load_dotenv()
FAKE_DIR = Path(__file__).resolve().parents[1] / "data" / "fake_gold"


def fs():
    return s3fs.S3FileSystem(
        key=os.environ["MINIO_ACCESS_KEY"],
        secret=os.environ["MINIO_SECRET_KEY"],
        client_kwargs={"endpoint_url": os.environ.get("MINIO_ENDPOINT", "http://localhost:9000")},
    )


def partition(source, moment=None):
    """Dossier du jour au format du contrat : <source>/year=AAAA/month=MM/day=JJ"""
    m = moment or datetime.now(timezone.utc)
    return f"{source}/year={m:%Y}/month={m:%m}/day={m:%d}"


def ecrire_objet(bucket, cle, contenu: bytes):
    """Dépose un fichier brut (JSON, CSV), par exemple dans bronze."""
    with fs().open(f"{bucket}/{cle}", "wb") as f:
        f.write(contenu)


def lire_parquet(bucket, cle):
    with fs().open(f"{bucket}/{cle}", "rb") as f:
        return pd.read_parquet(io.BytesIO(f.read()))


def ecrire_parquet(df, bucket, cle):
    with fs().open(f"{bucket}/{cle}", "wb") as f:
        df.to_parquet(f, index=False)


def publier_gold(df, source):
    """Valide la table au format du contrat, l'écrit dans gold/ puis dépose _SUCCESS."""
    valider(df, source)
    ecrire_parquet(df, "gold", chemin_gold(source))
    ecrire_objet("gold", f"{source}/_SUCCESS", b"")


def gold_pret(source):
    return fs().exists(f"gold/{source}/_SUCCESS")


def lire_gold(source):
    """Table Gold d'une source (meteo, velos ou pollution), ou None si elle n'est pas encore publiée."""
    if os.environ.get("URBANHUB_FAKE") == "1":
        chemin = FAKE_DIR / chemin_gold(source)
        return pd.read_parquet(chemin) if chemin.exists() else None
    if not gold_pret(source):
        return None
    return lire_parquet("gold", chemin_gold(source))
