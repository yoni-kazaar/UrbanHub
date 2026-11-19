# UrbanHub – Tâches par personne

Chaque personne mène sa partie de bout en bout, sans attendre les autres. Le seul lien entre les parties est le [contrat commun](CONTRAT.md).

## Sommaire

1. [Vue d'ensemble](#vue-densemble)
2. [Architecture](#architecture)
3. [Se connecter à MinIO](#se-connecter)
4. [Règles MinIO](#regles-minio)
5. [Jalons](#jalons)
6. [Personne A – Météo (flux batch)](#personne-a)
7. [Personne B – Vélos (flux streaming)](#personne-b)
8. [Personne C – Pollution (flux IoT)](#personne-c)
9. [Personne D – Plateforme et analyse croisée](#personne-d)

---

<a id="vue-densemble"></a>

## Vue d'ensemble

| Personne | Partie | Source | Table Gold | Page Streamlit |
| :---: | --- | --- | --- | --- |
| **A** | Météo – batch | Météo-France (horaire) | `gold/meteo/meteo_ville_heure.parquet` | `1_Meteo.py` |
| **B** | Vélos – streaming | API CityBikes | `gold/velos/velos_ville_heure.parquet` | `2_Velos.py` |
| **C** | Pollution – IoT | API OpenAQ | `gold/pollution/pollution_ville_heure.parquet` | `3_Pollution.py` |
| **D** | Plateforme et analyse croisée | Les 3 tables Gold | – | `Accueil.py`, `4_Croisee.py` |

> **À faire par tout le monde le jour 1 :** relire et valider [CONTRAT.md](CONTRAT.md), récupérer son compte MinIO (URL + secret, fournis par D), le mettre dans son `.env`, puis travailler uniquement dans son propre dossier.

---

<a id="architecture"></a>

## Architecture

```
Sources (Météo-France, CityBikes, OpenAQ)
      │  ingestion : scripts Python (collecteurs pour B et C)
      ▼
MinIO – Data Lake         bronze → silver → gold (Parquet)
      │  lecture des 3 tables Gold
      ▼
Streamlit – indicateurs urbains   une page par partie
```

- **MinIO** tourne sur le VPS Hetzner de D, déployé avec **Coolify** à partir de `infra/docker-compose.yml`. Coolify fournit l'adresse HTTPS (certificat automatique).
- Les autres s'y connectent avec leur compte MinIO par HTTPS : **personne d'autre que D n'a d'accès SSH au VPS ni à Coolify**.
- L'image utilisée est `pgsty/minio` (SILO), un fork communautaire de MinIO qui garde la console web : l'image officielle `minio/minio` n'est plus distribuée.
- **GitHub** contient le code uniquement, jamais les données ni les secrets.
- Les collecteurs de B et C tournent sur une machine allumée en continu (la leur, ou le VPS : D les déploie dans Coolify à leur demande) avec `restart: always` s'ils sont dans Docker.

```
UrbanHub/
├── CONTRAT.md
├── Personne.md
├── .env.example                # variables de chaque personne
├── requirements.txt
├── infra/                      # D : MinIO (docker-compose.yml, init.sh, policies/, .env.example)
├── common/                     # villes, accès MinIO, schémas Gold, fausses tables
├── partie1_meteo/              # A
├── partie2_velos/              # B
├── partie3_pollution/          # C
├── partie4_croisee/            # D
└── app/                        # Streamlit : Accueil.py (D) et pages/ (une par personne)
```

**Lancer son code** (depuis la racine du dépôt, avec `PYTHONPATH=.`) :

```bash
python -m partie2_velos.collecte      # exemple : collecteur de B
streamlit run app/Accueil.py          # interface
```

---

<a id="se-connecter"></a>

## Se connecter à MinIO

1. Copier `.env.example` en `.env` à la racine du dépôt (il est ignoré par git).
2. Le remplir avec les valeurs transmises par D (jamais par GitHub) :

```
MINIO_ENDPOINT=https://<adresse fournie par D>      # sans numéro de port
MINIO_ACCESS_KEY=urbanhub-meteo                     # ton compte
MINIO_SECRET_KEY=<ton secret>
```

3. Vérifier que le serveur répond : `curl -I <MINIO_ENDPOINT>/minio/health/live` doit renvoyer `200`.

À la racine de l'adresse, MinIO répond par une erreur XML `AccessDenied` : c'est normal, c'est une API et non une page web.

**Console web (voir ses fichiers) :** réservée à D (compte administrateur), via un tunnel SSH :

```bash
ssh -L 9001:localhost:9001 hetzner     # puis ouvrir http://localhost:9001
```

Les autres peuvent lister et lire leurs fichiers avec leur compte dans le code, ou demander à D.

---

<a id="regles-minio"></a>

## Règles MinIO

### Un compte par personne

| Compte | Peut écrire dans | Peut lire |
| --- | --- | --- |
| `urbanhub-meteo` (A) | `bronze/meteo/`, `silver/meteo/`, `gold/meteo/` | `gold/` |
| `urbanhub-velos` (B) | `bronze/velos/`, `silver/velos/`, `gold/velos/` | `gold/` |
| `urbanhub-pollution` (C) | `bronze/pollution/`, `silver/pollution/`, `gold/pollution/` | `gold/` |
| `urbanhub-croise` (D) | `gold/croise/` | tout |

Personne ne peut écraser les données d'un autre, ni supprimer un fichier. Seul D connaît le compte administrateur.

### Règles d'écriture

- **Bronze ne se modifie jamais** : chaque relevé est un nouveau fichier horodaté (`velos_20261119T140000Z.json`).
- **Silver et Gold** peuvent être réécrits, uniquement par leur propriétaire.
- **Table Gold prête** : son propriétaire dépose un fichier vide `gold/<source>/_SUCCESS`.
- **Versioning activé** sur le bucket `gold`, pour pouvoir revenir en arrière.
- **Toujours écrire dans son dossier** : un fichier envoyé à la racine d'un bucket (par exemple `bronze/photo.png`) n'est visible d'aucun compte sauf `urbanhub-croise` en lecture.
- **Développement** : tester d'abord sur un MinIO local (`infra/README.md`), puis basculer sur le VPS en changeant `MINIO_ENDPOINT` dans `.env`.

---

<a id="jalons"></a>

## Jalons

À fixer ensemble le jour 1 (le premier à compléter) :

| Jalon | Date |
| --- | --- |
| Contrat validé, comptes MinIO distribués, collectes B et C lancées | |
| Premier fichier Gold (même partiel) déposé par A, B et C | |
| **Gel de la collecte** (au moins 1 à 2 semaines avant le rendu, pour que D ait de quoi entraîner son modèle) | |
| Analyses et pages Streamlit terminées | |
| Rapport assemblé et relu | |
| Vidéos de démo | |

---

<a id="personne-a"></a>

## Personne A – Météo (flux batch, Météo-France)

**Dossier :** `partie1_meteo/` · **Compte MinIO :** `urbanhub-meteo`

> ℹ️ **Source :** [données climatologiques de base horaires de Météo-France](https://www.data.gouv.fr/fr/datasets/donnees-climatologiques-de-base-horaires/), à la place de NOAA Global Hourly (arrêté le 24/08/2025), avec l'accord du professeur. Volume : environ 3,5 Go compressés pour la métropole.

### 1. Collecte

- [x] Écrire un script qui télécharge **en parallèle** les fichiers départementaux des 5 dernières années et les dépose dans `bronze/meteo/`.
- [x] Construire la liste des stations françaises et les rattacher aux 8 villes.
- [ ] Relancer le téléchargement juste avant le gel de la collecte, pour avoir les derniers jours.

### 2. Traitement

- [ ] Filtrer selon les codes qualité Météo-France, gérer les valeurs manquantes et convertir `AAAAMMJJHH` en `timestamp` UTC (température, vent, pression, visibilité, précipitations).
- [ ] Nettoyer (valeurs manquantes, unités, heure en UTC) et écrire dans `silver/meteo/` en gardant **toutes** les stations françaises (avec `latitude` et `longitude`).
- [ ] Rattacher chaque station à sa ville (`common.villes.rattacher_ville`), puis produire `gold/meteo/meteo_ville_heure.parquet` et déposer `gold/meteo/_SUCCESS`.

### 3. Analyse

- [ ] Répondre aux 4 questions métier :
  1. Périodes météorologiques anormales
  2. Lien entre météo et visibilité
  3. Évolution saisonnière de la température, en France et dans les 8 villes
  4. Jours extrêmes
- [ ] **IA :** détecter les anomalies (Isolation Forest ou z-score).

### 4. Livrables

- [ ] Page Streamlit `app/pages/1_Meteo.py` (courbes saisonnières, carte des stations, jours extrêmes)
- [ ] Partie du rapport
- [ ] Vidéo de démo

---

<a id="personne-b"></a>

## Personne B – Vélos (flux streaming, CityBikes)

**Dossier :** `partie2_velos/` · **Compte MinIO :** `urbanhub-velos`

> ⚠️ **Priorité absolue :** la collecte doit démarrer dès le jour 1 et tourner sans interruption, sinon il n'y aura pas assez de données.

### 1. Collecte

- [ ] Jour 1 : trouver une machine allumée en permanence (PC fixe, ou le VPS : D déploie le collecteur dans Coolify).
- [ ] Trouver l'identifiant du réseau de chacune des 8 villes dans l'API.
- [ ] Écrire un collecteur qui tourne toutes les 2 à 3 minutes et dépose les relevés dans `bronze/velos/`. Une erreur sur un réseau ne doit pas arrêter la boucle.
- [ ] Le lancer dans un conteneur Docker avec `restart: always`.
- [ ] **Lancer la collecte le plus tôt possible**, puis vérifier chaque jour qu'elle tourne (`docker compose logs`).

### 2. Traitement

- [ ] Nettoyer et dédoublonner, puis écrire dans `silver/velos/` (une ligne par station et par relevé, avec `latitude` et `longitude`).
- [ ] Calculer le taux d'occupation et produire `gold/velos/velos_ville_heure.parquet`, puis déposer `gold/velos/_SUCCESS`.

### 3. Analyse

Les analyses par station et par zone se font sur Silver, car Gold est agrégé par ville.

- [ ] Répondre aux 5 questions métier :
  1. Stations les plus utilisées
  2. Zones où l'offre de vélos est insuffisante
  3. Pics d'utilisation journaliers
  4. Déséquilibres géographiques
  5. Stations critiques à rééquilibrer
- [ ] **IA :** regrouper les stations selon leur profil de remplissage sur 24 h (K-means).

### 4. Livrables

- [ ] Page Streamlit `app/pages/2_Velos.py` (carte des stations colorées selon leur remplissage, courbe sur 24 h, liste des stations critiques)
- [ ] Partie du rapport
- [ ] Vidéo de démo

---

<a id="personne-c"></a>

## Personne C – Pollution (flux IoT, OpenAQ)

**Dossier :** `partie3_pollution/` · **Compte MinIO :** `urbanhub-pollution`

> ⚠️ **Priorité :** créer la clé API et lancer la collecte dès le jour 1.

### 1. Collecte

- [ ] Créer la clé API gratuite OpenAQ et la mettre dans `.env` (jamais sur GitHub).
- [ ] Récupérer **d'abord l'historique** des dernières années via l'API : c'est lui qui rend la Partie 4 exploitable.
- [ ] Lister les capteurs français des 8 villes pour PM2.5, PM10, NO2, O3 et CO.
- [ ] Écrire un collecteur régulier (toutes les 15 à 60 minutes) qui dépose les relevés dans `bronze/pollution/`.
- [ ] Le lancer sur une machine allumée en continu, dans un conteneur avec `restart: always`.
- [ ] **Lancer la collecte le plus tôt possible.**

### 2. Traitement

- [ ] Nettoyer (unités en µg/m³, doublons, valeurs impossibles) et écrire dans `silver/pollution/`. Attention : OpenAQ donne souvent le CO en ppm, il faut le convertir.
- [ ] Produire `gold/pollution/pollution_ville_heure.parquet` (valeurs absentes laissées vides, jamais 0), puis déposer `gold/pollution/_SUCCESS`.

### 3. Analyse

- [ ] Répondre aux 4 questions métier :
  1. Zones les plus polluées
  2. Variation au cours de la journée
  3. Polluants dominants (analyse détaillée sur Paris)
  4. Épisodes de pollution anormale
- [ ] **IA :** détecter les épisodes anormaux et comparer aux seuils de l'OMS.

### 4. Livrables

- [ ] Page Streamlit `app/pages/3_Pollution.py` (carte des capteurs, courbe par heure de la journée, dépassements de seuils)
- [ ] Partie du rapport
- [ ] Vidéo de démo

---

<a id="personne-d"></a>

## Personne D – Plateforme et analyse croisée

**Dossiers :** `infra/`, `common/`, `partie4_croisee/` et `app/` · **Compte MinIO :** `urbanhub-croise`

> ⚠️ **Priorité :** MinIO doit être en ligne dès le jour 1, car B et C en ont besoin pour lancer leur collecte.

### 1. Plateforme (jour 1)

- [x] Écrire `infra/docker-compose.yml` (MinIO + init), `infra/init.sh` et `infra/policies/` (droits par compte).
- [x] Déployer MinIO sur le VPS avec Coolify (adresse HTTPS automatique, buckets `bronze`, `silver`, `gold`, versioning sur `gold`, 4 comptes créés par l'init).
- [x] Ajouter `.env.example`, `infra/.env.example` et `requirements.txt` dans le dépôt.
- [x] Mettre `restart: "no"` sur `minio-init` pour que Coolify ne le relance pas en boucle.
- [x] Transmettre à chacun l'adresse de MinIO et **son seul secret** (jamais par GitHub).
- [ ] Déployer à la demande les collecteurs de B et C dans Coolify, s'ils n'ont pas de machine allumée.

### 2. Code commun et données simulées

- [x] Écrire `common/` : `villes.py` (les 8 villes et leurs centres), `lake.py` (accès MinIO), `schemas.py` (format des 3 tables Gold et validation).
- [x] Écrire `common/fake_gold.py` : un générateur de **fausses tables Gold** au format du contrat, pour travailler et tester l'interface sans attendre les autres.
- [ ] Faire relire `common/` par au moins un autre membre.

### 3. Analyse

- [ ] Joindre les 3 tables Gold sur `ville` + `heure` (période commune), puis calculer les corrélations.
- [ ] Répondre aux 4 questions croisées :
  1. Relation entre météo et pollution
  2. Influence de la météo sur l'usage des vélos
  3. Conditions favorables à la mobilité douce
  4. Périodes où mobilité, pollution et météo interagissent fortement
- [ ] **IA :** construire un modèle qui prédit l'usage des vélos à partir de la météo (validation sur la période la plus récente, pas aléatoire), et un score « conditions favorables au vélo ».

### 4. Livrables

- [ ] Page d'accueil `app/Accueil.py` (carte des 8 villes et indicateurs urbains) et page `app/pages/4_Croisee.py`
- [ ] Remplacer les fausses tables Gold par les vraies.
- [ ] Partie du rapport
- [ ] Vidéo de démo

---

[↑ Retour au sommaire](#sommaire)
