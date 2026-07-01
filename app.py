import os
import json
import asyncio
import tempfile
import threading
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import HTMLResponse, StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

app = FastAPI()

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
    file: UploadFile = File(...),
    model: str = Form("small"),
    language: str = Form(""),
    word_timestamps: str = Form("false"),
):
    import uuid

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


@app.get("/", response_class=HTMLResponse)
async def index():
    with open(Path(__file__).parent / "index.html", encoding="utf-8") as f:
        return f.read()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 7979))
    host = "0.0.0.0" if os.environ.get("PORT") else "127.0.0.1"
    uvicorn.run(app, host=host, port=port, log_level="warning")
