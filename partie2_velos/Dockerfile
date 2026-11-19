FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir pandas pyarrow s3fs python-dotenv
COPY common ./common
COPY partie2_velos ./partie2_velos
ENV PYTHONPATH=/app PYTHONUNBUFFERED=1
CMD ["python", "-m", "partie2_velos.collecte"]
