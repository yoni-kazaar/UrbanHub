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

## Suite de la partie

`silver.py` (nettoyage, une ligne par station et par relevé), `gold.py` (table `gold/velos/velos_ville_heure.parquet`), `analyse.py` et la page `app/pages/2_Velos.py` : voir les tâches de B dans [Personne.md](../Personne.md).
