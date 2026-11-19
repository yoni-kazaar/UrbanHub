"""
Petit client pour l'API OpenAQ v3.

- Authentification par l'en-tête X-API-Key.
- Respect de la limite gratuite (60 requêtes / minute) : une pause entre chaque appel.
- Nouvel essai automatique si l'API répond 429 (trop de requêtes) ou 5xx (panne passagère).
"""

import time

import requests

from . import config


class OpenAQ:
    def __init__(self, api_key=config.OPENAQ_API_KEY, pause_s=1.1, essais=5):
        if not api_key:
            raise RuntimeError("OPENAQ_API_KEY manquante : ajoute-la dans le fichier .env")
        self.session = requests.Session()
        self.session.headers.update({"X-API-Key": api_key, "Accept": "application/json"})
        self.pause_s = pause_s      # 1,1 s entre deux appels -> moins de 60 appels par minute
        self.essais = essais
        self._dernier_appel = 0.0

    def get(self, chemin, params=None):
        """Appelle GET {base}{chemin} et renvoie le JSON. Réessaie en cas d'erreur passagère."""
        url = config.OPENAQ_BASE_URL + chemin
        for essai in range(1, self.essais + 1):
            attente = self.pause_s - (time.monotonic() - self._dernier_appel)
            if attente > 0:
                time.sleep(attente)
            self._dernier_appel = time.monotonic()
            try:
                rep = self.session.get(url, params=params, timeout=30)
            except requests.RequestException as e:
                print(f"  [réseau] {e} (essai {essai}/{self.essais})", flush=True)
                time.sleep(5 * essai)
                continue
            if rep.status_code == 200:
                return rep.json()
            if rep.status_code == 429 or rep.status_code >= 500:
                # 429 = limite atteinte : on attend le temps indiqué par l'API (ou 60 s)
                reset = rep.headers.get("x-ratelimit-reset")
                attente = int(reset) if reset and reset.isdigit() else 60 if rep.status_code == 429 else 5 * essai
                print(f"  [HTTP {rep.status_code}] pause {attente}s (essai {essai}/{self.essais})", flush=True)
                time.sleep(attente)
                continue
            rep.raise_for_status()   # 401, 404... : erreur définitive
        raise RuntimeError(f"Échec après {self.essais} essais : {url}")

    def toutes_les_pages(self, chemin, params=None, limit=1000):
        """Parcourt toutes les pages d'un résultat et renvoie la liste complète des 'results'."""
        params = dict(params or {}, limit=limit)
        resultats, page = [], 1
        while True:
            data = self.get(chemin, dict(params, page=page))
            lot = data.get("results", [])
            resultats.extend(lot)
            if len(lot) < limit:
                return resultats
            page += 1
