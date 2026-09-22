"""Store completed clips in a private Supabase Storage bucket."""

import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


ENV_FILE = Path(__file__).resolve().parents[1] / ".env"
MAX_FILE_BYTES = 50 * 1024 * 1024


def _settings() -> tuple[str, str, str]:
    values = dict(os.environ)
    if ENV_FILE.is_file():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                name, value = line.split("=", 1)
                values.setdefault(name.strip(), value.strip().strip('"').strip("'"))
    url = values.get("SUPABASE_URL", "").rstrip("/")
    key = values.get("SUPABASE_SECRET_KEY", "")
    bucket = values.get("SUPABASE_BUCKET", "highlight-videos")
    if not url.startswith("https://") or not key:
        raise RuntimeError("Supabase is not configured. Set SUPABASE_URL and SUPABASE_SECRET_KEY in backend/.env.")
    return url, key, bucket


def _request(url: str, key: str, data: bytes, content_type: str) -> dict:
    request = Request(url, data=data, method="POST", headers={
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": content_type,
    })
    try:
        with urlopen(request, timeout=180) as response:
            return json.load(response)
    except HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8"))
            message = detail.get("message") or detail.get("error") or exc.reason
        except (ValueError, UnicodeDecodeError):
            message = exc.reason
        raise RuntimeError(f"Supabase Storage rejected the request ({exc.code}): {message}") from exc
    except URLError as exc:
        raise RuntimeError(f"Cannot reach Supabase Storage: {exc.reason}") from exc


def upload_clip(path: Path, job_id: str) -> str:
    url, key, bucket = _settings()
    size = path.stat().st_size
    if size > MAX_FILE_BYTES:
        raise RuntimeError(f"{path.name} is larger than the 50 MB Supabase Free file limit.")
    object_path = f"clips/{job_id}/{path.name}"
    endpoint = f"{url}/storage/v1/object/{quote(bucket)}/{quote(object_path, safe='/')}"
    _request(endpoint, key, path.read_bytes(), "video/mp4")
    return object_path


def signed_clip_url(job_id: str, filename: str, download: bool = False) -> str:
    url, key, bucket = _settings()
    object_path = f"clips/{job_id}/{filename}"
    endpoint = f"{url}/storage/v1/object/sign/{quote(bucket)}/{quote(object_path, safe='/')}"
    result = _request(endpoint, key, json.dumps({"expiresIn": 3600}).encode(), "application/json")
    signed = result.get("signedURL") or result.get("signedUrl")
    if not signed:
        raise RuntimeError("Supabase did not return a signed clip URL.")
    target = signed if signed.startswith("https://") else f"{url}/storage/v1{signed}"
    return f"{target}&{urlencode({'download': filename})}" if download else target
