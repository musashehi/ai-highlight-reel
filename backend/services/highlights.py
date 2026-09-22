"""Local highlight selection using Ollama and Whisper segment boundaries."""

import json
import math
import urllib.error
import urllib.request

from fastapi import HTTPException


OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
MODEL = "qwen3:4b"
LENGTHS = {"auto": (15, 60), "15-30": (15, 30), "30-60": (30, 60)}


def select_highlights(segments: list[dict], content_type: str = "auto", count: int = 3,
                      clip_length: str = "auto") -> list[dict]:
    if not segments:
        return []
    minimum, maximum = LENGTHS[clip_length]

    candidates = []
    batch = []
    batch_chars = 0
    for index, segment in enumerate(segments):
        size = len(segment["text"]) + 70
        if batch and batch_chars + size > 5500:
            candidates.extend(_analyze_batch(batch, segments, content_type, count, minimum, maximum, clip_length))
            batch, batch_chars = [], 0
        batch.append(index)
        batch_chars += size
    if batch:
        candidates.extend(_analyze_batch(batch, segments, content_type, count, minimum, maximum, clip_length))

    candidates.sort(key=lambda item: item["score"], reverse=True)
    chosen = []
    for item in candidates:
        if any(max(0, min(item["end"], old["end"]) - max(item["start"], old["start"]))
               / min(item["end"] - item["start"], old["end"] - old["start"]) > 0.5
               for old in chosen):
            continue
        chosen.append(item)
        if len(chosen) == count:
            break
    return chosen


def _analyze_batch(ids: list[int], segments: list[dict], content_type: str, count: int,
                   minimum: int, maximum: int, clip_length: str) -> list[dict]:

    numbered = [
        {"id": i, "start": s["start"], "end": s["end"], "text": s["text"]}
        for i in ids for s in [segments[i]]
    ]
    prompt = (
        f"Select up to {count} strong standalone short-form video moments from this "
        f"{content_type} transcript. Look for compelling hooks, insights, stories, "
        "emotion, humor, or exciting plays as appropriate. Each clip should make "
        f"sense alone and run {minimum}-{maximum} seconds. Use ONLY the provided "
        "segment IDs as boundaries. Return JSON with a highlights array; each "
        "item must have integer start_id and end_id (inclusive), integer score "
        "from 0 to 100, short title, and short reason. Do not invent moments.\n\n"
        + json.dumps(numbered, ensure_ascii=False)
    )
    payload = {
        "model": MODEL,
        "stream": False,
        "format": "json",
        "think": False,
        "options": {"temperature": 0.2, "num_predict": 512},
        "messages": [
            {"role": "system", "content": "You are a video editor. Respond with valid JSON only."},
            {"role": "user", "content": prompt},
        ],
    }
    request = urllib.request.Request(
        OLLAMA_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            result = json.load(response)
        raw = json.loads(result["message"]["content"])
    except (urllib.error.URLError, TimeoutError) as exc:
        raise HTTPException(status_code=503, detail=f"Local Ollama is unavailable: {exc}") from exc
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(status_code=502, detail="Ollama returned invalid JSON.") from exc

    if not isinstance(raw, dict) or not isinstance(raw.get("highlights"), list):
        raise HTTPException(status_code=502, detail="Ollama returned an invalid highlight list.")

    valid = []
    for item in raw["highlights"]:
        if not isinstance(item, dict):
            continue
        start_id, end_id, score = (item.get(k) for k in ("start_id", "end_id", "score"))
        title, reason = item.get("title"), item.get("reason")
        if not (type(start_id) is int and type(end_id) is int):
            continue
        if type(score) is float and 0 <= score <= 1 and math.isfinite(score):
            score = round(score * 100)
        if type(score) is not int:
            continue
        if not (start_id in ids and end_id in ids and start_id <= end_id and 0 <= score <= 100):
            continue
        if not (isinstance(title, str) and title.strip() and isinstance(reason, str) and reason.strip()):
            continue
        start, end = segments[start_id]["start"], segments[end_id]["end"]
        if not (math.isfinite(start) and math.isfinite(end) and 0 <= start < end):
            continue
        if end - start > maximum:
            continue
        while end - start < minimum:
            choices = []
            if start_id > ids[0]:
                candidate_start = segments[start_id - 1]["start"]
                if end - candidate_start <= maximum:
                    choices.append((end - candidate_start, start_id - 1, end_id))
            if end_id < ids[-1]:
                candidate_end = segments[end_id + 1]["end"]
                if candidate_end - start <= maximum:
                    choices.append((candidate_end - start, start_id, end_id + 1))
            if not choices:
                break
            _, start_id, end_id = min(choices, key=lambda option: option[0])
            start, end = segments[start_id]["start"], segments[end_id]["end"]
        if end - start < minimum and clip_length != "auto":
            continue
        valid.append({"start": start, "end": end, "score": score,
                      "title": title.strip()[:100], "reason": reason.strip()[:300]})

    return valid
