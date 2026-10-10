FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
COPY requirements.txt requirements-vps.txt ./
RUN pip install --no-cache-dir -r requirements-vps.txt
COPY . .
RUN mkdir -p data && chmod +x entrypoint.sh
CMD ["sh", "/app/entrypoint.sh"]
