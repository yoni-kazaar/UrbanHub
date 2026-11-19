# Image Python de la partie météo.
# Le code n'est pas copié dans l'image : il est monté depuis le dépôt
# (voir docker-compose.minio-local.yml), donc une modification du code
# est prise en compte sans reconstruire l'image.
FROM python:3.12-slim

WORKDIR /app
COPY partie1_meteo/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app
