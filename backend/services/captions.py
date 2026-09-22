"""Build clip-relative SRT captions from Whisper segments."""

from pathlib import Path


def _timestamp(seconds: float) -> str:
    milliseconds = round(seconds * 1000)
    hours, remaining = divmod(milliseconds, 3_600_000)
    minutes, remaining = divmod(remaining, 60_000)
    secs, millis = divmod(remaining, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"


def _phrases(words: list[str], max_words: int | None) -> list[list[str]]:
    if max_words is None:
        return [words]
    chunks = [words[i:i + max_words] for i in range(0, len(words), max_words)]
    if len(chunks) > 1 and len(chunks[-1]) == 1:
        chunks[-2].extend(chunks.pop())
    return chunks


def write_srt(path: Path, segments: list[dict], start: float, end: float,
              max_words: int | None = None) -> None:
    entries = []
    for segment in segments:
        cue_start = max(start, float(segment["start"]))
        cue_end = min(end, float(segment["end"]))
        words = str(segment["text"]).split()
        if cue_end <= cue_start or not words:
            continue
        phrases = _phrases(words, max_words)
        consumed = 0
        for phrase in phrases:
            phrase_start = cue_start + (cue_end - cue_start) * consumed / len(words)
            consumed += len(phrase)
            phrase_end = cue_start + (cue_end - cue_start) * consumed / len(words)
            entries.append(
                f"{len(entries) + 1}\n"
                f"{_timestamp(phrase_start - start)} --> {_timestamp(phrase_end - start)}\n"
                f"{' '.join(phrase).upper()}\n"
            )
    path.write_text("\n".join(entries), encoding="utf-8")
