# Partie 3 : pollution de l'air (OpenAQ, personne C)

## Comment ça marche

```
OpenAQ ──> collecteur (toutes les 15 min) ──┐
       ──> historique (12 derniers mois) ───┴──> bronze/pollution/   JSON brut
                                                     │
                                pipeline (toutes les heures)
                                                     ▼
                                                silver/pollution/    mesures nettoyées (Parquet)
                                                     ▼
                                                gold/pollution/pollution_ville_heure.parquet + _SUCCESS
```

- **Collecteur** : récupère la dernière mesure de chaque capteur des 8 villes (PM2.5, PM10, NO2, O3, CO).
- **Historique** : télécharge une fois les 12 derniers mois. S'il s'arrête, on le relance et il reprend où il en était.
- **Pipeline** : nettoie les nouvelles données (unités en µg/m³, valeurs impossibles ou périmées, doublons) puis calcule la moyenne par ville et par heure (format du [contrat](../CONTRAT.md)).

## Lancer

1. Copier `.env.example` (racine du dépôt) en `.env` et remplir `OPENAQ_API_KEY` et `MINIO_*`.
2. Depuis `partie3_pollution/` :

```bash
docker compose up -d --build                     # collecteur + pipeline, en continu
docker compose run -d --name historique-pollution collecteur-pollution python -m partie3_pollution.historique
```

Suivre :

```bash
docker compose logs --tail 5 collecteur-pollution
docker compose logs --tail 20 pipeline-pollution
docker logs --tail 5 historique-pollution
```

Forcer une mise à jour de Gold tout de suite :

```bash
docker compose run --rm collecteur-pollution python -m partie3_pollution.pipeline
```

## Problèmes et solutions

| Problème | Solution |
| --- | --- |
| `no configuration file provided` | Mauvais dossier : `cd partie3_pollution` |
| `.env not found` | `copy ..\.env.example ..\.env` puis le remplir |
| `No module named 'pandas'` | `requirements.txt` pas enregistré : Ctrl + S, puis `docker compose build --no-cache` |
| `HTTP 429` ou `HTTP 500` dans les logs | Normal : l'API demande de ralentir ou bugge un instant, le script réessaie tout seul |
| `[MinIO indisponible]` | MinIO est arrêté : les données sont gardées en local et renvoyées au prochain passage du pipeline. Relancer MinIO (`docker compose up -d` dans `infra/`) |
| L'historique s'est arrêté (PC éteint) | `docker rm historique-pollution` puis relancer sa commande : il reprend où il en était |
| `Terminé avec N erreurs` (historique) | Relancer la commande : seules les tranches manquantes sont retéléchargées |
| `AccessDenied` en lecture | Le compte n'a pas le droit de lire `bronze/pollution` ou `silver/pollution` : demander à D d'ajouter les droits de lecture |
| Données fausses dans Gold, ou règle de nettoyage modifiée | Tout refaire : `docker compose stop pipeline-pollution`, supprimer le dossier `pollution` du bucket `silver` dans la console MinIO, puis `docker compose run --rm collecteur-pollution python -m partie3_pollution.silver --complet`, `... .gold`, et `docker compose up -d` |
| La console MinIO affiche peu d'objets | Les compteurs se mettent à jour avec du retard : ouvrir le bucket pour voir les vrais fichiers |