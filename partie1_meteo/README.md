# Partie 1 – Météo (flux batch, Météo-France)

Responsable : personne A. Voir [Personne.md](../Personne.md#personne-a) et [CONTRAT.md](../CONTRAT.md).

## Source

[Données climatologiques de base horaires](https://www.data.gouv.fr/fr/datasets/donnees-climatologiques-de-base-horaires/)
de Météo-France (Licence Ouverte), un fichier CSV compressé par département et par période :

| Fichier | Période | Mise à jour |
| --- | --- | --- |
| `H_<dép>_previous-2020-2024.csv.gz` | 2020 à 2024 | figé |
| `H_<dép>_latest-2025-2026.csv.gz` | 2025 à aujourd'hui | chaque jour |

**Pourquoi pas NOAA ?** Le sujet indique NOAA Global Hourly, mais ce jeu n'est plus
publié depuis le 24/08/2025 (aucun fichier 2026). Son successeur GHCNh n'a aucune
donnée 2026 pour Lyon, Lille et Strasbourg. Météo-France couvre les 8 villes
jusqu'au jour même : choix validé par le professeur.

## Fichiers

| Fichier | Rôle |
| --- | --- |
| `config.py` | Paramètres : catalogue data.gouv.fr, années, threads, buckets |
| `provisoire.py` | Villes et accès MinIO (les villes sont identiques à `common/villes.py`) |
| `telechargement.py` | Étape 1 : téléchargement parallèle des fichiers départementaux vers Bronze |
| `stations.py` | Étape 2 : liste des stations françaises + rattachement aux villes |
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

# 1. Téléchargement parallèle
#    test rapide (Rhône et Paris) :
docker compose -f partie1_meteo/docker-compose.yml run --rm meteo python -m partie1_meteo.telechargement --departements 69 75
#    toute la métropole :
docker compose -f partie1_meteo/docker-compose.yml run --rm meteo python -m partie1_meteo.telechargement

# 2. Stations
docker compose -f partie1_meteo/docker-compose.yml run --rm meteo python -m partie1_meteo.stations
```

Relancer le téléchargement est sans risque :
- les fichiers 2020-2024 déjà présents ne sont jamais retéléchargés ;
- les fichiers 2025-2026 sont retéléchargés une fois par jour (nouveau dossier daté) ;
- une relance le même jour ne reprend que les fichiers en erreur.

Pour viser le **VPS** : mettre l'URL HTTPS dans `.env`, puis supprimer la ligne
`MINIO_ENDPOINT` du fichier `docker-compose.yml` de ce dossier.

## Résultats obtenus (19/11/2026)

**Étape 1 – téléchargement**
- 95 départements de métropole, 190 fichiers, **3,3 Go compressés** dans Bronze.
- 19 min avec 8 téléchargements en parallèle ; 8 fichiers en délai dépassé côté
  Météo-France, repris en 0,7 min par une relance.

**Étape 2 – stations**
- **2 098 stations** actives depuis 2022, dernière mesure le 19/11/2026 à 05 h UTC.
- 81 stations rattachées aux 8 villes, avec les 5 variables dans chaque ville :

| Ville | Stations | Station la plus proche du centre |
| --- | ---: | --- |
| Paris | 24 | Luxembourg (1,6 km) |
| Lyon | 12 | Lyon Tête d'Or (1,8 km) |
| Marseille | 12 | Marseille-Obs (2,2 km) |
| Toulouse | 8 | Toulouse-Blagnac (5,6 km) |
| Lille | 3 | Lille-Lesquin (7,2 km) |
| Bordeaux | 8 | Bordeaux-Paulin (1,5 km) |
| Nantes | 9 | Nantes-Ville (3,2 km) |
| Strasbourg | 5 | Strasbourg-Botanique (1,5 km) |

Une station ne mesure pas forcément toutes les variables : la visibilité et la
pression ne sont relevées que dans les grandes stations. La table `stations.parquet`
indique pour chacune ce qu'elle mesure (`mesure_temperature`, `mesure_vent`…).
