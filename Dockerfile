FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py .
COPY web web
ENV RADAR_DB=/data/radar.sqlite3
EXPOSE 8000
CMD ["sh", "-c", "test -n \"$RADAR_API_KEY\" && exec uvicorn app:app --host 0.0.0.0 --port ${PORT:-8000}"]
