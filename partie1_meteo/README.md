# Partie 1 – Météo (flux batch, NOAA)

Responsable : personne A. Voir [Personne.md](../Personne.md#personne-a) et [CONTRAT.md](../CONTRAT.md).

## Fichiers

| Fichier | Rôle |
| --- | --- |
| `config.py` | Paramètres : URL NOAA, années, nombre de threads, buckets |
| `provisoire.py` | Villes et accès MinIO, en attendant `common/` (à supprimer ensuite) |
| `init_local.py` | Étape 0 : crée les buckets du MinIO **local** |
| `stations.py` | Étape 1 : liste des stations françaises + rattachement aux villes |
| `telechargement.py` | Étape 2 : téléchargement parallèle vers Bronze |
| `Dockerfile`, `docker-compose.minio-local.yml` | MinIO local + conteneur Python |

## Pourquoi Docker pour lancer Python ?

Sur certains PC Windows, Smart App Control bloque la bibliothèque `pyarrow`
(nécessaire pour Parquet). Le code tourne donc dans un conteneur Python :
même résultat sur toutes les machines.

## Lancer (depuis la racine du dépôt)

```bash
# 0. Préparer
cp partie1_meteo/.env.example .env
docker compose -f partie1_meteo/docker-compose.minio-local.yml up -d
docker compose -f partie1_meteo/docker-compose.minio-local.yml build meteo
docker compose -f partie1_meteo/docker-compose.minio-local.yml run --rm meteo python -m partie1_meteo.init_local

# 1. Stations
docker compose -f partie1_meteo/docker-compose.minio-local.yml run --rm meteo python -m partie1_meteo.stations

# 2. Téléchargement parallèle
#    test rapide :
docker compose -f partie1_meteo/docker-compose.minio-local.yml run --rm meteo python -m partie1_meteo.telechargement --villes-seulement --limite 3 --annees 2024
#    les 8 villes :
docker compose -f partie1_meteo/docker-compose.minio-local.yml run --rm meteo python -m partie1_meteo.telechargement --villes-seulement
#    toute la France :
docker compose -f partie1_meteo/docker-compose.minio-local.yml run --rm meteo python -m partie1_meteo.telechargement
```

Console MinIO locale : http://localhost:9101 (minioadmin / minioadmin).

Pour envoyer les données sur le **VPS** : mettre l'URL et les clés du compte
`meteo` dans `.env`, puis supprimer la ligne `MINIO_ENDPOINT` du service
`meteo` dans `docker-compose.minio-local.yml`.

## Résultats obtenus (19/11/2026)

- 208 stations françaises actives depuis 2022, dont 21 rattachées aux 8 villes.
- Toutes les villes ont au moins une station (Paris : 8, dont Orly et Montsouris).
- 21 stations × 5 ans : 78 fichiers en 1,9 min, 0,48 Go bruts → 0,05 Go en gzip.

## ⚠️ Limite connue : les données s'arrêtent au 24 août 2025

Le jeu NOAA « Global Hourly » (ISD) indiqué dans le sujet n'est plus mis à jour :
aucun fichier 2026, derniers relevés le 24/08/2025. NOAA l'a remplacé par
**GHCNh** (`s3://noaa-ghcnh-pds/hourly/access/by-year/<année>/psv/`), qui couvre
2026 et est mis à jour chaque jour. Décision d'équipe en attente.
