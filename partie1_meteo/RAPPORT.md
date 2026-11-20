# Partie 1 : analyse météorologique urbaine (flux batch)

*Section du rapport UrbanHub rédigée par la personne A. Chiffres calculés le 20/11/2026 sur la période du 01/01/2022 au 20/11/2026.*

## 1. Source de données

Le sujet indique le jeu **NOAA Global Hourly** (ISD). Lors de la collecte, nous avons constaté que ce jeu **n'est plus publié depuis le 24/08/2025** : aucun fichier 2026 n'existe, alors que les Parties 2 et 3 collectent en novembre 2026. Son successeur, NOAA GHCNh, ne contient aucune donnée 2026 pour Lyon, Lille et Strasbourg.

Avec l'accord du professeur, la Partie 1 utilise donc les **[données climatologiques de base horaires de Météo-France](https://www.data.gouv.fr/fr/datasets/donnees-climatologiques-de-base-horaires/)** (Licence Ouverte) :

- un fichier CSV compressé par département et par période (2020-2024 et 2025-2026) ;
- mis à jour chaque jour : la dernière mesure utilisée date du 20/11/2026 à 05 h UTC ;
- les 8 variables demandées sont présentes, déjà dans les bonnes unités, avec un code qualité par mesure.

| Variable du sujet | Colonne Météo-France | Unité |
| --- | --- | --- |
| `station_id` | `NUM_POSTE` | - |
| `timestamp` | `AAAAMMJJHH` | heure UTC |
| `temperature` | `T` | °C |
| `wind_speed` | `FF` (vent moyen 10 min) | m/s |
| `wind_direction` | `DD` | degrés |
| `visibility` | `VV` | m |
| `pressure` | `PMER` (niveau de la mer) | hPa |
| `precipitation` | `RR1` (cumul sur 1 h) | mm |

Nous avons aussi gardé `TN`, `TX` (min et max de l'heure), `TD` (point de rosée), `U` (humidité) et `FXI` (rafales), utiles pour la visibilité et les extrêmes.

## 2. Architecture du flux

```
data.gouv.fr (Météo-France)
   │  telechargement.py : 190 fichiers en parallèle (ThreadPoolExecutor)
   ▼
bronze/meteo/   fichiers d'origine, jamais modifiés (3,3 Go)
   │  stations.py + nettoyage.py : 95 départements en parallèle (ProcessPoolExecutor)
   ▼
silver/meteo/   Parquet nettoyé, 1 ligne par station et par heure (504 Mo, 77,5 M lignes)
   │  gold.py : moyennes par ville et par heure
   ▼
gold/meteo/     table du contrat + tables d'analyse
   │  analyses.py : 4 questions métier + IA
   ▼
app/pages/1_Meteo.py (Streamlit)
```

| Étape | Résultat | Durée |
| --- | --- | --- |
| Téléchargement | 95 départements, 190 fichiers, 3,3 Go | 19 min (8 en parallèle) |
| Stations | 2 099 stations actives depuis 2022, dont 81 dans les 8 villes | 2 min |
| Nettoyage | 77,5 millions de lignes, 1 996 stations, 5 605 fichiers Parquet | 8,1 min |
| Gold | 342 574 lignes ville × heure, 100 % des heures couvertes pour chaque ville | 5 min |

Chaque ville est la **moyenne de ses stations à moins de 30 km** de son centre (règle du contrat) : de 3 stations à Lille à 24 à Paris. La direction du vent est moyennée **vectoriellement** (la moyenne de 350° et 10° vaut 0°, pas 180°).

## 3. Nettoyage

| Règle | Lignes ou valeurs concernées |
| --- | ---: |
| Lignes lues | 106 375 776 |
| Hors période (avant 2022) | 28 740 069 |
| Lignes sans aucune mesure | 119 862 |
| Doublons (même station, même heure) | 0 |
| **Lignes gardées** | **77 515 845** |
| Valeurs au code qualité « douteuse » (2), vidées | 52 |
| Valeurs physiquement impossibles, vidées | 3 |
| Directions de vent par vent calme, vidées | 1 424 679 |

Les données Météo-France sont déjà contrôlées avant publication : moins d'une valeur sur un million est rejetée. La correction la plus fréquente concerne le **vent calme** : une direction de 0° par vent nul aurait été comptée comme un vent du nord. Les valeurs absentes restent vides, jamais remplacées par 0. Huit tests automatiques vérifient ces règles (`tests/test_nettoyage.py`).

## 4. Questions métier

### Q1. Peut-on identifier des périodes météorologiques anormales ?

**Oui.** Chaque jour est comparé à la **normale** du même jour de l'année (moyenne 2022-2026, lissée sur ±7 jours). Une période anormale correspond à au moins 3 jours consécutifs à plus de 2 écarts-types de cette normale.

À l'échelle de la France, **7 périodes** ressortent :

| Période | Type | Écart moyen à la normale |
| --- | --- | ---: |
| 01-03/04/2022 | froid | -7,7 °C |
| 26-28/02/2023 | froid | -5,6 °C |
| 04-07/08/2023 | froid | -6,0 °C |
| 21-24/04/2024 | froid | -5,9 °C |
| 14-16/03/2025 | froid | -5,2 °C |
| 25-28/05/2026 | chaud | +6,7 °C |
| 22-25/06/2026 | chaud | +6,5 °C |

Les vagues de froid tardives au printemps dominent (avril 2022, avril 2024), et 2026 concentre les deux épisodes chauds. La période la plus marquée localement est à **Paris, du 24 au 26/06/2026 : 32,1 °C en moyenne, soit +9,7 °C** au-dessus de la normale.

**Détection d'anomalies par IA (Isolation Forest).** Un modèle non supervisé, entraîné ville par ville sur 7 variables journalières (écart de température à la normale, amplitude, pluie, rafales, pression minimale, visibilité minimale, humidité), isole les 1 % de jours les plus atypiques : **144 jours**. La température est prise en écart à la normale, sinon tous les jours d'été et d'hiver seraient jugés anormaux. Les jours repérés sont surtout liés à la **pluie (83)** et aux **rafales (30)**, par exemple le 12/11/2026 à Marseille (76 mm) et le 21/11/2024 à Nantes (rafales de 31 m/s).

*Limite :* la normale est calculée sur les 5 ans étudiés, et non sur 30 ans comme les normales climatiques officielles. Elle inclut donc elle-même les années chaudes récentes.

### Q2. Existe-t-il une corrélation entre conditions météorologiques et visibilité ?

**Oui, surtout avec l'humidité.** Corrélations de Spearman avec la visibilité (toutes villes, données horaires) :

| Variable | Corrélation |
| --- | ---: |
| Humidité | -0,45 |
| Écart température - point de rosée | +0,44 |
| Température | +0,29 |
| Pluie | -0,20 |
| Vent | +0,14 |
| Pression | -0,11 |

La visibilité médiane passe de **30 km sous 60 % d'humidité à 5,9 km au-delà de 95 %**. Elle passe de 26 km par temps sec à 6,5 km sous une pluie forte (> 4 mm/h). L'air proche de la saturation (température proche du point de rosée) est la première cause de baisse de visibilité, devant la pluie. Le vent l'améliore légèrement en dispersant le brouillard.

Le **brouillard** (visibilité < 1 km) est le plus fréquent en **décembre** et vers **6 h du matin**. Bordeaux est la ville la plus touchée (5,3 % des heures), Marseille la moins touchée (0,4 %).

### Q3. Quelle est l'évolution saisonnière de la température ?

| Zone | Mois le plus chaud | Mois le plus froid | Écart été - hiver |
| --- | --- | --- | ---: |
| France | août (21,1 °C) | janvier (4,0 °C) | 17,1 °C |
| Marseille | juillet (26,0 °C) | janvier (7,3 °C) | 18,7 °C |
| Toulouse | août (24,4 °C) | janvier (5,7 °C) | 18,7 °C |
| Lyon | août (23,7 °C) | janvier (3,9 °C) | 19,7 °C |
| Bordeaux | août (23,1 °C) | janvier (6,5 °C) | 16,6 °C |
| Strasbourg | août (21,7 °C) | janvier (3,2 °C) | 18,6 °C |
| Paris | juillet (21,5 °C) | janvier (5,0 °C) | 16,5 °C |
| Nantes | juillet (21,1 °C) | janvier (6,3 °C) | 14,9 °C |
| Lille | août (20,2 °C) | janvier (4,4 °C) | 15,8 °C |

Le cycle saisonnier est le même partout (maximum en juillet-août, minimum en janvier), mais son **amplitude dépend de la distance à la mer** : 14,9 °C à Nantes (océanique) contre 19,7 °C à Lyon et 18,6 °C à Strasbourg (continentales). Marseille est la ville la plus chaude toute l'année. La température moyenne annuelle de la France vaut 12,6 °C (2022), 12,4 °C (2023), 12,0 °C (2024) et 12,2 °C (2025). Cinq ans sont trop courts pour en tirer une tendance climatique.

### Q4. Quels sont les jours présentant des conditions météorologiques extrêmes ?

Deux types de seuils sont combinés : des **seuils absolus**, les mêmes partout, et des **seuils relatifs** propres à chaque ville (le 1 % des jours les plus extrêmes). Nombre de jours concernés entre 2022 et 2026 :

| Ville | ≥ 35 °C | ≤ -5 °C | Pluie ≥ 30 mm | Rafales ≥ 100 km/h | Brouillard < 200 m |
| --- | ---: | ---: | ---: | ---: | ---: |
| Toulouse | 101 | 6 | 5 | 2 | 56 |
| Bordeaux | 77 | 2 | 7 | 3 | 187 |
| Marseille | 77 | 0 | 25 | 0 | 30 |
| Lyon | 69 | 10 | 5 | 1 | 54 |
| Nantes | 35 | 5 | 3 | 2 | 97 |
| Paris | 32 | 2 | 3 | 0 | 9 |
| Strasbourg | 27 | 24 | 2 | 1 | 124 |
| Lille | 11 | 9 | 1 | 9 | 128 |

**Records de la période :**
- chaleur : **42,8 °C à Bordeaux le 23/06/2026** ;
- froid : **-11,4 °C à Strasbourg le 17/12/2022** ;
- pluie : **102 mm à Marseille le 20/10/2026** ;
- rafales : **36,2 m/s (130 km/h) à Lille le 18/02/2022**.

Les risques sont très géographiques. La chaleur touche le Sud-Ouest et le Sud-Est, et les fortes pluies la Méditerranée (épisodes méditerranéens d'automne). Le gel concerne surtout Strasbourg, le vent fort Lille et le brouillard Bordeaux. Les jours qui cumulent le plus de critères mêlent souvent vent et pluie, par exemple le 09/01/2026 à Lille (rafales de 28 m/s et 21 mm de pluie).

## 5. Interface

La page **Météo** de l'application Streamlit (`app/pages/1_Meteo.py`) présente une réponse par onglet :

- **Saisons :** courbes mensuelles, profil saisonnier, carte de chaleur mois × année ;
- **Périodes anormales :** écart à la normale jour par jour, périodes surlignées, jours repérés par l'IA ;
- **Visibilité :** corrélations, visibilité par classe d'humidité et de pluie, carte du brouillard mois × heure ;
- **Jours extrêmes :** décompte par ville, calendrier, top 10 ;
- **Stations :** carte des 1 996 stations.

Elle se filtre par ville et par période, et lit uniquement les tables Gold.

## 6. Limites

- **Source modifiée par rapport au sujet** (NOAA -> Météo-France), pour une raison de disponibilité des données.
- **Normales calculées sur 5 ans :** elles sont moins robustes que des normales officielles sur 30 ans.
- **Une ville est la moyenne de ses stations,** qui n'ont pas toutes les mêmes capteurs : la visibilité et la pression ne sont mesurées que dans les grandes stations.
- **Seuils d'extrêmes choisis par nos soins** (35 °C, -5 °C, 30 mm, 100 km/h, 200 m). Ce ne sont pas les seuils de vigilance officiels de Météo-France.
