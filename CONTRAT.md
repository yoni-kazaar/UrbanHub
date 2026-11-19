# UrbanHub – Contrat commun

Ce contrat est le seul lien entre les 4 parties du projet. Tant que chacun le respecte, chacun avance seul, sans attendre les autres.

Toute modification du contrat doit être validée par les 4 membres de l'équipe.

## Répartition

| Personne | Partie | Source | Type de flux |
| --- | --- | --- | --- |
| A | 1 – Météo | NOAA Global Hourly | Batch (5 dernières années) |
| B | 2 – Vélos | API CityBikes | Streaming (toutes les 2-3 min) |
| C | 3 – Pollution | API OpenAQ | IoT (ingestion régulière) |
| D | 4 – Plateforme et analyse croisée | Les 3 tables Gold | Jointure |

Le détail des tâches est dans [Personne.md](Personne.md).

## Architecture

```
Sources (NOAA, CityBikes, OpenAQ)
      │  ingestion : scripts Python (collecteurs pour B et C)
      ▼
MinIO – Data Lake              bronze → silver → gold (Parquet)
      │  lecture des 3 tables Gold
      ▼
Streamlit – indicateurs urbains   une page par partie + accueil
```

- **MinIO** est hébergé sur **un seul VPS**, administré par D. Les autres s'y connectent comme à un service web (URL HTTPS + clés), **sans accès SSH** au serveur.
- **GitHub** contient le code, jamais les données (ni Bronze, ni Silver, ni Gold).
- Il n'y a pas de base de données séparée : l'interface lit directement les tables Gold (Parquet) dans MinIO.

## Règles communes

| Règle | Valeur |
| --- | --- |
| Villes | `Paris`, `Lyon`, `Marseille`, `Toulouse`, `Lille`, `Bordeaux`, `Nantes`, `Strasbourg` (colonne `ville`, orthographe exacte) |
| Centres des villes | Un seul fichier de référence, `common/villes.py` (latitude et longitude). Personne n'utilise d'autres coordonnées |
| Date et heure | Colonne `timestamp` en **UTC**, format ISO 8601 (`2026-11-19T14:00:00Z`) |
| Heure d'agrégation | Colonne `heure` = `timestamp` arrondi à l'heure inférieure, en UTC |
| Type de `heure` dans Parquet | Vraie colonne `datetime` avec fuseau UTC, **pas du texte** (sinon la jointure échoue) |
| Affichage | Les graphiques affichent l'heure de Paris (`Europe/Paris`). Le stockage reste toujours en UTC |
| Position | Colonnes `latitude` et `longitude` en degrés décimaux |
| Noms de colonnes | En minuscules avec des `_` (`wind_speed`, `bikes_available`) |
| Rattachement à une ville | Une station ou un capteur appartient à une ville s'il est à moins de **30 km** de son centre (la plus proche si plusieurs). Sinon, `ville` est vide. Fonction commune : `common.villes.rattacher_ville` |
| Agrégation par ville et par heure | **Moyenne** des stations ou capteurs de la ville |
| Colonnes minimales de Silver | `ville`, `latitude`, `longitude`, `timestamp`, plus les mesures (les analyses par station se font sur Silver) |

## Stockage : Data Lake MinIO

3 buckets :

| Bucket | Contenu | Format |
| --- | --- | --- |
| `bronze` | Données brutes, telles que reçues | Format d'origine (CSV, JSON) |
| `silver` | Données nettoyées | Parquet |
| `gold` | Tables finales prêtes à l'analyse | Parquet |

Chemins :

```
<bucket>/<source>/year=AAAA/month=MM/day=JJ/<fichier>
```

avec `<source>` = `meteo`, `velos` ou `pollution`.

Exemple : `bronze/velos/year=2026/month=11/day=19/velos_20261119T140000Z.json`

## Les 3 tables Gold

Une ligne par **ville** et par **heure**. Ces trois tables doivent avoir exactement ce format, car la Partie 4 les joint sur `ville` + `heure`.

Chacun reste libre de produire d'autres tables pour ses propres analyses.

### `gold/meteo/meteo_ville_heure.parquet` (Partie 1)

| Colonne | Type | Unité |
| --- | --- | --- |
| `ville` | texte | |
| `heure` | datetime UTC | |
| `temperature_c` | décimal | °C |
| `precipitation_mm` | décimal | mm |
| `wind_speed_ms` | décimal | m/s |
| `wind_direction_deg` | décimal | degrés (0–360) |
| `visibility_m` | décimal | m |
| `pressure_hpa` | décimal | hPa |

### `gold/velos/velos_ville_heure.parquet` (Partie 2)

| Colonne | Type | Unité |
| --- | --- | --- |
| `ville` | texte | |
| `heure` | datetime UTC | |
| `bikes_available` | décimal | vélos (moyenne sur l'heure) |
| `free_slots` | décimal | places (moyenne sur l'heure) |
| `taux_occupation` | décimal | 0 à 1, = `bikes_available / (bikes_available + free_slots)` |

### `gold/pollution/pollution_ville_heure.parquet` (Partie 3)

| Colonne | Type | Unité |
| --- | --- | --- |
| `ville` | texte | |
| `heure` | datetime UTC | |
| `pm25` | décimal | µg/m³ |
| `pm10` | décimal | µg/m³ |
| `no2` | décimal | µg/m³ |
| `o3` | décimal | µg/m³ |
| `co` | décimal | µg/m³ |

Une valeur absente est laissée vide (`null`), jamais remplacée par 0.

Les trois tables n'ont pas la même durée : la météo couvre 5 ans, les vélos seulement depuis le début de leur collecte. La Partie 4 travaille donc sur la **période commune** des trois tables.

## Règles d'écriture dans MinIO

| Compte MinIO | Peut écrire dans | Peut lire |
| --- | --- | --- |
| `urbanhub-meteo` (A) | `bronze/meteo/`, `silver/meteo/`, `gold/meteo/` | `gold/` |
| `urbanhub-velos` (B) | `bronze/velos/`, `silver/velos/`, `gold/velos/` | `gold/` |
| `urbanhub-pollution` (C) | `bronze/pollution/`, `silver/pollution/`, `gold/pollution/` | `gold/` |
| `urbanhub-croise` (D) | `gold/croise/` | tout |

- **Bronze ne se modifie jamais** : chaque relevé est un nouveau fichier horodaté (`velos_20261119T140000Z.json`).
- **Silver et Gold** peuvent être réécrits, uniquement par leur propriétaire.
- **Une table Gold est prête** quand son propriétaire a déposé un fichier vide `gold/<source>/_SUCCESS`.
- Le bucket `gold` a le **versioning activé**.
- Le compte administrateur de MinIO n'est connu que de D.

## Interface : Streamlit

- Une page par partie : **Météo** (A), **Vélos** (B), **Pollution** (C), plus **Accueil** et **Analyse croisée** (D).
- Chaque page lit les tables Gold dans MinIO (clés en lecture seule sur `gold/`).
- Le code des pages est dans `app/`. L'application peut être lancée en local (`streamlit run app/Accueil.py`) ou hébergée gratuitement sur Streamlit Community Cloud.

## Infrastructure : un VPS pour MinIO

- Un seul VPS, celui de D, héberge MinIO avec Docker.
- Seul le port **443 (HTTPS)** est ouvert, derrière Caddy. La console d'administration MinIO (9001) n'est **jamais** exposée sur Internet.
- **A, B et C n'ont pas d'accès SSH** : ils utilisent uniquement l'API S3 de MinIO avec leur compte (`MINIO_ENDPOINT` et clés dans leur `.env`). D crée et gère les comptes.
- **Collecteurs B et C** : ils doivent tourner en continu, sur une machine allumée en permanence (un PC allumé, ou le VPS déployé par D à leur demande). Ils n'ont besoin que de l'URL et des clés MinIO.
- **Sauvegardes** : D fait un snapshot régulier du VPS ou du volume MinIO.
- **Développement** : tester d'abord sur un MinIO local, puis basculer sur le VPS en changeant `MINIO_ENDPOINT`.

## Organisation du dépôt

Un dossier par partie : chacun travaille dans le sien, ce qui évite les conflits.

```
UrbanHub/
├── CONTRAT.md                  # ce fichier
├── Personne.md                 # tâches de chaque personne
├── .env.example                # variables attendues, sans valeurs secrètes
├── requirements.txt
├── infra/                      # D : MinIO et Caddy (docker-compose.yml)
├── common/                     # code partagé (relu par au moins 2 personnes)
│   ├── villes.py               # les 8 villes, leurs centres, rattacher_ville
│   ├── lake.py                 # lecture/écriture MinIO
│   ├── schemas.py              # format des 3 tables Gold + validation
│   └── fake_gold.py            # fausses tables Gold (pour D et l'interface)
├── partie1_meteo/              # A
├── partie2_velos/              # B
├── partie3_pollution/          # C
├── partie4_croisee/            # D
└── app/                        # interface Streamlit
    ├── Accueil.py              # D
    └── pages/
        ├── 1_Meteo.py          # A
        ├── 2_Velos.py          # B
        ├── 3_Pollution.py      # C
        └── 4_Croisee.py        # D
```

## Secrets

- Les clés et mots de passe (clé OpenAQ, comptes MinIO) vont dans un fichier `.env`, **jamais commité**.
- Le fichier `.env.example` liste les variables attendues, sans leur valeur.
- Chaque personne n'utilise que son propre compte MinIO.
