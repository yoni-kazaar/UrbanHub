"""
Étape 1 – Découverte des capteurs.

1. Récupère tous les sites OpenAQ situés en France (filtre iso=FR).
2. Garde ceux rattachés à l'une des 8 villes (common.villes.rattacher_ville, rayon 30 km).
3. Garde uniquement les capteurs des 5 polluants suivis et encore actifs.
4. Dépose la réponse brute dans bronze/pollution/... et le catalogue dans etat/capteurs.json.

Lancement seul :  python -m partie3_pollution.decouverte_capteurs
"""

import json
from collections import Counter
from datetime import datetime, timedelta, timezone

from common.villes import rattacher_ville

from . import config
from .openaq import OpenAQ
from .stockage import Lac, chemin_partitionne

FICHIER_CATALOGUE = config.DOSSIER_ETAT / "capteurs.json"


def _date_utc(champ):
    """Lit un champ OpenAQ du type {"utc": "2026-11-19T10:00:00Z", ...}."""
    if not champ or not champ.get("utc"):
        return None
    return datetime.fromisoformat(champ["utc"].replace("Z", "+00:00"))


def decouvrir(client, lac):
    maintenant = datetime.now(timezone.utc)
    sites = client.toutes_les_pages("/locations", {"iso": "FR"})
    print(f"{len(sites)} sites OpenAQ en France", flush=True)

    # Bronze : la réponse brute, telle que reçue
    chemin = chemin_partitionne(f"sites_FR_{maintenant:%Y%m%dT%H%M%SZ}.json", maintenant)
    print("  brut ->", lac.ecrire_json("bronze", chemin, {"collecte_utc": maintenant.isoformat(),
                                                           "requete": "/v3/locations?iso=FR",
                                                           "results": sites}), flush=True)

    limite_actif = maintenant - timedelta(days=config.CAPTEUR_ACTIF_JOURS)
    capteurs = []
    for site in sites:
        coord = site.get("coordinates") or {}
        lat, lon = coord.get("latitude"), coord.get("longitude")
        ville = rattacher_ville(lat, lon)
        if ville is None:
            continue
        dernier = _date_utc(site.get("datetimeLast"))
        if dernier is None or dernier < limite_actif:
            continue                       # site arrêté : inutile de l'interroger
        for s in site.get("sensors", []):
            p = s.get("parameter") or {}
            if p.get("name") in config.POLLUANTS:
                capteurs.append({
                    "sensor_id": s["id"],
                    "location_id": site["id"],
                    "location_name": site.get("name"),
                    "pollutant": p["name"],
                    "unit": p.get("units"),
                    "latitude": lat,
                    "longitude": lon,
                    "ville": ville,
                    "is_monitor": site.get("isMonitor"),
                    "provider": (site.get("provider") or {}).get("name"),
                })

    catalogue = {"maj_utc": maintenant.isoformat(), "capteurs": capteurs}
    config.DOSSIER_ETAT.mkdir(parents=True, exist_ok=True)
    FICHIER_CATALOGUE.write_text(json.dumps(catalogue, ensure_ascii=False, indent=2), encoding="utf-8")

    sites_gardes = {c["location_id"] for c in capteurs}
    print(f"{len(capteurs)} capteurs gardés sur {len(sites_gardes)} sites", flush=True)
    print("  par ville    :", dict(Counter(c["ville"] for c in capteurs)), flush=True)
    print("  par polluant :", dict(Counter(c["pollutant"] for c in capteurs)), flush=True)
    print("  unités       :", dict(Counter(f'{c["pollutant"]} {c["unit"]}' for c in capteurs)), flush=True)
    return catalogue


def charger_catalogue():
    if not FICHIER_CATALOGUE.exists():
        return None
    return json.loads(FICHIER_CATALOGUE.read_text(encoding="utf-8"))


if __name__ == "__main__":
    decouvrir(OpenAQ(), Lac())
