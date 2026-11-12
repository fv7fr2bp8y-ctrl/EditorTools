FROM python:3.11-slim

WORKDIR /app

# ffmpeg за аудио декодиране
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Предзаредете модела при build (за да не чака потребителят при стартиране)
RUN python -c "from faster_whisper import WhisperModel; WhisperModel('small', device='cpu', compute_type='int8')"

COPY app.py persist.py pro.py index.html manifest.json sw.js privacy.html ./
COPY icons ./icons
COPY .well-known ./.well-known

# Hugging Face Spaces маршрутизира към този порт; DATA_DIR е записваем в контейнера
ENV PORT=7860
ENV DATA_DIR=/data
RUN mkdir -p /data && chmod 777 /data

EXPOSE 7860
CMD ["python", "app.py"]
