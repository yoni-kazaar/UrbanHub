"""
Traitement complet : synchro -> Silver -> Gold.

Deux façons de le lancer :
  python -m partie3_pollution.pipeline            -> une seule fois (mode strict : s'arrête à la 1re erreur)
  python -m partie3_pollution.pipeline --boucle   -> en continu, toutes les PIPELINE_INTERVALLE_MINUTES
                                                     (utilisé par le conteneur pipeline-pollution)

En mode boucle, si un passage échoue, on ne publie pas de Gold pour ce passage,
on affiche l'erreur et on réessaie au passage suivant.
"""

import argparse
import os
import sys
import time
import traceback
from datetime import datetime, timezone

from . import config, gold, silver, synchro

INTERVALLE_MINUTES = int(os.environ.get("PIPELINE_INTERVALLE_MINUTES", "60"))


class EtapeEchouee(Exception):
    pass


def etape(nom, fonction):
    print(f"\n========== {nom} ==========", flush=True)
    debut = time.time()
    try:
        fonction()
    except BaseException as e:      # attrape aussi les SystemExit
        traceback.print_exc()
        raise EtapeEchouee(nom) from e
    print(f"-> {nom} OK ({time.time() - debut:.0f} s)", flush=True)


def un_passage():
    """Lance les 3 étapes dans l'ordre. Renvoie True si tout est OK."""
    print(f"\n##### Pipeline démarré à {datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S}Z #####", flush=True)
    try:
        if config.MINIO_ENDPOINT:
            etape("1/3 Synchro local -> MinIO", synchro.main)
        else:
            print("1/3 Synchro ignorée (pas de MinIO configuré)", flush=True)
        etape("2/3 Silver (nettoyage)", silver.main)
        etape("3/3 Gold (table du contrat)", gold.main)
    except EtapeEchouee as e:
        print(f"\nÉchec à l'étape '{e}' : Gold non publié pour ce passage.", flush=True)
        return False
    print("\nPipeline terminé : gold/pollution/pollution_ville_heure.parquet est à jour.", flush=True)
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--boucle", action="store_true", help="relancer en continu")
    args = parser.parse_args()

    if not args.boucle:
        sys.exit(0 if un_passage() else 1)

    print(f"Mode continu : un passage toutes les {INTERVALLE_MINUTES} min", flush=True)
    while True:
        debut = time.time()
        un_passage()
        attente = max(0, INTERVALLE_MINUTES * 60 - (time.time() - debut))
        print(f"Prochain passage dans {attente / 60:.0f} min", flush=True)
        time.sleep(attente)


if __name__ == "__main__":
    main()