"""Collecteur CityBikes : un relevé JSON brut par réseau toutes les 2 min 30, dans bronze/velos/.

    python -m partie2_velos.collecte               # en boucle (prod)
    python -m partie2_velos.collecte --une-fois    # un seul passage (test)
"""
import argparse
import json
import logging
import time
import urllib.request
from datetime import datetime, timezone

from common import lake

API = "https://api.citybik.es/v2/networks"
INTERVALLE_S = 150 # 2 min 30

# ville du contrat -> identifiant du réseau CityBikes
RESEAUX = {
    "Paris": "velib",
    "Lyon": "velov",
    "Marseille": "le-velo",
    "Toulouse": "velo",
    "Lille": "vlille",
    "Bordeaux": "v3-bordeaux",
    "Nantes": "bicloo",
    "Strasbourg": "velhop",
}

log = logging.getLogger("velos.collecte")


def telecharger(reseau):
    """JSON brut d'un réseau (3 essais)."""
    for essai in range(3):
        try:
            with urllib.request.urlopen(f"{API}/{reseau}", timeout=30) as r:
                return r.read()
        except Exception:
            if essai == 2:
                raise
            time.sleep(2 ** essai)


def releve(reseau):
    """Télécharge un réseau et dépose le JSON tel quel dans bronze (un fichier par relevé)."""
    maintenant = datetime.now(timezone.utc)
    contenu = telecharger(reseau)
    cle = f"{lake.partition('velos', maintenant)}/velos_{maintenant:%Y%m%dT%H%M%SZ}_{reseau}.json"
    lake.ecrire_objet("bronze", cle, contenu)
    return cle, len(json.loads(contenu)["network"]["stations"])


def passage():
    """Un passage sur les 8 réseaux. Une erreur sur un réseau n'arrête pas les autres."""
    reussis = 0
    for ville, reseau in RESEAUX.items():
        try:
            cle, nb = releve(reseau)
            log.info("%s : %d stations -> bronze/%s", ville, nb, cle)
            reussis += 1
        except Exception as e:
            log.warning("%s (%s) : échec : %s", ville, reseau, e)
    return reussis


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--une-fois", action="store_true", help="un seul passage puis arrêt")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    while True:
        debut = time.time()
        reussis = passage()
        log.info("passage terminé : %d/%d réseaux", reussis, len(RESEAUX))
        if args.une_fois:
            raise SystemExit(0 if reussis == len(RESEAUX) else 1)
        time.sleep(max(0, INTERVALLE_S - (time.time() - debut)))


if __name__ == "__main__":
    main()
