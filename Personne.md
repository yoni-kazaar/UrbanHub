# UrbanHub – Tâches par personne

Chaque personne mène sa partie de bout en bout, sans attendre les autres. Le seul lien entre les parties est le [contrat commun](CONTRAT.md).

## Sommaire

1. [Vue d'ensemble](#vue-densemble)
2. [Architecture sur le VPS](#architecture)
3. [Règles MinIO](#regles-minio)
4. [Personne A – Météo (flux batch)](#personne-a)
5. [Personne B – Vélos (flux streaming)](#personne-b)
6. [Personne C – Pollution (flux IoT)](#personne-c)
7. [Personne D – Plateforme et analyse croisée](#personne-d)

---

<a id="vue-densemble"></a>

## Vue d'ensemble

| Personne | Partie | Source | Table Gold | Schéma PostgreSQL | Tableau de bord Grafana |
| :---: | --- | --- | --- | --- | --- |
| **A** | Météo – batch | NOAA Global Hourly | `gold/meteo/meteo_ville_heure.parquet` | `meteo` | Météo |
| **B** | Vélos – streaming | API CityBikes | `gold/velos/velos_ville_heure.parquet` | `velos` | Vélos |
| **C** | Pollution – IoT | API OpenAQ | `gold/pollution/pollution_ville_heure.parquet` | `pollution` | Pollution |
| **D** | Plateforme et analyse croisée | Les 3 tables Gold | – | `croise` | Accueil et Analyse croisée |

> **À faire par tout le monde le jour 1 :** relire et valider [CONTRAT.md](CONTRAT.md), récupérer son compte MinIO et son accès SSH au VPS, puis travailler uniquement dans son propre dossier.

---

<a id="architecture"></a>

## Architecture sur le VPS

```
Sources (NOAA, CityBikes, OpenAQ)
      │  ingestion : scripts et collecteurs Docker
      ▼
MinIO – Data Lake         bronze → silver → gold (Parquet)
      │  chargement de chaque table Gold
      ▼
PostgreSQL – Data Warehouse   un schéma par partie + schéma « croise »
      │
      ▼
Grafana – indicateurs urbains   un tableau de bord par partie
```

Un `docker-compose.yml` par personne, tous reliés au même réseau Docker externe `urbanhub` :

```
UrbanHub/
├── CONTRAT.md
├── Personne.md
├── .env.example
├── infra/                      # D : MinIO, PostgreSQL, Grafana, Caddy (HTTPS)
│   └── docker-compose.yml
├── partie1_meteo/              # A : tâche batch lancée à la main
│   ├── docker-compose.yml
│   └── grafana/meteo.json
├── partie2_velos/              # B : collecteur, restart: always
│   ├── docker-compose.yml
│   └── grafana/velos.json
├── partie3_pollution/          # C : collecteur, restart: always
│   ├── docker-compose.yml
│   └── grafana/pollution.json
└── partie4_croisee/            # D : vues SQL, modèle IA, tableaux de bord
    └── grafana/accueil.json, croise.json
```

**Déployer sa partie sur le VPS :**

```bash
cd UrbanHub/partieX_xxx
git pull
docker compose up -d --build
```

**Accéder à MinIO et PostgreSQL depuis son PC (tunnel SSH, rien n'est exposé sur Internet) :**

```bash
ssh -L 9000:localhost:9000 -L 9001:localhost:9001 -L 5432:localhost:5432 user@ip-du-vps
```

L'API MinIO est alors sur `localhost:9000`, sa console sur `localhost:9001` et PostgreSQL sur `localhost:5432`.

---

<a id="regles-minio"></a>

## Règles MinIO

### Un compte par personne

| Compte | Peut écrire dans | Peut lire |
| --- | --- | --- |
| `meteo` (A) | `bronze/meteo/`, `silver/meteo/`, `gold/meteo/` | `gold/` |
| `velos` (B) | `bronze/velos/`, `silver/velos/`, `gold/velos/` | `gold/` |
| `pollution` (C) | `bronze/pollution/`, `silver/pollution/`, `gold/pollution/` | `gold/` |
| `croise` (D) | `gold/croise/` | tout |

Personne ne peut écraser les données d'un autre, même par erreur.

### Règles d'écriture

- **Bronze ne se modifie jamais** : chaque relevé est un nouveau fichier horodaté (`velos_20261119T140000Z.json`).
- **Silver et Gold** peuvent être réécrits, uniquement par leur propriétaire.
- **Table Gold prête** : son propriétaire dépose un fichier vide `gold/<source>/_SUCCESS`. Les chargements vers PostgreSQL n'importent que les tables qui en ont un.
- **Versioning activé** sur le bucket `gold`, pour pouvoir revenir en arrière.
- **Développement** : tester d'abord sur un MinIO local, puis basculer sur le VPS en changeant `MINIO_ENDPOINT` dans `.env`.

---

<a id="personne-a"></a>

## Personne A – Météo (flux batch, NOAA)

**Dossier :** `partie1_meteo/` · **Compte MinIO :** `meteo` · **Schéma PostgreSQL :** `meteo`

> ⚠️ **À vérifier avant de lancer :** 5 ans de données pour toute la France représentent plusieurs Go. Contrôler l'espace disque libre du VPS.

### 1. Collecte

- [ ] Récupérer la liste des stations NOAA et garder les stations françaises.
- [ ] Écrire un script qui télécharge **en parallèle** les fichiers des 5 dernières années et les dépose dans `bronze/meteo/`.
- [ ] Mettre le script dans un conteneur Docker lancé à la main sur le VPS.

### 2. Traitement

- [ ] Décoder les champs : température, vent (vitesse et direction), pression, visibilité, précipitations. Les valeurs `+9999` signifient « manquant ».
- [ ] Nettoyer (valeurs manquantes, unités, heure en UTC) et écrire dans `silver/meteo/` en gardant **toutes** les stations françaises.
- [ ] Produire `gold/meteo/meteo_ville_heure.parquet`, puis déposer `gold/meteo/_SUCCESS`.
- [ ] Charger la table Gold dans le schéma PostgreSQL `meteo`.

### 3. Analyse

- [ ] Répondre aux 4 questions métier :
    1. Périodes météorologiques anormales
    2. Lien entre météo et visibilité
    3. Évolution saisonnière de la température, en France et dans les 8 villes
    4. Jours extrêmes
- [ ] **IA :** détecter les anomalies (Isolation Forest ou z-score).

### 4. Livrables

- [ ] Tableau de bord Grafana **Météo** (courbes saisonnières, carte des stations, jours extrêmes), exporté dans `partie1_meteo/grafana/meteo.json`
- [ ] Partie du rapport
- [ ] Vidéo de démo

---

<a id="personne-b"></a>

## Personne B – Vélos (flux streaming, CityBikes)

**Dossier :** `partie2_velos/` · **Compte MinIO :** `velos` · **Schéma PostgreSQL :** `velos`

> ⚠️ **Priorité absolue :** la collecte doit démarrer sur le VPS dès le jour 1 et tourner sans interruption, sinon il n'y aura pas assez de données.

### 1. Collecte

- [ ] Trouver l'identifiant du réseau de chacune des 8 villes dans l'API.
- [ ] Écrire un collecteur qui tourne toutes les 2 à 3 minutes et dépose les relevés dans `bronze/velos/`.
- [ ] Le déployer sur le VPS dans un conteneur avec `restart: always`.
- [ ] **Lancer la collecte le plus tôt possible**, puis vérifier chaque jour qu'elle tourne (`docker compose logs`).

### 2. Traitement

- [ ] Nettoyer et dédoublonner, puis écrire dans `silver/velos/`.
- [ ] Calculer le taux d'occupation et produire `gold/velos/velos_ville_heure.parquet`, puis déposer `gold/velos/_SUCCESS`.
- [ ] Charger la table Gold et la table des stations dans le schéma PostgreSQL `velos`.

### 3. Analyse

- [ ] Répondre aux 5 questions métier :
    1. Stations les plus utilisées
    2. Zones où l'offre de vélos est insuffisante
    3. Pics d'utilisation journaliers
    4. Déséquilibres géographiques
    5. Stations critiques à rééquilibrer
- [ ] **IA :** regrouper les stations selon leur profil de remplissage sur 24 h (K-means).

### 4. Livrables

- [ ] Tableau de bord Grafana **Vélos** (carte des stations colorées selon leur remplissage, courbe sur 24 h, liste des stations critiques), exporté dans `partie2_velos/grafana/velos.json`
- [ ] Partie du rapport
- [ ] Vidéo de démo

---

<a id="personne-c"></a>

## Personne C – Pollution (flux IoT, OpenAQ)

**Dossier :** `partie3_pollution/` · **Compte MinIO :** `pollution` · **Schéma PostgreSQL :** `pollution`

> ⚠️ **Priorité :** créer la clé API et lancer la collecte sur le VPS dès le jour 1.

### 1. Collecte

- [ ] Créer la clé API gratuite OpenAQ et la mettre dans `.env` (jamais sur GitHub).
- [ ] Lister les capteurs français des 8 villes pour PM2.5, PM10, NO2, O3 et CO.
- [ ] Écrire un collecteur régulier (toutes les 15 à 60 minutes) qui dépose les relevés dans `bronze/pollution/`.
- [ ] Le déployer sur le VPS dans un conteneur avec `restart: always`.
- [ ] **Lancer la collecte le plus tôt possible.**
- [ ] Récupérer aussi l'historique des dernières années via l'API.

### 2. Traitement

- [ ] Nettoyer (unités en µg/m³, doublons, valeurs impossibles) et écrire dans `silver/pollution/`.
- [ ] Produire `gold/pollution/pollution_ville_heure.parquet`, puis déposer `gold/pollution/_SUCCESS`.
- [ ] Charger la table Gold dans le schéma PostgreSQL `pollution`.

### 3. Analyse

- [ ] Répondre aux 4 questions métier :
    1. Zones les plus polluées
    2. Variation au cours de la journée
    3. Polluants dominants (analyse détaillée sur Paris)
    4. Épisodes de pollution anormale
- [ ] **IA :** détecter les épisodes anormaux et comparer aux seuils de l'OMS.

### 4. Livrables

- [ ] Tableau de bord Grafana **Pollution** (carte des capteurs, courbe par heure de la journée, alertes de dépassement), exporté dans `partie3_pollution/grafana/pollution.json`
- [ ] Partie du rapport
- [ ] Vidéo de démo

---

<a id="personne-d"></a>

## Personne D – Plateforme et analyse croisée

**Dossiers :** `infra/` et `partie4_croisee/` · **Compte MinIO :** `croise` · **Schéma PostgreSQL :** `croise`

> ⚠️ **Priorité :** la plateforme doit être en ligne dès le jour 1, car B et C en ont besoin pour lancer leur collecte.

### 1. Plateforme (jour 1)

- [ ] Sécuriser le VPS : pare-feu `ufw`, connexion SSH par clé, un compte par membre.
- [ ] Écrire `infra/docker-compose.yml` : MinIO, PostgreSQL, Grafana et Caddy (HTTPS pour Grafana uniquement).
- [ ] Créer le réseau Docker externe `urbanhub`.
- [ ] Créer les buckets `bronze`, `silver` et `gold`, et activer le versioning sur `gold`.
- [ ] Créer les 4 comptes MinIO avec leurs droits (voir [Règles MinIO](#regles-minio)).
- [ ] Créer les 4 schémas PostgreSQL et un utilisateur par personne.
- [ ] Ajouter `.env.example` dans le dépôt.

### 2. Données simulées

- [ ] Écrire un générateur de **fausses tables Gold** au format du contrat, pour travailler sans attendre les autres.
- [ ] Les charger dans les schémas `meteo`, `velos` et `pollution` tant que les vraies tables ne sont pas prêtes.

### 3. Analyse

- [ ] Créer dans le schéma `croise` les vues SQL qui joignent les 3 tables sur `ville` + `heure`.
- [ ] Calculer les corrélations et répondre aux 4 questions croisées :
    1. Relation entre météo et pollution
    2. Influence de la météo sur l'usage des vélos
    3. Conditions favorables à la mobilité douce
    4. Périodes où mobilité, pollution et météo interagissent fortement
- [ ] **IA :** construire un modèle qui prédit l'usage des vélos à partir de la météo, et un score « conditions favorables au vélo ».

### 4. Livrables

- [ ] Tableau de bord Grafana **Accueil** (carte des 8 villes et indicateurs urbains) et **Analyse croisée**, exportés dans `partie4_croisee/grafana/`
- [ ] Remplacer les fausses tables Gold par les vraies.
- [ ] Partie du rapport
- [ ] Vidéo de démo

---

[↑ Retour au sommaire](#sommaire)
