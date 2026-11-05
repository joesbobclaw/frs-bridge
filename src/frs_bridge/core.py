"""Portable file processing and durable, ordered events. No cloud credentials."""
from array import array
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sqlite3
import subprocess
import sys
import uuid
import wave

RATE = 16000
FRAME = 1600  # 100 ms mono signed 16-bit PCM


def ffmpeg(args):
    subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


def write_wav(path, pcm):
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(RATE)
        out.writeframes(pcm)


def read_wav(path):
    with wave.open(str(path), "rb") as inp:
        if (inp.getnchannels(), inp.getsampwidth(), inp.getframerate()) != (1, 2, RATE):
            raise ValueError("Expected 16 kHz mono PCM16 WAV")
        return inp.readframes(inp.getnframes())


def activity(pcm, threshold=-45):
    """Energy + zero crossing heuristic, NOT a validated speech detector."""
    active = run = longest = total = 0
    for offset in range(0, len(pcm), FRAME * 2):
        block = pcm[offset:offset + FRAME * 2]
        if len(block) < FRAME * 2:
            break
        samples = array("h", block)
        if sys.byteorder != "little":
            samples.byteswap()
        rms = math.sqrt(sum(s*s for s in samples) / len(samples))
        db = 20 * math.log10(max(rms, 1) / 32768)
        zcr = sum((a < 0) != (b < 0) for a, b in zip(samples, samples[1:])) / (len(samples)-1)
        speech_like = db >= threshold and 0.01 <= zcr <= 0.45
        total += 1
        if speech_like:
            active += 1
            run += 1
            longest = max(longest, run)
        else:
            run = 0
    return {"duration_seconds": len(pcm)/(RATE*2), "active_fraction": active/max(total, 1),
            "longest_active_seconds": round(longest/10, 2),
            "candidate": longest >= 6, "threshold_dbfs": threshold}


class Store:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, body TEXT NOT NULL)")

    def connect(self):
        return sqlite3.connect(self.root / "events.sqlite3", timeout=30)

    def emit(self, event):
        event = {"schema": "frs-bridge.event.v1", "created_at": datetime.now(timezone.utc).isoformat(), **event}
        with self.connect() as db:
            cursor = db.execute("INSERT INTO events(body) VALUES (?)", (json.dumps(event),))
            event["id"] = cursor.lastrowid
        return event

    def events(self, after=0, limit=100):
        with self.connect() as db:
            return [{**json.loads(body), "id": ident} for ident, body in db.execute(
                "SELECT id,body FROM events WHERE id>? ORDER BY id LIMIT ?", (after, limit))]


class Transcriber:
    def __init__(self, model="base", language=None):
        from faster_whisper import WhisperModel
        self.model = WhisperModel(model, device="cpu", compute_type="int8")
        self.language = language

    def __call__(self, path):
        segments, info = self.model.transcribe(str(path), language=self.language, beam_size=5,
                                             temperature=0, vad_filter=True, condition_on_previous_text=False)
        rows = [{"start": s.start, "end": s.end, "text": s.text.strip(),
                 "avg_logprob": s.avg_logprob, "no_speech_prob": s.no_speech_prob} for s in segments]
        return {"text": " ".join(s["text"] for s in rows), "segments": rows,
                "language": info.language, "engine": "faster-whisper", "verified": False}


def process(store, source, transcriber=None, threshold=-45, captured_at=None, speaker_matcher=None):
    clip_id = uuid.uuid4().hex
    directory = store.root / "clips" / clip_id
    directory.mkdir(parents=True)
    raw, clean = directory / "raw.wav", directory / "clean.wav"
    ffmpeg(["-i", str(source), "-ac", "1", "-ar", str(RATE), "-c:a", "pcm_s16le", str(raw)])
    stats = activity(read_wav(raw), threshold)
    ffmpeg(["-i", str(raw), "-af", "highpass=f=120,lowpass=f=5000,loudnorm=I=-16:TP=-1.5:LRA=11",
            "-ar", str(RATE), "-c:a", "pcm_s16le", str(clean)])
    event = {"type": "audio.recorded", "clip_id": clip_id, "captured_at": captured_at,
             "audio": {"raw": str(raw.relative_to(store.root)), "clean": str(clean.relative_to(store.root))},
             "activity": stats, "transcription": {"status": "disabled", "verified": False}}
    if transcriber:
        if not stats["candidate"]:
            event["transcription"]["status"] = "skipped_no_speech_candidate"
        elif stats["duration_seconds"] >= 30 or stats["longest_active_seconds"] >= 12:
            event["transcription"]["status"] = "skipped_sustained_signal"
        else:
            try:
                result = transcriber(raw)  # preserve original evidence; cleanup is for playback
                suspect = not result["text"].strip() or any(
                    s["avg_logprob"] < -1.0 or s["no_speech_prob"] > 0.6 for s in result["segments"])
                event["transcription"] = {**result, "status": "uncertain" if suspect else "unverified", "verified": False}
            except Exception:
                event["transcription"] = {"status": "error", "verified": False}
    if speaker_matcher and stats["candidate"] and stats["longest_active_seconds"] < 12:
        try:
            event["speaker"] = speaker_matcher(raw)
        except Exception:
            event["speaker"] = {"label": "unknown", "reason": "insufficient_audio_or_encoder_error", "verified": False}
    return store.emit(event)


def effect(source, target, semitones):
    if not -12 <= semitones <= 12:
        raise ValueError("Pitch shift must be between -12 and 12 semitones")
    ratio = 2 ** (semitones / 12)
    ffmpeg(["-i", str(source), "-ar", str(RATE), "-ac", "1", "-af",
            f"aresample={RATE},asetrate={RATE}*{ratio},aresample={RATE},atempo={1/ratio}", str(target)])
