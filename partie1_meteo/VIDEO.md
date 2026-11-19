# Séquence Météo de la vidéo de présentation (≈ 4 min)

La présentation du projet se fait par une vidéo commune à toute l'équipe. Ce script décrit la
séquence de la Partie 1, à intégrer dans cette vidéo.

À préparer avant d'enregistrer :
- MinIO lancé : `docker compose -f infra/docker-compose.yml up -d minio`
- Application lancée : `docker compose -f partie1_meteo/docker-compose.yml --profile app up -d app`
- Onglets ouverts : console MinIO (http://localhost:9001, compte `urbanhub-meteo`), application (http://localhost:8501), VS Code sur `partie1_meteo/`.

| Temps | À l'écran | À dire |
| --- | --- | --- |
| 0:00 – 0:20 | Schéma d'architecture du README | « La Partie 1 traite le flux batch : 5 ans de météo horaire pour toute la France, de la source jusqu'aux indicateurs. » |
| 0:20 – 0:45 | `config.py`, commentaire sur la source | « Le sujet proposait NOAA, mais ce jeu s'arrête en août 2025. Avec l'accord du professeur, nous utilisons Météo-France, à jour chaque jour. » |
| 0:45 – 1:30 | Terminal : `telechargement.py --departements 69 75`, puis `telechargement.py` sans argument | « Le script lit le catalogue de data.gouv.fr et télécharge les fichiers en parallèle avec un ThreadPoolExecutor. Une relance ne reprend que les fichiers manquants. » Montrer le bilan : 190 fichiers, 3,3 Go. |
| 1:30 – 2:00 | Console MinIO : `bronze/meteo/year=…/`, puis `silver/meteo/`, puis `gold/meteo/` | « Bronze garde les fichiers d'origine, jamais modifiés. Silver contient le Parquet nettoyé, et Gold les tables finales. Mon compte ne peut écrire que dans les dossiers meteo. » |
| 2:00 – 2:30 | `nettoyage.py` (règles en tête du fichier) et le résultat de `pytest` | « Codes qualité, valeurs impossibles, vent calme, doublons : 77 millions de lignes gardées, et 8 tests vérifient les règles. » |
| 2:30 – 3:40 | Application, page Météo : les 4 onglets | Saisons : « l'amplitude dépend de la mer : 15 °C à Nantes, 20 °C à Lyon. » Périodes anormales : « en rouge, la vague de chaleur de juin 2026 à Paris, +9,7 °C ; les croix noires sont les jours repérés par l'IA. » Visibilité : « l'humidité est le premier facteur, la visibilité tombe de 30 à 6 km. » Extrêmes : « record de 42,8 °C à Bordeaux. » |
| 3:40 – 4:00 | Page Accueil, ou Analyse croisée | « Notre table Gold ville × heure suit le contrat commun : elle se joint directement aux vélos et à la pollution. » |

