import os
import json
import base64
import struct
import asyncio
import tempfile
import threading
import re
import sqlite3
import hashlib
from datetime import date, datetime, timezone
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse, FileResponse, Response
from fastapi.staticfiles import StaticFiles
import uvicorn

app = FastAPI()


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    resp.headers["X-Frame-Options"] = "SAMEORIGIN"
    resp.headers["Permissions-Policy"] = "microphone=(self)"
    return resp


# Persistent data dir (Railway volume mounts at /data; falls back to local dir)
DATA_DIR = Path(os.environ.get("DATA_DIR", str(Path(__file__).parent)))
DATA_DIR.mkdir(parents=True, exist_ok=True)

DAILY_TRANSCRIBE_LIMIT = 20
DAILY_TTS_LIMIT = 10
QUOTA_FILE = DATA_DIR / "quota.json"
quota_lock = threading.Lock()

# ---------- Analytics (privacy-friendly, self-hosted) ----------
STATS_KEY = os.environ.get("STATS_KEY", "")  # secret to view /stats
ANALYTICS_DB = DATA_DIR / "analytics.db"
IP_SALT = os.environ.get("IP_SALT", "editortools-static-salt")
analytics_lock = threading.Lock()


def init_analytics():
    with sqlite3.connect(ANALYTICS_DB) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT, day TEXT, event TEXT,
            ip_hash TEXT, country TEXT, device TEXT, browser TEXT,
            ui_lang TEXT, extra TEXT
        )""")
        db.execute("CREATE INDEX IF NOT EXISTS idx_day ON events(day)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_event ON events(event)")


init_analytics()


def hash_ip(ip: str, day: str) -> str:
    # daily-salted hash: same visitor consistent within a day, unlinkable across days
    return hashlib.sha256(f"{IP_SALT}:{day}:{ip}".encode()).hexdigest()[:16]


def parse_ua(ua: str):
    ua = ua or ""
    ual = ua.lower()
    if "iphone" in ual or "android" in ual or "mobile" in ual:
        device = "mobile"
    elif "ipad" in ual or "tablet" in ual:
        device = "tablet"
    else:
        device = "desktop"
    if "edg/" in ual: browser = "Edge"
    elif "chrome" in ual and "chromium" not in ual: browser = "Chrome"
    elif "firefox" in ual: browser = "Firefox"
    elif "safari" in ual: browser = "Safari"
    elif "samsungbrowser" in ual: browser = "Samsung"
    else: browser = "Other"
    # TWA / Android app heuristic
    if "wv" in ual and "android" in ual: browser = "Android app"
    return device, browser


def log_event(request: Request, event: str, ui_lang: str = "", country: str = "", extra: str = ""):
    try:
        ip = get_client_ip(request)
        day = date.today().isoformat()
        ts = datetime.now(timezone.utc).isoformat()
        device, browser = parse_ua(request.headers.get("user-agent", ""))
        if not country:
            country = (request.headers.get("cf-ipcountry")
                       or request.headers.get("x-vercel-ip-country") or "")
        with analytics_lock, sqlite3.connect(ANALYTICS_DB) as db:
            db.execute(
                "INSERT INTO events (ts,day,event,ip_hash,country,device,browser,ui_lang,extra) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (ts, day, event, hash_ip(ip, day), country, device, browser, ui_lang, extra),
            )
    except Exception:
        pass


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
    log_event(request, "transcribe", ui_lang=language, extra=model)

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
    log_event(request, "tts", extra=voice)

    # Gemini понякога връща текст вместо аудио — до 4 опита свеждат провала под ~2%
    result = None
    for _ in range(4):
        result = await gemini_tts_once(text, voice)
        if result:
            break
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


@app.post("/track")
async def track(request: Request, event: str = Form(...), ui_lang: str = Form(""),
                country: str = Form(""), extra: str = Form("")):
    allowed = {"pageview", "live", "download", "copy", "read_all"}
    if event in allowed:
        log_event(request, event, ui_lang=ui_lang, country=country, extra=extra)
    return {"ok": True}


@app.get("/stats", response_class=HTMLResponse)
async def stats(request: Request, key: str = ""):
    if not STATS_KEY or key != STATS_KEY:
        raise HTTPException(403, "Forbidden")
    with sqlite3.connect(ANALYTICS_DB) as db:
        db.row_factory = sqlite3.Row
        def q(sql, params=()):
            return [dict(r) for r in db.execute(sql, params).fetchall()]

        totals = {r["event"]: r["n"] for r in q(
            "SELECT event, COUNT(*) n FROM events GROUP BY event")}
        total_views = totals.get("pageview", 0)
        uniq_all = q("SELECT COUNT(DISTINCT ip_hash) n FROM events WHERE event='pageview'")[0]["n"]
        today = date.today().isoformat()
        today_views = q("SELECT COUNT(*) n FROM events WHERE event='pageview' AND day=?", (today,))[0]["n"]
        today_uniq = q("SELECT COUNT(DISTINCT ip_hash) n FROM events WHERE event='pageview' AND day=?", (today,))[0]["n"]
        by_day = q("SELECT day, COUNT(*) views, COUNT(DISTINCT ip_hash) uniq "
                   "FROM events WHERE event='pageview' GROUP BY day ORDER BY day DESC LIMIT 30")
        by_device = q("SELECT device, COUNT(DISTINCT ip_hash) n FROM events WHERE event='pageview' GROUP BY device ORDER BY n DESC")
        by_browser = q("SELECT browser, COUNT(DISTINCT ip_hash) n FROM events WHERE event='pageview' GROUP BY browser ORDER BY n DESC")
        by_lang = q("SELECT ui_lang, COUNT(DISTINCT ip_hash) n FROM events WHERE event='pageview' AND ui_lang<>'' GROUP BY ui_lang ORDER BY n DESC")
        by_country = q("SELECT country, COUNT(DISTINCT ip_hash) n FROM events WHERE event='pageview' AND country<>'' GROUP BY country ORDER BY n DESC LIMIT 15")
        feat = {k: totals.get(k, 0) for k in ("transcribe", "tts", "live", "download", "copy", "read_all")}

    def rows(data, k1, k2):
        if not data: return "<tr><td colspan=2 style='color:#8E8AA4'>—</td></tr>"
        mx = max((r[k2] for r in data), default=1) or 1
        out = ""
        for r in data:
            label = r[k1] or "—"
            n = r[k2]
            w = int(100 * n / mx)
            out += (f"<tr><td>{label}</td><td><div class='bar'><div class='barfill' "
                    f"style='width:{w}%'></div><span>{n}</span></div></td></tr>")
        return out

    day_rows = "".join(
        f"<tr><td>{r['day']}</td><td>{r['views']}</td><td>{r['uniq']}</td></tr>" for r in by_day
    ) or "<tr><td colspan=3 style='color:#8E8AA4'>Няма данни още</td></tr>"

    html = f"""<!DOCTYPE html><html lang="bg"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>EditorTools — Статистика</title>
<style>
  * {{ box-sizing:border-box; margin:0; padding:0; }}
  body {{ font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; background:#0E0C18; color:#E8E8F0; padding:32px 20px 80px; }}
  .wrap {{ max-width:920px; margin:0 auto; }}
  h1 {{ font-size:1.5rem; margin-bottom:4px; }}
  .sub {{ color:#8E8AA4; font-size:.85rem; margin-bottom:28px; }}
  .cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:14px; margin-bottom:32px; }}
  .card {{ background:#1A1726; border:1px solid rgba(255,255,255,.08); border-radius:14px; padding:18px; }}
  .card .n {{ font-size:1.9rem; font-weight:700; }}
  .card .l {{ color:#9A96B0; font-size:.8rem; margin-top:2px; }}
  .card .accent {{ color:#8B7BFF; }}
  h2 {{ font-size:1rem; margin:28px 0 12px; color:#DEDCEA; }}
  table {{ width:100%; border-collapse:collapse; background:#1A1726; border:1px solid rgba(255,255,255,.08); border-radius:12px; overflow:hidden; }}
  th,td {{ text-align:left; padding:10px 14px; font-size:.85rem; border-bottom:1px solid rgba(255,255,255,.05); }}
  th {{ color:#8E8AA4; font-weight:600; font-size:.72rem; text-transform:uppercase; letter-spacing:.05em; }}
  tr:last-child td {{ border-bottom:none; }}
  .bar {{ position:relative; background:rgba(255,255,255,.05); border-radius:6px; height:22px; display:flex; align-items:center; }}
  .barfill {{ position:absolute; left:0; top:0; height:100%; background:linear-gradient(90deg,#5B4BE8,#7C6BFF); border-radius:6px; }}
  .bar span {{ position:relative; padding-left:8px; font-size:.8rem; font-weight:600; }}
  .grid2 {{ display:grid; grid-template-columns:1fr 1fr; gap:20px; }}
  @media(max-width:640px){{ .grid2{{grid-template-columns:1fr}} }}
</style></head><body><div class="wrap">
  <h1>📊 EditorTools — Статистика</h1>
  <div class="sub">Анонимна аналитика · без бисквитки · IP-та се хешират дневно</div>
  <div class="cards">
    <div class="card"><div class="n accent">{total_views}</div><div class="l">Общо посещения</div></div>
    <div class="card"><div class="n">{uniq_all}</div><div class="l">Уникални потребители</div></div>
    <div class="card"><div class="n">{today_views}</div><div class="l">Днес посещения</div></div>
    <div class="card"><div class="n">{today_uniq}</div><div class="l">Днес уникални</div></div>
  </div>
  <h2>🛠 Използване на функции</h2>
  <div class="cards">
    <div class="card"><div class="n">{feat['transcribe']}</div><div class="l">Транскрипции</div></div>
    <div class="card"><div class="n">{feat['tts']}</div><div class="l">TTS генерации</div></div>
    <div class="card"><div class="n">{feat['live']}</div><div class="l">Live записи</div></div>
    <div class="card"><div class="n">{feat['download']}</div><div class="l">Изтегляния</div></div>
  </div>
  <div class="grid2">
    <div><h2>📱 Устройство</h2><table><tbody>{rows(by_device,'device','n')}</tbody></table></div>
    <div><h2>🌐 Браузър</h2><table><tbody>{rows(by_browser,'browser','n')}</tbody></table></div>
  </div>
  <div class="grid2">
    <div><h2>🗣 Език на интерфейса</h2><table><tbody>{rows(by_lang,'ui_lang','n')}</tbody></table></div>
    <div><h2>📍 Държава</h2><table><tbody>{rows(by_country,'country','n')}</tbody></table></div>
  </div>
  <h2>📅 Последни 30 дни</h2>
  <table><thead><tr><th>Ден</th><th>Посещения</th><th>Уникални</th></tr></thead><tbody>{day_rows}</tbody></table>
</div></body></html>"""
    return html


app.mount("/icons", StaticFiles(directory=Path(__file__).parent / "icons"), name="icons")


@app.get("/manifest.json")
async def manifest():
    return FileResponse(Path(__file__).parent / "manifest.json", media_type="application/manifest+json")


@app.get("/sw.js")
async def service_worker():
    return FileResponse(Path(__file__).parent / "sw.js", media_type="application/javascript")


@app.get("/privacy.html", response_class=HTMLResponse)
async def privacy():
    with open(Path(__file__).parent / "privacy.html", encoding="utf-8") as f:
        return f.read()


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
