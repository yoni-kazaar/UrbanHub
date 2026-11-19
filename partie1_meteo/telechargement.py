"""Étape 2 – Téléchargement PARALLÈLE des fichiers horaires NOAA.

Pour chaque couple (station française, année), le fichier CSV est téléchargé,
compressé en gzip et déposé tel quel dans Bronze :

    bronze/meteo/year=AAAA/month=MM/day=JJ/<station_id>_<année>.csv.gz
    (date du dossier = date du téléchargement)

Les téléchargements sont lancés en parallèle avec
concurrent.futures.ThreadPoolExecutor : jamais de boucle fichier par fichier.

Lancement, depuis la racine du dépôt (après stations.py) :
    python -m partie1_meteo.telechargement                       # tout
    python -m partie1_meteo.telechargement --limite 3 --annees 2024   # test rapide
    python -m partie1_meteo.telechargement --villes-seulement    # 8 villes seulement

Les années passées déjà présentes dans Bronze ne sont pas retéléchargées.
L'année en cours l'est à chaque lancement, car NOAA la complète chaque jour.
"""

from __future__ import annotations

import argparse
import gzip
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from partie1_meteo import config
from partie1_meteo.provisoire import client_minio, ecrire_octets, lire_parquet, lister_cles

MOTIF_FICHIER = re.compile(r"(\d{11})_(\d{4})\.csv\.gz$")


@dataclass
class Resultat:
    station_id: str
    annee: int
    statut: str              # "ok", "absent" (pas de données NOAA) ou "erreur"
    octets_bruts: int = 0
    octets_compresses: int = 0
    cle: str = ""
    message: str = ""


# --- Une session HTTP par thread (requests.Session n'est pas partageable) ---

_local = threading.local()


def session_http() -> requests.Session:
    if not hasattr(_local, "session"):
        s = requests.Session()
        relance = Retry(
            total=config.NB_ESSAIS,
            backoff_factor=2,  # attend 2 s, 4 s, 8 s entre les essais
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
        )
        s.mount("https://", HTTPAdapter(max_retries=relance))
        _local.session = s
    return _local.session


# --- Le travail d'un thread : un fichier --------------------------------------

def telecharger_un_fichier(s3, station_id: str, annee: int, partition: str) -> Resultat:
    url = config.URL_FICHIER_HORAIRE.format(annee=annee, station_id=station_id)
    try:
        reponse = session_http().get(url, timeout=config.TIMEOUT_SECONDES)
        # Le bucket NOAA répond 403 ou 404 quand le fichier n'existe pas :
        # la station n'a simplement pas de données cette année-là.
        if reponse.status_code in (403, 404):
            return Resultat(station_id, annee, "absent")
        reponse.raise_for_status()

        brut = reponse.content
        compresse = gzip.compress(brut)
        cle = f"{partition}/{station_id}_{annee}.csv.gz"
        ecrire_octets(s3, config.BUCKET_BRONZE, cle, compresse, "application/gzip")
        return Resultat(station_id, annee, "ok", len(brut), len(compresse), cle)

    except Exception as erreur:  # une erreur ne doit pas arrêter les autres
        return Resultat(station_id, annee, "erreur", message=str(erreur)[:300])


# --- Préparation de la liste des fichiers à télécharger ----------------------

def deja_presents(s3) -> set[tuple[str, int]]:
    """Couples (station, année) déjà déposés dans Bronze, toutes dates confondues."""
    presents = set()
    for cle in lister_cles(s3, config.BUCKET_BRONZE, f"{config.SOURCE}/"):
        m = MOTIF_FICHIER.search(cle)
        if m:
            presents.add((m.group(1), int(m.group(2))))
    return presents


def taches_a_faire(s3, annees: list[int], limite: int | None, villes_seulement: bool, forcer: bool):
    stations = lire_parquet(s3, config.BUCKET_SILVER, config.CLE_STATIONS)
    if villes_seulement:
        stations = stations[stations["ville"].notna()]
    if limite:
        stations = stations.head(limite)

    presents = set() if forcer else deja_presents(s3)
    taches, ignores = [], 0

    for station in stations.itertuples():
        for annee in annees:
            # Inutile de demander une année où la station ne fonctionnait pas.
            if station.debut.year > annee or station.fin.year < annee:
                continue
            # Années passées déjà téléchargées : on ne les refait pas.
            if annee < config.ANNEE_COURANTE and (station.station_id, annee) in presents:
                ignores += 1
                continue
            taches.append((station.station_id, annee))

    return taches, ignores, len(stations)


# --- Programme principal -------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Téléchargement parallèle des fichiers NOAA")
    parser.add_argument("--annees", type=int, nargs="+", default=config.ANNEES)
    parser.add_argument("--limite", type=int, help="nombre maximal de stations (pour tester)")
    parser.add_argument("--villes-seulement", action="store_true", help="seulement les stations des 8 villes")
    parser.add_argument("--forcer", action="store_true", help="retélécharger même ce qui est déjà dans Bronze")
    parser.add_argument("--threads", type=int, default=config.NB_THREADS)
    args = parser.parse_args()

    s3 = client_minio()
    maintenant = datetime.now(timezone.utc)
    partition = config.partition_bronze(maintenant)

    taches, ignores, nb_stations = taches_a_faire(
        s3, args.annees, args.limite, args.villes_seulement, args.forcer
    )
    print(f"{nb_stations} stations, années {args.annees}")
    print(f"{len(taches)} fichiers à télécharger, {ignores} déjà présents dans Bronze")
    print(f"{args.threads} téléchargements en parallèle → {config.BUCKET_BRONZE}/{partition}/\n")

    debut = time.time()
    resultats: list[Resultat] = []

    with ThreadPoolExecutor(max_workers=args.threads) as pool:
        futurs = [pool.submit(telecharger_un_fichier, s3, sid, an, partition) for sid, an in taches]
        for i, futur in enumerate(as_completed(futurs), start=1):
            r = futur.result()
            resultats.append(r)
            if r.statut == "erreur":
                print(f"  ERREUR {r.station_id}_{r.annee} : {r.message}")
            if i % 25 == 0 or i == len(futurs):
                go = sum(x.octets_bruts for x in resultats) / 1e9
                print(f"  {i}/{len(futurs)} fichiers traités ({go:.2f} Go bruts)")

    duree = time.time() - debut

    # --- Bilan ---
    ok = [r for r in resultats if r.statut == "ok"]
    absents = [r for r in resultats if r.statut == "absent"]
    erreurs = [r for r in resultats if r.statut == "erreur"]
    bruts = sum(r.octets_bruts for r in ok)
    compresses = sum(r.octets_compresses for r in ok)

    print(f"\nTerminé en {duree / 60:.1f} min")
    print(f"  {len(ok)} fichiers déposés, {len(absents)} absents chez NOAA, {len(erreurs)} en erreur")
    if ok:
        print(f"  {bruts / 1e9:.2f} Go bruts → {compresses / 1e9:.2f} Go compressés dans Bronze")
    if erreurs:
        print("  Relancer la même commande pour reprendre les fichiers en erreur.")

    # Manifeste : trace de ce téléchargement, déposé à côté des fichiers.
    manifeste = {
        "date_telechargement": maintenant.isoformat(),
        "duree_secondes": round(duree),
        "annees": args.annees,
        "nb_stations": nb_stations,
        "nb_ok": len(ok),
        "nb_absents": len(absents),
        "nb_erreurs": len(erreurs),
        "octets_bruts": bruts,
        "octets_compresses": compresses,
        "fichiers": [asdict(r) for r in resultats],
    }
    cle_manifeste = f"{partition}/_manifeste_{maintenant:%Y%m%dT%H%M%SZ}.json"
    ecrire_octets(
        s3, config.BUCKET_BRONZE, cle_manifeste,
        json.dumps(manifeste, ensure_ascii=False, indent=2).encode("utf-8"),
        "application/json",
    )
    print(f"  Manifeste : {config.BUCKET_BRONZE}/{cle_manifeste}")


if __name__ == "__main__":
    main()
