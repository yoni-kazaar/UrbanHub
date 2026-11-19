# Partie 3 – Pollution (flux IoT, OpenAQ) – Personne C

## Fichiers

| Fichier | Rôle |
| --- | --- |
| `config.py` | Lit le `.env` : clé OpenAQ, accès MinIO, intervalle de collecte |
| `openaq.py` | Client API OpenAQ v3 : clé `X-API-Key`, pause pour rester sous 60 requêtes/min, nouvel essai sur 429/5xx |
| `stockage.py` | Écriture dans le Data Lake : MinIO, ou dossier local si `MINIO_ENDPOINT` est vide. Secours en local si MinIO est injoignable |
| `decouverte_capteurs.py` | Sites OpenAQ en France → rattachement aux 8 villes (`common.villes`) → capteurs PM2.5, PM10, NO2, O3, CO actifs → `etat/capteurs.json` |
| `collecteur.py` | Toutes les 15 min : dernière mesure de chaque site → un fichier brut horodaté dans `bronze/pollution/year=…/month=…/day=…/` |
| `Dockerfile`, `docker-compose.yml` | Collecteur en conteneur avec `restart: always` (+ MinIO local optionnel) |

## Démarrage

1. Copier `.env.example` en `.env` à la racine du dépôt et remplir `OPENAQ_API_KEY`.
2. Depuis `partie3_pollution/` :

```bash
# Test d'un seul passage
docker compose run --rm collecteur-pollution python -m partie3_pollution.collecteur --une-fois

# Collecte en continu (dossier local si MINIO_ENDPOINT est vide)
docker compose up -d --build

# Collecte en continu avec un MinIO local (MINIO_ENDPOINT=minio-local:9000 dans .env)
docker compose --profile local up -d --build

# Suivre la collecte
docker compose logs -f collecteur-pollution
```

Console du MinIO local : http://localhost:9011 (minioadmin / minioadmin123).

## Passage sur le VPS

Remplacer dans `.env` : `MINIO_ENDPOINT` (adresse HTTPS donnée par D), `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY` (compte `pollution`), puis relancer.
Les fichiers déjà collectés en local se recopient sur le VPS avec `mc mirror` (Bronze n'est jamais modifié, donc rien ne se perd).

## Notes

- Bronze garde les réponses **telles que reçues**, unités d'origine comprises (OpenAQ renvoie parfois O3/NO2 en ppb et CO en ppm). La conversion en µg/m³ se fait à l'étape Silver.
- Coût en requêtes : 1 requête par site et par passage. Avec ~100 sites toutes les 15 min, ~400 requêtes/heure, sous la limite gratuite de 2 000/heure.
