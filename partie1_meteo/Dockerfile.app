# Image pour lancer l'application Streamlit de l'équipe (app/) dans Docker.
# Utile sur les PC où Smart App Control bloque pyarrow.
FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt /tmp/requirements.txt
# s3fs récent imposé : les versions plus anciennes dépendent d'un fsspec retiré de PyPI.
RUN pip install --no-cache-dir -r /tmp/requirements.txt "s3fs>=2025.9"

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app
EXPOSE 8501
