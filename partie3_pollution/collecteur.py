"""
Étape 2 : collecteur régulier (flux IoT simulé).

Toutes les INTERVALLE_MINUTES (15 par défaut) :
  - interroge /v3/locations/{id}/latest pour chaque site du catalogue ;
  - dépose un fichier brut horodaté dans
    bronze/pollution/year=AAAA/month=MM/day=JJ/pollution_AAAAMMJJTHHMMSSZ.json
  - Bronze n'est jamais modifié : chaque relevé est un nouveau fichier.
Le catalogue des capteurs est rafraîchi une fois par jour.

Lancement :
  python -m partie3_pollution.collecteur            # tourne en continu
  python -m partie3_pollution.collecteur --une-fois # un seul passage (test)
"""

import sys
import time
from datetime import datetime, timedelta, timezone

from . import config
from .decouverte_capteurs import charger_catalogue, decouvrir
from .openaq import OpenAQ
from .stockage import Lac, chemin_partitionne


def catalogue_a_jour(client, lac):
    cat = charger_catalogue()
    if cat:
        age = datetime.now(timezone.utc) - datetime.fromisoformat(cat["maj_utc"])
        if age < timedelta(hours=config.REFRESH_CAPTEURS_HEURES):
            return cat
    print("Mise à jour du catalogue des capteurs...", flush=True)
    return decouvrir(client, lac)


def un_passage(client, lac):
    cat = catalogue_a_jour(client, lac)
    sites = sorted({c["location_id"] for c in cat["capteurs"]})
    capteurs_suivis = {c["sensor_id"] for c in cat["capteurs"]}
    debut = datetime.now(timezone.utc)

    releves, erreurs = [], 0
    for loc_id in sites:
        try:
            data = client.get(f"/locations/{loc_id}/latest", {"limit": 1000})
            # On garde la réponse telle quelle, limitée aux capteurs des 5 polluants
            results = [r for r in data.get("results", []) if r.get("sensorsId") in capteurs_suivis]
            releves.append({"location_id": loc_id, "results": results})
        except Exception as e:
            erreurs += 1
            print(f"  site {loc_id} : {e}", flush=True)

    fichier = f"pollution_{debut:%Y%m%dT%H%M%SZ}.json"
    ou = lac.ecrire_json("bronze", chemin_partitionne(fichier, debut), {
        "collecte_utc": debut.isoformat(),
        "requete": "/v3/locations/{id}/latest",
        "catalogue_maj_utc": cat["maj_utc"],
        "nb_sites": len(sites),
        "nb_erreurs": erreurs,
        "releves": releves,
    })
    nb_mesures = sum(len(r["results"]) for r in releves)
    duree = (datetime.now(timezone.utc) - debut).total_seconds()
    print(f"[{debut:%Y-%m-%d %H:%M:%S}Z] {nb_mesures} mesures, {len(sites)} sites, "
          f"{erreurs} erreurs, {duree:.0f}s -> {ou}", flush=True)


def main():
    client, lac = OpenAQ(), Lac()
    print(f"Collecteur pollution démarré | stockage : {lac.mode()} | "
          f"intervalle : {config.INTERVALLE_MINUTES} min", flush=True)
    if "--une-fois" in sys.argv:
        un_passage(client, lac)
        return
    while True:
        t0 = time.monotonic()
        try:
            un_passage(client, lac)
        except Exception as e:      # le collecteur ne doit jamais s'arrêter sur une erreur
            print(f"Erreur pendant le passage : {e}", flush=True)
        reste = config.INTERVALLE_MINUTES * 60 - (time.monotonic() - t0)
        time.sleep(max(reste, 10))


if __name__ == "__main__":
    main()
