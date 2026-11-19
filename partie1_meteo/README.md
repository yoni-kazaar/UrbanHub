# Partie 1 : Météo (flux batch, Météo-France)

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
| `nettoyage.py` | Étape 3 : nettoyage Bronze -> Silver (qualité, bornes, vent calme, doublons) |
| `tests/test_nettoyage.py` | Tests des règles de nettoyage |
| `gold.py` | Étape 4 : tables Gold (table du contrat + tables par jour, France, stations) |
| `analyses.py` | Étape 5 : les 4 questions métier + Isolation Forest -> `gold/meteo/analyses/` |
| [`../app/pages/1_Meteo.py`](../app/pages/1_Meteo.py) | Étape 6 : page Streamlit Météo |
| [`RAPPORT.md`](RAPPORT.md) | Étape 7 : section du rapport |
| `Dockerfile`, `Dockerfile.app`, `docker-compose.yml` | Conteneurs Python (scripts) et Streamlit (application) |

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

# 3. Nettoyage Bronze -> Silver
docker compose -f partie1_meteo/docker-compose.yml run --rm meteo python -m pytest partie1_meteo/tests -q
docker compose -f partie1_meteo/docker-compose.yml run --rm meteo python -m partie1_meteo.nettoyage --departements 69 75   # test
docker compose -f partie1_meteo/docker-compose.yml run --rm meteo python -m partie1_meteo.nettoyage                       # toute la France

# 4. Tables Gold (dépose gold/meteo/_SUCCESS à la fin)
docker compose -f partie1_meteo/docker-compose.yml run --rm meteo python -m partie1_meteo.gold

# 5. Questions métier et IA
docker compose -f partie1_meteo/docker-compose.yml run --rm meteo python -m partie1_meteo.analyses

# 6. Application Streamlit -> http://localhost:8501 (page Météo dans le menu)
docker compose -f partie1_meteo/docker-compose.yml --profile app up -d --build app
```

**Mettre à jour avant le gel de la collecte :** relancer les étapes 1 à 5 dans l'ordre.
Seuls les fichiers 2025-2026 sont retéléchargés, et tout le reste est recalculé (≈ 25 min).

## Étape 4 : tables Gold

| Table (`gold/meteo/`) | Contenu |
| --- | --- |
| `meteo_ville_heure.parquet` | **Table du contrat** : 1 ligne par ville et par heure (UTC), publiée avec `common.lake.publier_gold` |
| `meteo_ville_heure_detail.parquet` | Idem + min/max, point de rosée, humidité, rafales, nombre de stations |
| `meteo_ville_jour.parquet` | 1 ligne par ville et par jour (heure de Paris) |
| `meteo_france_jour.parquet` | Moyenne nationale par jour, toutes stations |
| `meteo_stations.parquet` | Les 1 995 stations, pour la carte |
| `analyses/*.parquet`, `analyses/resultats.json` | Résultats des 4 questions (étape 5) |

Une ville = **moyenne de ses stations** (y compris min, max et rafales), direction du vent
moyennée **vectoriellement**. Une journée n'est calculée qu'avec au moins 18 heures mesurées.

## Étape 3 : règles de nettoyage

| Règle | Détail |
| --- | --- |
| Période | Depuis le 1er janvier 2022 (5 dernières années) |
| Date | `AAAAMMJJHH` (heure UTC chez Météo-France) -> `timestamp` datetime UTC |
| Qualité | Code qualité `2` (« douteuse ») -> valeur vidée. Gardés : `0` protégée, `1` validée, `9` filtrée |
| Valeurs impossibles | Hors bornes physiques -> vidées (ex. température -40 à 50 °C, humidité 0 à 100 %, pression 900 à 1 080 hPa) |
| Vent calme | Vitesse 0 -> direction vidée ; 360° -> 0° (nord) |
| Doublons, lignes vides | Même station et même heure : la dernière gardée ; lignes sans aucune mesure supprimées |
| Valeurs absentes | Restent vides (`null`), jamais remplacées par 0 |

**Résultat :** `silver/meteo/year=AAAA/month=MM/dep_<dép>.parquet`, une ligne par station et
par heure, colonnes `station_id`, `station_name`, `ville`, `departement`, `latitude`, `longitude`,
`altitude_m`, `timestamp`, `temperature_c`, `temperature_min_c`, `temperature_max_c`,
`dew_point_c`, `humidity_pct`, `precipitation_mm`, `wind_speed_ms`, `wind_gust_ms`,
`wind_direction_deg`, `visibility_m`, `pressure_hpa`. Le bilan détaillé est dans
`silver/meteo/_rapport_nettoyage.json`.

Relancer le téléchargement est sans risque :
- les fichiers 2020-2024 déjà présents ne sont jamais retéléchargés ;
- les fichiers 2025-2026 sont retéléchargés une fois par jour (nouveau dossier daté) ;
- une relance le même jour ne reprend que les fichiers en erreur.

Pour viser le **VPS** : mettre l'URL HTTPS dans `.env`, puis supprimer la ligne
`MINIO_ENDPOINT` du fichier `docker-compose.yml` de ce dossier.

## Résultats obtenus (19/11/2026)

**Étape 1 : téléchargement**
- 95 départements de métropole, 190 fichiers, **3,3 Go compressés** dans Bronze.
- 19 min avec 8 téléchargements en parallèle ; 8 fichiers en délai dépassé côté
  Météo-France, repris en 0,7 min par une relance.

**Étape 2 : stations**
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
indique pour chacune ce qu'elle mesure (`mesure_temperature`, `mesure_vent`...).

**Étapes 3 à 5** : 77,5 millions de lignes dans Silver, table du contrat de 342 377 lignes
(100 % des heures couvertes dans chaque ville). Résultats des questions métier : voir [RAPPORT.md](RAPPORT.md).
