FROM python:3.11-slim

# Nicht als root laufen lassen.
RUN useradd --create-home --uid 1000 kiara

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY run.py .

# Alle Daten (DB, Belege, Schlüssel) landen im Volume /data.
ENV KIARA_DATA_DIR=/data
RUN mkdir -p /data && chown kiara:kiara /data
VOLUME /data

USER kiara
EXPOSE 8000

# --proxy-headers: echte Client-IPs vom Reverse-Proxy (Caddy) übernehmen,
# damit das Login-Rate-Limit pro Besucher greift statt pro Proxy.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
