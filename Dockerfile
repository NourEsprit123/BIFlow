FROM python:3.10-slim

WORKDIR /app

# Installation des dépendances légères
RUN pip install --no-cache-dir pandas ollama

# Copie des scripts et du dossier sandbox
COPY . /app

CMD ["python", "demo_bi_analyst_sandbox.py"]