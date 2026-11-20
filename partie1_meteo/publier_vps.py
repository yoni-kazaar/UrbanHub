"""Publication de gold/meteo/ sur le MinIO du VPS (après l'étape 5).

Le pipeline météo (étapes 1 à 5) tourne sur le MinIO local : 3,3 Go de Bronze
n'ont pas à transiter par le VPS. Seul le Gold, quelques Mo, est copié ensuite
sur le MinIO du VPS, lu par l'application et par l'analyse croisée.

Variables lues dans .env :
- MINIO_ENDPOINT, MINIO_ACCESS_KEY, MINIO_SECRET_KEY : MinIO local (source) ;
- VPS_MINIO_ENDPOINT, VPS_MINIO_ACCESS_KEY, VPS_MINIO_SECRET_KEY : MinIO du VPS
  (compte urbanhub-meteo, qui peut écrire dans gold/meteo/).

_SUCCESS est copié en dernier : tant que la copie n'est pas finie, l'ancien
_SUCCESS reste en place et la table publiée reste cohérente (versioning activé
sur le bucket gold). À la fin, les tailles des deux côtés sont comparées.

Lancement, depuis la racine du dépôt (après analyses.py) :
    python -m partie1_meteo.publier_vps            # liste les deux côtés puis copie
    python -m partie1_meteo.publier_vps --lister   # liste seulement
"""

from __future__ import annotations

import os
import sys

import boto3
from botocore.config import Config
from dotenv import find_dotenv, load_dotenv

from partie1_meteo import config

load_dotenv(find_dotenv(usecwd=True))
PREFIXE = f"{config.SOURCE}/"


def client(prefixe_env: str = ""):
    """Client S3 : MinIO local (prefixe_env vide) ou MinIO du VPS ("VPS_")."""
    return boto3.client(
        "s3",
        endpoint_url=os.environ[f"{prefixe_env}MINIO_ENDPOINT"],
        aws_access_key_id=os.environ[f"{prefixe_env}MINIO_ACCESS_KEY"],
        aws_secret_access_key=os.environ[f"{prefixe_env}MINIO_SECRET_KEY"],
        config=Config(signature_version="s3v4", retries={"max_attempts": 5, "mode": "standard"}),
        region_name="us-east-1",
    )


def objets(s3) -> dict[str, dict]:
    """Objets de gold/meteo/, par clé."""
    res = {}
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=config.BUCKET_GOLD, Prefix=PREFIXE):
        for o in page.get("Contents", []):
            res[o["Key"]] = o
    return res


def afficher(nom: str, objs: dict[str, dict]) -> None:
    print(f"{nom} : {len(objs)} fichiers")
    for cle, o in sorted(objs.items()):
        print(f"  {cle:<50} {o['Size'] / 1e6:7.2f} Mo  {o['LastModified']:%d/%m/%Y %H:%M}")


def main() -> None:
    local, vps = client(), client("VPS_")
    source = objets(local)
    if not source:
        sys.exit("gold/meteo/ est vide sur le MinIO local : lancer d'abord gold.py et analyses.py")
    afficher("MinIO local", source)
    afficher("MinIO du VPS", objets(vps))
    if "--lister" in sys.argv:
        return

    cles = sorted(c for c in source if not c.endswith("_SUCCESS"))
    cles += [c for c in source if c.endswith("_SUCCESS")]
    print("\nCopie vers le VPS...")
    for cle in cles:
        corps = local.get_object(Bucket=config.BUCKET_GOLD, Key=cle)["Body"].read()
        vps.put_object(Bucket=config.BUCKET_GOLD, Key=cle, Body=corps)
        print(f"  {cle} ({len(corps) / 1e6:.2f} Mo)")

    copie = objets(vps)
    ecarts = [c for c in source if c not in copie or copie[c]["Size"] != source[c]["Size"]]
    if ecarts:
        sys.exit(f"Écarts après la copie : {ecarts}")
    print(f"\n{len(source)} fichiers publiés sur le VPS, tailles identiques.")


if __name__ == "__main__":
    main()
