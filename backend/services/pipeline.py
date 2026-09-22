"""The local video-to-highlights pipeline shared by sync and background APIs."""

import subprocess
from pathlib import Path
from typing import Callable

from fastapi import HTTPException
from services.highlights import select_highlights
from services.video import create_clips


Progress = Callable[[str, int, int], None]


def process_video(source: Path, filename: str, output_dir: Path, job_id: str,
                  model, content_type: str, clip_count: int, output_format: str,
                  clip_length: str, progress: Progress | None = None) -> dict:
    def update(stage: str, done: int = 0, total: int = 0) -> None:
        if progress:
            progress(stage, done, total)

    audio_path = output_dir / f"{job_id}.mp3"
    update("extracting")
    try:
        result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
             "-vn", "-acodec", "mp3", str(audio_path)],
            capture_output=True, text=True,
        )
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"FFmpeg could not start: {exc}") from exc
    if result.returncode != 0:
        detail = (result.stderr or "").lower()
        if "does not contain any stream" in detail or "output file #0 does not contain any stream" in detail:
            raise HTTPException(status_code=400, detail="This video does not contain an audio track.")
        raise HTTPException(status_code=422, detail="FFmpeg could not extract audio from this video.")

    update("transcribing")
    try:
        segments, info = model.transcribe(str(audio_path), beam_size=5)
        transcript_segments = [
            {"start": round(segment.start, 2), "end": round(segment.end, 2),
             "text": segment.text.strip()}
            for segment in segments
        ]
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Transcription failed: {exc}") from exc

    update("analyzing")
    highlights = select_highlights(transcript_segments, content_type, clip_count, clip_length)
    update("rendering", 0, len(highlights))
    clips = create_clips(source, highlights, transcript_segments, output_dir, job_id,
                         output_format, lambda done, total: update("rendering", done, total))
    return {
        "status": "success", "filename": filename, "saved_to": str(source),
        "audio_file": str(audio_path), "language": info.language,
        "language_probability": round(info.language_probability, 3),
        "output_format": output_format, "clip_length": clip_length,
        "transcript": " ".join(segment["text"] for segment in transcript_segments),
        "segments": transcript_segments, "highlights": clips,
    }
