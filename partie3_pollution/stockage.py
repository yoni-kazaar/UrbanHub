"""
Lecture / écriture dans le Data Lake, avec deux modes :

- MINIO_ENDPOINT renseigné -> MinIO (local pour développer, puis le VPS de D) ;
- MINIO_ENDPOINT vide      -> un dossier local partie3_pollution/data_lake/<bucket>/<chemin>.

En écriture, si MinIO est injoignable, le fichier part dans le dossier local : aucune collecte n'est perdue.
Chemins du contrat : <bucket>/<source>/year=AAAA/month=MM/day=JJ/<fichier>
"""

import io
import json
from pathlib import Path

from . import config


def chemin_partitionne(nom_fichier, dt, source=config.SOURCE):
    return f"{source}/year={dt:%Y}/month={dt:%m}/day={dt:%d}/{nom_fichier}"


class Lac:
    def __init__(self, forcer_local=False):
        self.client = None
        self._buckets_ok = set()
        if config.MINIO_ENDPOINT and not forcer_local:
            from minio import Minio
            endpoint = config.MINIO_ENDPOINT.replace("https://", "").replace("http://", "").rstrip("/")
            secure = config.MINIO_SECURE or config.MINIO_ENDPOINT.startswith("https://")
            self.client = Minio(endpoint, access_key=config.MINIO_ACCESS_KEY,
                                secret_key=config.MINIO_SECRET_KEY, secure=secure)

    def mode(self):
        return f"MinIO ({config.MINIO_ENDPOINT})" if self.client else f"dossier local ({config.DOSSIER_LAC_LOCAL})"

    # ------------------------------------------------------------------ écriture
    def _creer_bucket_si_absent(self, bucket):
        """Utile sur un MinIO local tout neuf. Sur le VPS, c'est D qui crée les buckets."""
        if bucket in self._buckets_ok:
            return
        try:
            if not self.client.bucket_exists(bucket):
                self.client.make_bucket(bucket)
        except Exception:
            pass   # pas le droit de vérifier/créer : on tente quand même l'écriture
        self._buckets_ok.add(bucket)

    def _ecrire_local(self, bucket, chemin, data):
        f = Path(config.DOSSIER_LAC_LOCAL) / bucket / chemin
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(data)
        return f"local:{f}"

    def ecrire(self, bucket, chemin, data, content_type="application/octet-stream"):
        """Écrit des octets ; renvoie où le fichier a été écrit."""
        if self.client:
            try:
                self._creer_bucket_si_absent(bucket)
                self.client.put_object(bucket, chemin, io.BytesIO(data), length=len(data),
                                       content_type=content_type)
                return f"s3://{bucket}/{chemin}"
            except Exception as e:  # MinIO arrêté, réseau coupé, droits...
                if not config.SECOURS_LOCAL:
                    raise
                print(f"  [MinIO indisponible : {e}] -> écriture de secours en local", flush=True)
        return self._ecrire_local(bucket, chemin, data)

    def ecrire_json(self, bucket, chemin, objet):
        data = json.dumps(objet, ensure_ascii=False).encode("utf-8")
        return self.ecrire(bucket, chemin, data, content_type="application/json")

    # ------------------------------------------------------------------ lecture
    def lister(self, bucket, prefixe):
        """Liste les chemins des fichiers sous bucket/prefixe (triés)."""
        if self.client:
            return sorted(o.object_name for o in self.client.list_objects(bucket, prefix=prefixe, recursive=True))
        base = Path(config.DOSSIER_LAC_LOCAL) / bucket
        if not base.exists():
            return []
        return sorted(p.relative_to(base).as_posix() for p in (base / prefixe).rglob("*") if p.is_file())

    def lire(self, bucket, chemin):
        if self.client:
            r = self.client.get_object(bucket, chemin)
            try:
                return r.read()
            finally:
                r.close()
                r.release_conn()
        return (Path(config.DOSSIER_LAC_LOCAL) / bucket / chemin).read_bytes()

    def lire_json(self, bucket, chemin):
        return json.loads(self.lire(bucket, chemin))