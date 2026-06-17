FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY collector.py .

# DB lives in a mounted volume so data survives container recreation.
ENV DB_PATH=/data/olhovivo.sqlite3
VOLUME /data

CMD ["python", "-u", "collector.py"]
