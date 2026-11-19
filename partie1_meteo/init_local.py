"""Étape 0 – Prépare le MinIO LOCAL (développement uniquement).

Vérifie la connexion et crée les buckets bronze, silver et gold s'ils manquent.
Sur le VPS, c'est D qui crée les buckets : ne pas lancer ce script dessus.

Lancement, depuis la racine du dépôt :
    python -m partie1_meteo.init_local
"""

import os

from partie1_meteo import config
from partie1_meteo.provisoire import client_minio, creer_buckets_local


def main() -> None:
    print(f"Connexion à {os.environ.get('MINIO_ENDPOINT')}")
    s3 = client_minio()
    creer_buckets_local(s3, [config.BUCKET_BRONZE, config.BUCKET_SILVER, config.BUCKET_GOLD])
    print("Buckets disponibles :", [b["Name"] for b in s3.list_buckets()["Buckets"]])


if __name__ == "__main__":
    main()
