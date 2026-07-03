FROM python:3.11-slim

WORKDIR /app

# ffmpeg за аудио декодиране
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Предзаредете модела при build (за да не чака потребителят при стартиране)
RUN python -c "from faster_whisper import WhisperModel; WhisperModel('small', device='cpu', compute_type='int8')"

COPY app.py index.html manifest.json sw.js ./
COPY icons ./icons
COPY .well-known ./.well-known

EXPOSE 7979
CMD ["python", "app.py"]
