# Collecteur pollution (Partie 3). Contexte de build = racine du dépôt (UrbanHub/)
FROM python:3.12-slim
WORKDIR /app
COPY partie3_pollution/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
COPY common/ common/
COPY partie3_pollution/ partie3_pollution/
CMD ["python", "-u", "-m", "partie3_pollution.collecteur"]
