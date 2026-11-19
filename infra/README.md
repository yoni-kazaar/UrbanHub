# Infra : MinIO

```bash
cd infra
cp .env.example .env    # remplir les mots de passe (openssl rand -hex 16)
docker compose up -d
```

- API S3 : http://localhost:9000
- Console web : http://localhost:9001 (compte `MINIO_ROOT_USER`)
- Rejouer l'init (après un changement dans `policies/`) : `docker compose run --rm minio-init`
- Tout effacer : `docker compose down -v`

Les 4 comptes (`urbanhub-meteo`, `urbanhub-velos`, `urbanhub-pollution`, `urbanhub-croise`) ont pour clé d'accès leur nom et pour secret la variable `MINIO_<NOM>_SECRET` (par exemple `MINIO_METEO_SECRET`). Les droits sont dans `policies/`, conformes à [CONTRAT.md](../CONTRAT.md).
