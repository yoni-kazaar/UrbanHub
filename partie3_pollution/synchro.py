"""
Recopie le Data Lake local (partie3_pollution/data_lake) vers MinIO.

À lancer quand MINIO_ENDPOINT pointe vers un MinIO : tout ce qui a été collecté
en local (ou écrit en secours pendant une panne) y est envoyé.
Les fichiers déjà présents sur MinIO ne sont pas renvoyés.

Lancement : python -m partie3_pollution.synchro
"""

from pathlib import Path

from . import config
from .stockage import Lac


def main():
    distant = Lac()
    if not distant.client:
        raise SystemExit("MINIO_ENDPOINT est vide : rien à synchroniser.")
    base = Path(config.DOSSIER_LAC_LOCAL)
    fichiers = [p for p in base.rglob("*") if p.is_file()]
    deja, envoyes = 0, 0
    for p in fichiers:
        bucket, chemin = p.relative_to(base).parts[0], "/".join(p.relative_to(base).parts[1:])
        try:
            distant.client.stat_object(bucket, chemin)
            deja += 1
            continue
        except Exception:
            pass
        ct = "application/json" if p.suffix == ".json" else "application/octet-stream"
        distant.ecrire(bucket, chemin, p.read_bytes(), content_type=ct)
        envoyes += 1
    print(f"{len(fichiers)} fichiers locaux : {envoyes} envoyés, {deja} déjà présents sur MinIO", flush=True)


if __name__ == "__main__":
    main()