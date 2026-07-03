import os
import json
import base64
import struct
import asyncio
import tempfile
import threading
import re
from datetime import date
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse, FileResponse, Response
from fastapi.staticfiles import StaticFiles
import uvicorn

app = FastAPI()

DAILY_TRANSCRIBE_LIMIT = 5
DAILY_TTS_LIMIT = 10
QUOTA_FILE = Path(__file__).parent / "quota.json"
quota_lock = threading.Lock()


def get_client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def load_quota() -> dict:
    if QUOTA_FILE.exists():
        try:
            return json.loads(QUOTA_FILE.read_text())
        except Exception:
            return {}
    return {}


def save_quota(data: dict):
    try:
        QUOTA_FILE.write_text(json.dumps(data))
    except Exception:
        pass


def check_and_increment(ip: str, kind: str, limit: int):
    today = date.today().isoformat()
    with quota_lock:
        data = load_quota()
        entry = data.get(ip)
        if not entry or entry.get("date") != today:
            entry = {"date": today, "transcribe": 0, "tts": 0}
        used = entry.get(kind, 0)
        if used >= limit:
            raise HTTPException(
                429,
                f"Дневният лимит от {limit} заявки е достигнат за днес. Опитай пак утре.",
            )
        entry[kind] = used + 1
        data[ip] = entry
        save_quota(data)

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
TTS_MODEL = "gemini-2.5-flash-preview-tts"
TTS_VOICE = "Schedar"
TTS_VOICES = {
    "Schedar", "Algenib", "Charon", "Iapetus", "Sadaltager",
    "Aoede", "Kore", "Leda", "Vindemiatrix", "Despina",
}
tts_cache: dict[str, bytes] = {}

MODELS = ["tiny", "base", "small", "medium", "large-v2", "large-v3"]
LANGUAGES = {
    "Автоматично": None,
    "Български (bg)": "bg",
    "English (en)": "en",
    "Deutsch (de)": "de",
    "Français (fr)": "fr",
    "Español (es)": "es",
    "Italiano (it)": "it",
    "Русский (ru)": "ru",
    "Português (pt)": "pt",
}

# Active transcription jobs: job_id -> {"segments": [], "done": bool, "error": str|None, "info": dict}
jobs: dict[str, dict] = {}


def fmt_time_srt(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def to_srt(segments: list) -> str:
    lines = []
    for i, seg in enumerate(segments, 1):
        lines.append(str(i))
        lines.append(f"{fmt_time_srt(seg['start'])} --> {fmt_time_srt(seg['end'])}")
        lines.append(seg["text"].strip())
        lines.append("")
    return "\n".join(lines)


def to_plain(segments: list) -> str:
    return "\n".join(seg["text"].strip() for seg in segments)


def run_transcription(job_id: str, audio_path: str, model_name: str, language: str | None, word_ts: bool):
    try:
        from faster_whisper import WhisperModel
        model = WhisperModel(model_name, device="cpu", compute_type="int8")
        segments_gen, info = model.transcribe(
            audio_path,
            language=language,
            word_timestamps=word_ts,
            vad_filter=True,
            condition_on_previous_text=True,
        )
        jobs[job_id]["info"] = {
            "language": info.language,
            "language_probability": round(info.language_probability, 3),
            "duration": round(info.duration, 1),
        }
        for seg in segments_gen:
            segment_data = {
                "start": round(seg.start, 3),
                "end": round(seg.end, 3),
                "text": seg.text,
            }
            if word_ts and seg.words:
                segment_data["words"] = [
                    {"start": round(w.start, 3), "end": round(w.end, 3), "word": w.word}
                    for w in seg.words
                ]
            jobs[job_id]["segments"].append(segment_data)
    except Exception as e:
        jobs[job_id]["error"] = str(e)
    finally:
        jobs[job_id]["done"] = True
        # clean up temp file
        try:
            os.unlink(audio_path)
        except Exception:
            pass


MAX_FILE_MB = 500

@app.post("/transcribe")
async def transcribe(
    request: Request,
    file: UploadFile = File(...),
    model: str = Form("small"),
    language: str = Form(""),
    word_timestamps: str = Form("false"),
):
    import uuid

    check_and_increment(get_client_ip(request), "transcribe", DAILY_TRANSCRIBE_LIMIT)

    job_id = uuid.uuid4().hex
    suffix = Path(file.filename or "audio").suffix or ".tmp"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    content = await file.read()
    if len(content) > MAX_FILE_MB * 1024 * 1024:
        from fastapi import HTTPException
        raise HTTPException(413, f"Файлът е по-голям от {MAX_FILE_MB}MB")
    tmp.write(content)
    tmp.close()

    lang = language if language else None
    word_ts = word_timestamps.lower() == "true"

    jobs[job_id] = {"segments": [], "done": False, "error": None, "info": {}}
    t = threading.Thread(
        target=run_transcription,
        args=(job_id, tmp.name, model, lang, word_ts),
        daemon=True,
    )
    t.start()
    return {"job_id": job_id}


@app.get("/stream/{job_id}")
async def stream(job_id: str):
    if job_id not in jobs:
        return {"error": "Not found"}

    async def event_gen():
        sent = 0
        while True:
            job = jobs.get(job_id)
            if not job:
                yield f"data: {json.dumps({'error': 'job not found'})}\n\n"
                break

            segs = job["segments"]
            while sent < len(segs):
                yield f"data: {json.dumps({'segment': segs[sent]})}\n\n"
                sent += 1

            if job["done"]:
                payload = {"done": True, "info": job.get("info", {})}
                if job["error"]:
                    payload["error"] = job["error"]
                yield f"data: {json.dumps(payload)}\n\n"
                # clean up
                del jobs[job_id]
                break

            await asyncio.sleep(0.3)

    return StreamingResponse(event_gen(), media_type="text/event-stream")


def pcm_to_wav(pcm: bytes, rate: int) -> bytes:
    n = len(pcm)
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF", 36 + n, b"WAVE", b"fmt ",
        16, 1, 1, rate, rate * 2, 2, 16,
        b"data", n,
    )
    return header + pcm


async def gemini_tts_once(text: str, voice: str) -> tuple[bytes, int] | None:
    import httpx

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{TTS_MODEL}:generateContent?key={GEMINI_API_KEY}"
    body = {
        "contents": [{"parts": [{"text": text}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}},
        },
    }
    async with httpx.AsyncClient(timeout=30) as client:
        res = await client.post(url, json=body)
    if res.status_code != 200:
        return None
    data = res.json()
    parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])
    inline = parts[0].get("inlineData") if parts else None
    if not inline or not inline.get("data"):
        return None
    rate_match = re.search(r"rate=(\d+)", inline.get("mimeType", ""))
    rate = int(rate_match.group(1)) if rate_match else 24000
    pcm = base64.b64decode(inline["data"])
    return pcm, rate


@app.post("/tts")
async def tts(request: Request, text: str = Form(...), voice: str = Form(TTS_VOICE)):
    if not GEMINI_API_KEY:
        raise HTTPException(500, "GEMINI_API_KEY не е конфигуриран на сървъра")

    text = text.strip()
    if not text:
        raise HTTPException(400, "Празен текст")
    if voice not in TTS_VOICES:
        voice = TTS_VOICE

    cache_key = f"{voice}:{text}"
    if cache_key in tts_cache:
        return Response(content=tts_cache[cache_key], media_type="audio/wav")

    check_and_increment(get_client_ip(request), "tts", DAILY_TTS_LIMIT)

    result = await gemini_tts_once(text, voice)
    if not result:
        result = await gemini_tts_once(text, voice)  # един повторен опит
    if not result:
        raise HTTPException(502, "Gemini TTS не върна аудио")

    pcm, rate = result
    wav = pcm_to_wav(pcm, rate)
    tts_cache[cache_key] = wav
    return Response(content=wav, media_type="audio/wav")


@app.get("/", response_class=HTMLResponse)
async def index():
    with open(Path(__file__).parent / "index.html", encoding="utf-8") as f:
        return f.read()


app.mount("/icons", StaticFiles(directory=Path(__file__).parent / "icons"), name="icons")


@app.get("/manifest.json")
async def manifest():
    return FileResponse(Path(__file__).parent / "manifest.json", media_type="application/manifest+json")


@app.get("/sw.js")
async def service_worker():
    return FileResponse(Path(__file__).parent / "sw.js", media_type="application/javascript")


@app.get("/.well-known/assetlinks.json")
async def assetlinks():
    path = Path(__file__).parent / ".well-known" / "assetlinks.json"
    if path.exists():
        return FileResponse(path, media_type="application/json")
    return []


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 7979))
    host = "0.0.0.0" if os.environ.get("PORT") else "127.0.0.1"
    uvicorn.run(app, host=host, port=port, log_level="warning")
