FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# Base SQLite et photos envoyées. À monter sur un disque persistant :
# sans cela, tout l'historique disparaît au redéploiement.
ENV VAR_DIR=/data
VOLUME ["/data"]

# Les hébergeurs imposent souvent leur port via la variable PORT.
ENV PORT=8000
EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
