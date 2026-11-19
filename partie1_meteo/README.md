# Partie 1 – Météo (flux batch, NOAA)

Responsable : personne A. Voir [Personne.md](../Personne.md#personne-a) et [CONTRAT.md](../CONTRAT.md).

## Fichiers

| Fichier | Rôle |
| --- | --- |
| `config.py` | Paramètres : URL NOAA, années, nombre de threads, buckets |
| `provisoire.py` | Villes et accès MinIO, en attendant `common/` (à supprimer ensuite) |
| `stations.py` | Étape 1 : liste des stations françaises + rattachement aux villes |
| `telechargement.py` | Étape 2 : téléchargement parallèle vers Bronze |
| `Dockerfile`, `docker-compose.yml` | Conteneur Python pour lancer les scripts |

## Pourquoi Docker pour lancer Python ?

Sur certains PC Windows, Smart App Control bloque la bibliothèque `pyarrow`
(nécessaire pour Parquet). Le code tourne donc dans un conteneur Python :
même résultat sur toutes les machines.

## Prérequis

1. Le MinIO de [infra/](../infra/README.md) tourne : `docker compose -f infra/docker-compose.yml up -d minio`
2. Un fichier `.env` à la racine (modèle : [.env.example](../.env.example)) avec le compte **`urbanhub-meteo`** :
   ```
   MINIO_ENDPOINT=http://localhost:9000
   MINIO_ACCESS_KEY=urbanhub-meteo
   MINIO_SECRET_KEY=<secret fourni par D>
   ```

Ce compte ne peut écrire que dans `bronze/meteo/`, `silver/meteo/` et `gold/meteo/`.

## Lancer (depuis la racine du dépôt)

```bash
# Construire l'image Python (une seule fois, ou après un changement de requirements.txt)
docker compose -f partie1_meteo/docker-compose.yml build meteo

# 1. Stations
docker compose -f partie1_meteo/docker-compose.yml run --rm meteo python -m partie1_meteo.stations

# 2. Téléchargement parallèle
#    test rapide :
docker compose -f partie1_meteo/docker-compose.yml run --rm meteo python -m partie1_meteo.telechargement --villes-seulement --limite 3 --annees 2024
#    toute la France :
docker compose -f partie1_meteo/docker-compose.yml run --rm meteo python -m partie1_meteo.telechargement
```

Relancer le téléchargement est sans risque : les années passées déjà présentes
dans Bronze sont ignorées, seules les erreurs et l'année en cours sont refaites.

Pour viser le **VPS** : mettre l'URL HTTPS dans `.env`, puis supprimer la ligne
`MINIO_ENDPOINT` du fichier `docker-compose.yml` de ce dossier.

## Résultats obtenus (19/11/2026)

- 208 stations françaises actives depuis 2022, dont 21 rattachées aux 8 villes.
- Toutes les villes ont au moins une station (Paris : 8, dont Orly et Montsouris).
- 21 stations des 8 villes : 81 fichiers en 2,5 min, 0,51 Go bruts → 0,05 Go en gzip.

## ⚠️ Limite connue : les données s'arrêtent au 24 août 2025

Le jeu NOAA « Global Hourly » (ISD) indiqué dans le sujet n'est plus mis à jour :
aucun fichier 2026, derniers relevés le 24/08/2025. NOAA l'a remplacé par
**GHCNh** (`s3://noaa-ghcnh-pds/hourly/access/by-year/<année>/psv/`), qui couvre
2026 et est mis à jour chaque jour. Décision d'équipe en attente.
