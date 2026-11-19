# UrbanHub – Contrat commun

Ce contrat est le seul lien entre les 4 parties du projet. Tant que chacun le respecte, chacun avance seul, sans attendre les autres.

Toute modification du contrat doit être validée par les 4 membres de l'équipe.

## Répartition

| Personne | Partie | Source | Type de flux |
| --- | --- | --- | --- |
| A | 1 – Météo | NOAA Global Hourly | Batch (5 dernières années) |
| B | 2 – Vélos | API CityBikes | Streaming (toutes les 2-3 min) |
| C | 3 – Pollution | API OpenAQ | IoT (ingestion régulière) |
| D | 4 – Analyse croisée et interface | Les 3 tables Gold | Jointure |

## Règles communes

| Règle | Valeur |
| --- | --- |
| Villes | `Paris`, `Lyon`, `Marseille`, `Toulouse`, `Lille`, `Bordeaux`, `Nantes`, `Strasbourg` (colonne `ville`, orthographe exacte) |
| Date et heure | Colonne `timestamp` en **UTC**, format ISO 8601 (`2026-11-19T14:00:00Z`) |
| Heure d'agrégation | Colonne `heure` = `timestamp` arrondi à l'heure inférieure, en UTC |
| Affichage | Les graphiques affichent l'heure de Paris (`Europe/Paris`). Le stockage reste toujours en UTC |
| Position | Colonnes `latitude` et `longitude` en degrés décimaux |
| Noms de colonnes | En minuscules avec des `_` (`wind_speed`, `bikes_available`) |
| Rattachement à une ville | Une station ou un capteur appartient à une ville s'il est à moins de **30 km** de son centre. Sinon, `ville` est vide |
| Agrégation par ville et par heure | **Moyenne** des stations ou capteurs de la ville |

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

## Organisation du dépôt

Un dossier par partie : chacun travaille dans le sien, ce qui évite les conflits.

```
UrbanHub/
├── CONTRAT.md                # ce fichier
├── docker-compose.yml        # MinIO + application Streamlit
├── .env.example              # variables attendues, sans valeurs secrètes
├── partie1_meteo/
├── partie2_velos/
├── partie3_pollution/
├── partie4_croisee/
└── app/                      # interface Streamlit
    ├── Accueil.py            # Partie 4
    └── pages/
        ├── 1_Meteo.py        # Partie 1
        ├── 2_Velos.py        # Partie 2
        ├── 3_Pollution.py    # Partie 3
        └── 4_Croisee.py      # Partie 4
```

## Secrets

- Les clés et mots de passe (clé OpenAQ, identifiants MinIO) vont dans un fichier `.env`, **jamais commité**.
- Le fichier `.env.example` liste les variables attendues, sans leur valeur.
