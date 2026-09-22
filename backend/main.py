"""FastAPI entry point for the local highlight maker."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock
from tempfile import TemporaryDirectory, mkdtemp
import shutil
import uuid

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from faster_whisper import WhisperModel

from services.pipeline import process_video
from services.storage import signed_clip_url, upload_clip


app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

model = WhisperModel("small", device="cpu", compute_type="int8")
BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "outputs"

executor = ThreadPoolExecutor(max_workers=1)
jobs: dict[str, dict] = {}
jobs_lock = Lock()


def validate(filename: str | None, content_type: str, clip_count: int,
             output_format: str, clip_length: str) -> str:
    suffix = Path(filename or "").suffix.lower()
    if suffix not in {".mp4", ".mov", ".mkv", ".webm"}:
        raise HTTPException(status_code=400, detail="Supported video formats: MP4, MOV, MKV, WebM.")
    if content_type not in {"auto", "podcast", "sports", "vlog", "interview", "speech"}:
        raise HTTPException(status_code=400, detail="Invalid content type.")
    if not 1 <= clip_count <= 10:
        raise HTTPException(status_code=400, detail="Clip count must be between 1 and 10.")
    if output_format not in {"original", "16:9", "9:16", "1:1"}:
        raise HTTPException(status_code=400, detail="Invalid output format.")
    if clip_length not in {"auto", "15-30", "30-60"}:
        raise HTTPException(status_code=400, detail="Invalid clip length.")
    return suffix


async def save_upload(file: UploadFile, destination: Path) -> None:
    try:
        with destination.open("wb") as output:
            while chunk := await file.read(1024 * 1024):
                output.write(chunk)
    finally:
        await file.close()


def job_progress(job_id: str, stage: str, done: int, total: int) -> None:
    with jobs_lock:
        jobs[job_id].update(status="processing", stage=stage,
                            clips_done=done, clips_total=total)


def store_clips(result: dict, job_id: str, work_dir: Path,
                progress=None) -> dict:
    for index, clip in enumerate(result["highlights"], start=1):
        clip_path = work_dir / "clips" / job_id / clip["filename"]
        clip["storage_path"] = upload_clip(clip_path, job_id)
        if progress:
            progress("storing", index, len(result["highlights"]))
    result["saved_to"] = None
    result["audio_file"] = None
    result["storage"] = "supabase"
    return result


def run_job(job_id: str, source: Path, filename: str, content_type: str,
            clip_count: int, output_format: str, clip_length: str) -> None:
    try:
        result = process_video(
            source, filename, source.parent, job_id, model, content_type, clip_count,
            output_format, clip_length,
            lambda stage, done, total: job_progress(job_id, stage, done, total),
        )
        job_progress(job_id, "storing", 0, len(result["highlights"]))
        result = store_clips(result, job_id, source.parent,
                             lambda stage, done, total: job_progress(job_id, stage, done, total))
        with jobs_lock:
            jobs[job_id].update(status="done", stage="done", result=result)
    except HTTPException as exc:
        with jobs_lock:
            jobs[job_id].update(status="error", stage="error", error=str(exc.detail))
    except Exception as exc:
        with jobs_lock:
            jobs[job_id].update(status="error", stage="error", error=f"Processing failed: {exc}")
    finally:
        shutil.rmtree(source.parent, ignore_errors=True)


@app.get("/")
def home():
    return {"status": "ok", "message": "AI Highlight Reel Maker API is running"}


@app.get("/clips/{job_id}/{filename}")
def get_clip(job_id: str, filename: str, download: bool = False):
    if len(job_id) != 32 or any(char not in "0123456789abcdef" for char in job_id):
        raise HTTPException(status_code=404, detail="Clip not found.")
    if not filename.startswith("highlight_") or not filename.endswith(".mp4") or not filename[10:-4].isdigit():
        raise HTTPException(status_code=404, detail="Clip not found.")
    clip_path = OUTPUT_DIR / "clips" / job_id / filename
    if clip_path.is_file():
        return FileResponse(clip_path, media_type="video/mp4", filename=filename if download else None)
    try:
        return RedirectResponse(signed_clip_url(job_id, filename, download))
    except RuntimeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/upload")
async def upload_video(file: UploadFile = File(...), content_type: str = Form("auto"),
                       clip_count: int = Form(3), output_format: str = Form("original"),
                       clip_length: str = Form("auto")):
    """Compatible synchronous endpoint for Swagger and existing clients."""
    suffix = validate(file.filename, content_type, clip_count, output_format, clip_length)
    job_id = uuid.uuid4().hex
    with TemporaryDirectory(prefix="highlight-") as directory:
        source = Path(directory) / f"{job_id}{suffix}"
        await save_upload(file, source)
        result = process_video(source, file.filename or source.name, Path(directory), job_id,
                               model, content_type, clip_count, output_format, clip_length)
        return store_clips(result, job_id, Path(directory))


@app.post("/jobs", status_code=202)
async def create_job(file: UploadFile = File(...), content_type: str = Form("auto"),
                     clip_count: int = Form(3), output_format: str = Form("original"),
                     clip_length: str = Form("auto")):
    suffix = validate(file.filename, content_type, clip_count, output_format, clip_length)
    job_id = uuid.uuid4().hex
    work_dir = Path(mkdtemp(prefix="highlight-"))
    source = work_dir / f"{job_id}{suffix}"
    try:
        await save_upload(file, source)
    except Exception:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise
    with jobs_lock:
        jobs[job_id] = {"job_id": job_id, "status": "queued", "stage": "queued",
                        "clips_done": 0, "clips_total": 0}
    executor.submit(run_job, job_id, source, file.filename or source.name,
                    content_type, clip_count, output_format, clip_length)
    return {"job_id": job_id, "status": "queued"}


@app.get("/jobs/{job_id}")
def get_job(job_id: str):
    with jobs_lock:
        job = jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found. The backend may have restarted.")
        return job.copy()
