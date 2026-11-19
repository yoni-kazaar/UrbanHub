# Partie 2 – Vélos (CityBikes)

Collecte en continu des stations de vélos en libre-service des 8 villes du contrat.

## Collecteur (`collecte.py`)

Toutes les 2 min 30, pour chaque réseau, il télécharge le JSON de l'API CityBikes et le dépose **tel quel** dans MinIO :

```
bronze/velos/year=AAAA/month=MM/day=JJ/velos_<AAAAMMJJ>T<HHMMSS>Z_<réseau>.json
```

Un fichier par réseau et par relevé : bronze ne se modifie jamais.

| Ville | Réseau CityBikes |
| --- | --- |
| Paris | `velib` |
| Lyon | `velov` |
| Marseille | `le-velo` |
| Toulouse | `velo` |
| Lille | `vlille` |
| Bordeaux | `v3-bordeaux` |
| Nantes | `bicloo` |
| Strasbourg | `velhop` |

Nantes (36 stations) et Strasbourg (40) sont de petits réseaux : ils pèsent peu dans les moyennes par ville.

- **Limite de l'API : 300 requêtes par heure et par adresse IP.** 8 réseaux toutes les 3 minutes font 160 requêtes par heure. Ne lance donc **jamais deux collecteurs depuis la même IP** (par exemple deux terminaux, ou ton Mac et un serveur sur le même réseau). Sur une réponse 429, le collecteur n'insiste pas, interrompt le passage et patiente le temps indiqué par l'API (en-tête `Retry-After`).
- Une erreur sur un réseau est notée dans les logs et n'arrête pas les autres (3 essais par requête).
- Aucune dépendance en plus de `common/` : le téléchargement utilise la bibliothèque standard.

## Lancer

Prérequis : MinIO accessible et un `.env` à la racine avec le compte `urbanhub-velos` (voir [Personne.md](../Personne.md#se-connecter)).

```bash
source .venv/bin/activate
PYTHONPATH=. python -m partie2_velos.collecte --une-fois   # un seul passage (test)
PYTHONPATH=. python -m partie2_velos.collecte              # en boucle, Ctrl+C pour arrêter
```

Un passage réussi se termine par `passage terminé : 8/8 réseaux`.

## Vérifier ce qui a été déposé

```bash
PYTHONPATH=. python -c "
from common import lake
f = lake.fs().find('bronze/velos')
print(len(f), 'fichiers'); print(*f[-3:], sep='\n')"
```

Ou dans la console MinIO, bucket `bronze`, dossier `velos/`.

## À savoir

- Le collecteur doit tourner **sans interruption** : chaque heure d'arrêt est une heure de données perdue.
- Pour la prod, il se lance dans un conteneur avec `restart: always`, avec `MINIO_ENDPOINT` pointant vers l'adresse HTTPS du VPS (voir `Personne.md`, section B).

## Silver (`silver.py`)

Lit les JSON de bronze d'un jour et écrit une table nettoyée, une ligne par station et par relevé :

```
silver/velos/year=AAAA/month=MM/day=JJ/velos.parquet      (réécrit à chaque exécution)
```

```bash
PYTHONPATH=. python -m partie2_velos.silver                     # aujourd'hui (UTC)
PYTHONPATH=. python -m partie2_velos.silver --jour 2026-11-19   # un jour précis
PYTHONPATH=. python -m partie2_velos.silver --tout              # tous les jours de bronze
```

| Colonne | Contenu |
| --- | --- |
| `ville` | ville du contrat la plus proche à moins de 30 km (`common.villes.rattacher_ville`), vide sinon |
| `reseau`, `station_id`, `station_name` | identifiants CityBikes |
| `latitude`, `longitude` | position de la station |
| `timestamp` | heure du **relevé** (UTC), tirée du nom du fichier |
| `free_bikes`, `empty_slots`, `capacite` | vélos disponibles, places libres, somme des deux |
| `en_service` | `False` si le réseau indique que la station ne loue ou ne reçoit plus de vélos |

Nettoyage : lignes sans position ou sans compteurs écartées, valeurs négatives écartées, doublons (réseau, station, relevé) supprimés. Les stations hors service sont **conservées** avec `en_service = False` : à filtrer dans les analyses et dans Gold.

## Suite de la partie

`gold.py` (table `gold/velos/velos_ville_heure.parquet`), `analyse.py` et la page `app/pages/2_Velos.py` : voir les tâches de B dans [Personne.md](../Personne.md).
