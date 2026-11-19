"""
Étape 3 : historique des mesures horaires (demandé dans Personne.md).

Pour chaque capteur du catalogue et chaque mois des HISTORIQUE_MOIS derniers mois :
  GET /v3/sensors/{id}/hours?datetime_from=...&datetime_to=...
  -> un fichier brut par capteur et par mois dans
     bronze/pollution/year=AAAA/month=MM/day=01/historique_<capteur>_<AAAAMM>.json

- Découpage par mois : la doc OpenAQ conseille de petites périodes pour éviter les timeouts.
- Reprise automatique : ce qui est déjà téléchargé est noté dans etat/historique_fait.txt,
  donc si le script s'arrête, on le relance et il reprend où il en était.
- Pause de 2,4 s entre deux appels : avec le collecteur qui tourne à côté sur la même clé,
  on reste sous la limite gratuite de 2 000 requêtes par heure.

Lancement : python -m partie3_pollution.historique
"""

import os
from datetime import datetime, timezone

from . import config
from .decouverte_capteurs import charger_catalogue, decouvrir
from .openaq import OpenAQ
from .stockage import Lac, chemin_partitionne

HISTORIQUE_MOIS = int(os.environ.get("HISTORIQUE_MOIS", "12"))
FICHIER_FAIT = config.DOSSIER_ETAT / "historique_fait.txt"


def periodes_mensuelles(nb_mois, maintenant):
    """[(début, fin), ...] du mois en cours jusqu'à nb_mois mois en arrière."""
    periodes = []
    annee, mois = maintenant.year, maintenant.month
    fin = maintenant
    for _ in range(nb_mois + 1):              # +1 : le mois en cours, partiel
        debut = datetime(annee, mois, 1, tzinfo=timezone.utc)
        periodes.append((debut, fin))
        fin = debut
        mois -= 1
        if mois == 0:
            annee, mois = annee - 1, 12
    return list(reversed(periodes))


def main():
    client, lac = OpenAQ(pause_s=2.4), Lac()
    cat = charger_catalogue() or decouvrir(client, lac)
    capteurs = cat["capteurs"]
    maintenant = datetime.now(timezone.utc)
    periodes = periodes_mensuelles(HISTORIQUE_MOIS, maintenant)

    config.DOSSIER_ETAT.mkdir(parents=True, exist_ok=True)
    fait = set(FICHIER_FAIT.read_text().split()) if FICHIER_FAIT.exists() else set()
    taches = [(c, d, f) for c in capteurs for d, f in periodes if f"{c['sensor_id']}_{d:%Y%m}" not in fait]
    total = len(capteurs) * len(periodes)
    print(f"Historique : {len(capteurs)} capteurs x {len(periodes)} mois = {total} tranches, "
          f"{total - len(taches)} déjà faites, {len(taches)} à télécharger | stockage : {lac.mode()}", flush=True)
    print(f"Durée estimée : ~{len(taches) * 2.5 / 3600:.1f} h", flush=True)

    nb_mesures, erreurs = 0, 0
    for i, (c, debut, fin) in enumerate(taches, 1):
        sid = c["sensor_id"]
        try:
            results = client.toutes_les_pages(f"/sensors/{sid}/hours", {
                "datetime_from": debut.isoformat().replace("+00:00", "Z"),
                "datetime_to": fin.isoformat().replace("+00:00", "Z"),
            })
            lac.ecrire_json("bronze", chemin_partitionne(f"historique_{sid}_{debut:%Y%m}.json", debut), {
                "collecte_utc": datetime.now(timezone.utc).isoformat(),
                "requete": f"/v3/sensors/{sid}/hours",
                "sensor_id": sid,
                "datetime_from": debut.isoformat(),
                "datetime_to": fin.isoformat(),
                "results": results,
            })
            with open(FICHIER_FAIT, "a") as f:
                f.write(f"{sid}_{debut:%Y%m}\n")
            nb_mesures += len(results)
        except Exception as e:
            erreurs += 1
            print(f"  capteur {sid} {debut:%Y-%m} : {e}", flush=True)
        if i % 50 == 0 or i == len(taches):
            print(f"[{datetime.now(timezone.utc):%H:%M:%S}Z] {i}/{len(taches)} tranches | "
                  f"{nb_mesures} mesures | {erreurs} erreurs", flush=True)

    print("Historique terminé." if erreurs == 0 else
          f"Terminé avec {erreurs} erreurs : relancer le script pour réessayer uniquement celles-là.", flush=True)


if __name__ == "__main__":
    main()