"""Cut timestamped highlights from the original video with FFmpeg."""

import subprocess
from pathlib import Path
from typing import Callable

from fastapi import HTTPException
from services.captions import write_srt


OUTPUT_SIZES = {
    "16:9": (1280, 720),
    "9:16": (720, 1280),
    "1:1": (720, 720),
}


def create_clips(source: Path, highlights: list[dict], segments: list[dict], output_root: Path,
                 job_id: str, output_format: str = "original",
                 progress: Callable[[int, int], None] | None = None) -> list[dict]:
    clip_dir = output_root / "clips" / job_id
    clip_dir.mkdir(parents=True, exist_ok=True)
    clips = []
    for index, highlight in enumerate(highlights, start=1):
        start = float(highlight["start"])
        duration = float(highlight["end"]) - start
        if start < 0 or duration <= 0:
            raise HTTPException(status_code=502, detail="Invalid highlight timestamps.")
        clip_name = f"highlight_{index}.mp4"
        clip_path = clip_dir / clip_name
        subtitle_name = f"highlight_{index}.srt"
        max_words = 4 if output_format == "9:16" else 6 if output_format == "1:1" else None
        write_srt(clip_dir / subtitle_name, segments, start, float(highlight["end"]), max_words)
        filters = []
        if output_format in OUTPUT_SIZES:
            width, height = OUTPUT_SIZES[output_format]
            filters.extend([
                f"scale={width}:{height}:force_original_aspect_ratio=increase",
                f"crop={width}:{height}",
            ])
        font_size = 15 if output_format == "9:16" else 20 if output_format == "1:1" else 30
        margin_v = 14 if output_format == "9:16" else 16
        filters.append(
            f"subtitles={subtitle_name}:force_style='"
            f"Fontname=Arial,Fontsize={font_size},PrimaryColour=&H0000FFFF,"
            "OutlineColour=&H00000000,Outline=2,Shadow=1,"
            f"Alignment=2,MarginV={margin_v}'"
        )
        command = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-ss", f"{start:.3f}", "-i", str(source), "-t", f"{duration:.3f}",
            "-map", "0:v:0", "-map", "0:a:0",
            "-vf", ",".join(filters),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
            "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart",
            str(clip_path),
        ]
        try:
            result = subprocess.run(command, capture_output=True, text=True, cwd=clip_dir)
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"FFmpeg could not start: {exc}") from exc
        if result.returncode != 0 or not clip_path.is_file() or clip_path.stat().st_size == 0:
            raise HTTPException(status_code=422, detail=f"FFmpeg could not create clip {index}: {(result.stderr or '').strip()[-500:]}")
        clips.append({**highlight, "filename": clip_name, "url": f"/clips/{job_id}/{clip_name}"})
        if progress:
            progress(index, len(highlights))
    return clips
