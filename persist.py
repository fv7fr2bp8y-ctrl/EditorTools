"""Keeps analytics.db and quota.json in a Google Cloud Storage bucket.

Cloud Run's disk is wiped on every restart. On startup the files are restored
from the bucket; a background thread uploads them every minute when they
change, and once more on shutdown. Set PERSIST_BUCKET to enable; without it
everything here is a no-op (local runs).

Uses the metadata server token and the GCS JSON API through `requests`, so no
extra dependency is needed. Safe only with a single instance (max-instances 1).
"""
import os
import sqlite3
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import quote

import requests

BUCKET = os.environ.get("PERSIST_BUCKET", "")
INTERVAL = int(os.environ.get("PERSIST_INTERVAL", "60"))
_META = "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token"

_token = {"value": "", "exp": 0.0}
_last_sig: dict = {}
_lock = threading.Lock()


def _auth() -> dict:
    if time.time() > _token["exp"] - 60:
        r = requests.get(_META, headers={"Metadata-Flavor": "Google"}, timeout=5)
        r.raise_for_status()
        j = r.json()
        _token["value"] = j["access_token"]
        _token["exp"] = time.time() + int(j.get("expires_in", 300))
    return {"Authorization": f"Bearer {_token['value']}"}


def _download(name: str, dest: Path) -> bool:
    url = f"https://storage.googleapis.com/storage/v1/b/{BUCKET}/o/{quote(name, safe='')}?alt=media"
    r = requests.get(url, headers=_auth(), timeout=30)
    if r.status_code == 404:
        return False
    r.raise_for_status()
    tmp = dest.with_suffix(dest.suffix + ".part")
    tmp.write_bytes(r.content)
    tmp.replace(dest)
    return True


def _upload_bytes(name: str, data: bytes):
    url = (f"https://storage.googleapis.com/upload/storage/v1/b/{BUCKET}/o"
           f"?uploadType=media&name={quote(name, safe='')}")
    r = requests.post(url, headers={**_auth(), "Content-Type": "application/octet-stream"},
                      data=data, timeout=60)
    r.raise_for_status()


def _snapshot(path: Path) -> bytes:
    """Consistent copy of a SQLite file (backup API), raw bytes for anything else."""
    if path.suffix != ".db":
        return path.read_bytes()
    fd, tmp = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        with sqlite3.connect(path) as src, sqlite3.connect(tmp) as dst:
            src.backup(dst)
        return Path(tmp).read_bytes()
    finally:
        os.unlink(tmp)


def restore(*paths: Path):
    if not BUCKET:
        return
    for p in paths:
        try:
            if _download(p.name, p):
                st = p.stat()
                _last_sig[p.name] = (st.st_mtime_ns, st.st_size)
                print(f"[persist] restored {p.name} ({st.st_size} bytes)", flush=True)
        except Exception as e:
            print(f"[persist] restore {p.name} failed: {e}", flush=True)


def sync(*paths: Path):
    if not BUCKET:
        return
    with _lock:
        for p in paths:
            try:
                if not p.exists():
                    continue
                st = p.stat()
                sig = (st.st_mtime_ns, st.st_size)
                if _last_sig.get(p.name) == sig:
                    continue
                _upload_bytes(p.name, _snapshot(p))
                _last_sig[p.name] = sig
            except Exception as e:
                print(f"[persist] upload {p.name} failed: {e}", flush=True)


def start(*paths: Path):
    if not BUCKET:
        return

    def loop():
        while True:
            time.sleep(INTERVAL)
            sync(*paths)

    threading.Thread(target=loop, daemon=True, name="persist").start()
