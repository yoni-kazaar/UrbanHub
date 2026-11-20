"""Étape 1 : téléchargement en parallèle des données horaires Météo-France.

1. Récupère sur data.gouv.fr la liste des fichiers du jeu de données
   'Données climatologiques de base - horaires'.
2. Garde les départements de France métropolitaine (codes à 2 caractères)
   et les périodes 2020-2024 ('previous') et 2025-2026 ('latest').
3. Télécharge tous les fichiers en parallèle (concurrent.futures) et les
   dépose tels quels (déjà compressés en gzip) dans Bronze :

    bronze/meteo/year=AAAA/month=MM/day=JJ/H_<dép>_<période>.csv.gz
    (date du dossier = date du téléchargement)

Lancement, depuis la racine du dépôt :
    python -m partie1_meteo.telechargement                         # toute la France
    python -m partie1_meteo.telechargement --departements 69 75    # test rapide

Relancer est sans risque :
- un fichier 'previous' (2020-2024) déjà présent dans Bronze n'est jamais
  retéléchargé ;
- un fichier 'latest' (2025-2026) est retéléchargé une fois par jour, car
  Météo-France le complète chaque jour (nouveau dossier daté dans Bronze).
Une relance le même jour ne reprend donc que les fichiers en erreur.
"""

from __future__ import annotations

import argparse
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
from partie1_meteo.provisoire import client_minio, ecrire_octets, lister_cles

# Nom d'un fichier Météo-France : H_69_latest-2025-2026.csv.gz
MOTIF_FICHIER = re.compile(r"H_(?P<dep>[0-9AB]{2,3})_(?P<periode>previous|latest)-(?P<debut>\d{4})-(?P<fin>\d{4})\.csv\.gz$")


@dataclass
class Fichier:
    departement: str
    periode: str        # "previous" ou "latest"
    nom: str            # H_69_latest-2025-2026.csv.gz
    url: str
    taille_annoncee: int | None


@dataclass
class Resultat:
    nom: str
    statut: str         # "ok" ou "erreur"
    octets: int = 0
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


# --- Catalogue : la liste des fichiers à télécharger ---

def lire_catalogue() -> tuple[list[Fichier], bytes]:
    """Fichiers horaires de la métropole, d'après l'API de data.gouv.fr.
    Renvoie aussi la réponse brute de l'API, conservée dans Bronze."""
    reponse = session_http().get(config.URL_CATALOGUE, timeout=60)
    reponse.raise_for_status()

    fichiers = []
    for ressource in reponse.json()["resources"]:
        m = MOTIF_FICHIER.search(ressource["url"])
        if not m or m["periode"] not in config.PERIODES:
            continue
        if len(m["dep"]) != 2:  # 971, 972... = outre-mer : hors périmètre
            continue
        fichiers.append(
            Fichier(
                departement=m["dep"],
                periode=m["periode"],
                nom=m.group(0),
                url=ressource["url"],
                taille_annoncee=ressource.get("filesize"),
            )
        )
    return sorted(fichiers, key=lambda f: (f.departement, f.periode)), reponse.content


def deja_presents(s3, partition_du_jour: str) -> tuple[set[str], set[str]]:
    """Noms des fichiers déjà déposés dans Bronze :
    - depuis toujours (toutes dates confondues) ;
    - aujourd'hui (dans le dossier du jour)."""
    toujours, aujourdhui = set(), set()
    for cle in lister_cles(s3, config.BUCKET_BRONZE, f"{config.SOURCE}/"):
        if MOTIF_FICHIER.search(cle):
            nom = cle.rsplit("/", 1)[-1]
            toujours.add(nom)
            if cle.startswith(partition_du_jour + "/"):
                aujourdhui.add(nom)
    return toujours, aujourdhui


# --- Le travail d'un thread : un fichier ---

def telecharger_un_fichier(s3, fichier: Fichier, partition: str) -> Resultat:
    derniere_erreur = None
    # Retry de urllib3 ne couvre pas un serveur qui s'arrête de répondre en
    # plein téléchargement ('Read timed out') : on réessaie donc nous-mêmes.
    for essai in range(1, config.NB_ESSAIS + 1):
        try:
            reponse = session_http().get(fichier.url, timeout=(30, config.TIMEOUT_SECONDES))
            reponse.raise_for_status()
            contenu = reponse.content  # déjà compressé en gzip par Météo-France

            cle = f"{partition}/{fichier.nom}"
            ecrire_octets(s3, config.BUCKET_BRONZE, cle, contenu, "application/gzip")
            return Resultat(fichier.nom, "ok", len(contenu), cle)

        except Exception as erreur:  # une erreur ne doit pas arrêter les autres
            derniere_erreur = erreur
            time.sleep(5 * essai)

    return Resultat(fichier.nom, "erreur", message=str(derniere_erreur)[:300])


# --- Programme principal ---

def main() -> None:
    parser = argparse.ArgumentParser(description="Téléchargement parallèle des fichiers Météo-France")
    parser.add_argument("--departements", nargs="+", help="codes de départements (ex. 69 75), pour tester")
    parser.add_argument("--forcer", action="store_true", help="retélécharger même les fichiers 'previous' déjà présents")
    parser.add_argument("--threads", type=int, default=config.NB_THREADS)
    args = parser.parse_args()

    s3 = client_minio()
    maintenant = datetime.now(timezone.utc)
    partition = config.partition_bronze(maintenant)

    print(f"Lecture du catalogue : {config.URL_CATALOGUE}")
    fichiers, catalogue_brut = lire_catalogue()
    if args.departements:
        fichiers = [f for f in fichiers if f.departement in args.departements]

    # 'previous' (2020-2024) ne change plus : un seul téléchargement suffit.
    # 'latest' (2025-2026) change chaque jour : un téléchargement par jour.
    toujours, aujourdhui = (set(), set()) if args.forcer else deja_presents(s3, partition)
    a_faire = [
        f for f in fichiers
        if (f.periode == "previous" and f.nom not in toujours)
        or (f.periode == "latest" and f.nom not in aujourdhui)
    ]
    ignores = len(fichiers) - len(a_faire)

    nb_dep = len({f.departement for f in fichiers})
    print(f"{nb_dep} départements, {len(fichiers)} fichiers au catalogue")
    print(f"{len(a_faire)} à télécharger, {ignores} déjà présents dans Bronze")
    print(f"{args.threads} téléchargements en parallèle -> {config.BUCKET_BRONZE}/{partition}/\n")

    debut = time.time()
    resultats: list[Resultat] = []

    with ThreadPoolExecutor(max_workers=args.threads) as pool:
        futurs = [pool.submit(telecharger_un_fichier, s3, f, partition) for f in a_faire]
        for i, futur in enumerate(as_completed(futurs), start=1):
            r = futur.result()
            resultats.append(r)
            if r.statut == "erreur":
                print(f"  ERREUR {r.nom} : {r.message}")
            if i % 20 == 0 or i == len(futurs):
                go = sum(x.octets for x in resultats) / 1e9
                print(f"  {i}/{len(futurs)} fichiers traités ({go:.2f} Go)")

    duree = time.time() - debut

    # --- Bilan ---
    ok = [r for r in resultats if r.statut == "ok"]
    erreurs = [r for r in resultats if r.statut == "erreur"]
    total = sum(r.octets for r in ok)

    print(f"\nTerminé en {duree / 60:.1f} min")
    print(f"  {len(ok)} fichiers déposés ({total / 1e9:.2f} Go compressés), {len(erreurs)} en erreur")
    if erreurs:
        print("  Relancer la même commande pour reprendre les fichiers en erreur.")

    # Traces déposées à côté des fichiers : catalogue d'origine + manifeste.
    horodatage = f"{maintenant:%Y%m%dT%H%M%SZ}"
    ecrire_octets(
        s3, config.BUCKET_BRONZE, f"{partition}/_catalogue_{horodatage}.json",
        catalogue_brut, "application/json",
    )
    manifeste = {
        "source": "Météo-France - Données climatologiques de base horaires (data.gouv.fr)",
        "date_telechargement": maintenant.isoformat(),
        "duree_secondes": round(duree),
        "nb_departements": nb_dep,
        "nb_ok": len(ok),
        "nb_ignores": ignores,
        "nb_erreurs": len(erreurs),
        "octets": total,
        "fichiers": [asdict(r) for r in resultats],
    }
    cle_manifeste = f"{partition}/_manifeste_{horodatage}.json"
    ecrire_octets(
        s3, config.BUCKET_BRONZE, cle_manifeste,
        json.dumps(manifeste, ensure_ascii=False, indent=2).encode("utf-8"),
        "application/json",
    )
    print(f"  Manifeste : {config.BUCKET_BRONZE}/{cle_manifeste}")


if __name__ == "__main__":
    main()
