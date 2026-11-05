# FRS Bridge

**Give a local AI application ears on a handheld radio.**

FRS Bridge connects a radio's receive-audio output to a computer's audio input. It records audio, creates speech-friendly playback files, optionally transcribes speech and matches enrolled speakers, and exposes ordered JSON events for AI or API consumers. Local-first, CPU-capable, receive-only.

**Status: experimental v0.1.** 16 automated checks pass; actual local transcription and voiceprint models also passed synthetic speech smoke tests. This release is not yet validated end-to-end with a live radio, human speaker enrollment, or a representative noisy-radio corpus. Do not use it as an emergency or identity-authentication system.

```text
FRS radio → headphone/speaker output → USB audio input → continuous recording
                                                        ↓
                                      raw WAV + normalized playback WAV
                                                        ↓
                                  speech candidate gate → optional local STT
                                                        → optional voiceprint match
                                                        ↓
                                           SQLite → JSON API / JSONL → AI
```

The radio demodulates RF. FRS Bridge receives already-demodulated audio; it cannot determine the RF frequency, transmitter identity, or radio channel from the cable. It does not key PTT, transmit, or modify a radio.

## Install

Install Python **3.11 recommended** and FFmpeg (including `ffprobe`):

- macOS: `brew install python@3.11 ffmpeg`
- Ubuntu/Debian: `sudo apt install python3 python3-venv ffmpeg`
- Windows: install Python 3.11 and FFmpeg, adding both to PATH.

```sh
git clone https://github.com/joesbobclaw/frs-bridge.git
cd frs-bridge
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
frs-bridge --help
```

Use `python` instead of `python3.11` where appropriate. Windows activation: `.venv\Scripts\Activate.ps1`. Recording, processing, and the event API have no third-party Python runtime dependencies. Optional ML packages bring substantially more dependencies and disk/RAM use; “lightweight voiceprint” describes the stored embedding, not a dependency-free model runtime.

## Connect and record

Use a receive-audio cable appropriate for your radio and an audio interface with a compatible input. A programming cable is usually **not** an audio cable. Speaker-level outputs may require attenuation/isolation; avoid overdriving a microphone input. Disable interface AGC/noise effects if possible. Start at low receiver volume, then calibrate.

```sh
frs-bridge devices
```

Discover the actual input rather than selecting a built-in microphone accidentally:

```sh
# macOS: list indexes, then substitute the USB audio index below
ffmpeg -f avfoundation -list_devices true -i ""
frs-bridge record --backend avfoundation --device ':2'

# Linux ALSA: inspect `arecord -l`, then use your actual card/device
frs-bridge record --backend alsa --device 'hw:1,0'

# Linux PulseAudio: inspect `pactl list short sources`
frs-bridge record --backend pulse --device default

# Windows: copy the exact audio device name from FFmpeg's listing
ffmpeg -list_devices true -f dshow -i dummy
frs-bridge record --backend dshow --device 'audio=USB Audio Device'
```

Allow microphone/audio-input permissions when your OS asks. Device listing commands may exit with an error even after printing the list. None of these sample indexes or names is universal. Only the current host platform's backend will be available in FFmpeg.

Capture is continuous PCM, split into 15-second WAV files. Background analysis never pauses capture; if its eight-clip queue fills, the raw recording is retained and a `processing.skipped` event records the backlog. Ctrl-C saves the buffered tail and drains queued work. Processing and transcription errors do not erase recordings. A separate `capture.saved` event is written before processing. A crash can lose the current in-memory segment (up to 15 seconds).

**Disk retention is manual in v0.1.** Continuous capture plus raw/clean derivatives uses roughly 8 GB/day at 16 kHz mono PCM16. Stop capture before archiving/deleting the data directory. Don't leave an unattended recorder filling a disk.

## Process a file / normalize voice

```sh
frs-bridge process your-recording.wav
frs-bridge effect data/clips/CLIP_ID/clean.wav shifted.wav --semitones 3
```

`process` accepts formats FFmpeg can decode, preserves a raw PCM copy, and makes a gentle 120–5000 Hz bandpass/loudness-normalized playback copy. `effect` changes pitch while approximately preserving duration. It is **local playback processing**, not RF modulation, voice cloning, or transmission. Originals remain untouched. This is not a denoising miracle: normalization can amplify noise too.

## Speech to text (local, optional)

```sh
python -m pip install -e '.[transcribe]'
frs-bridge process sample.wav --transcribe --model base --language en
frs-bridge record --backend avfoundation --device ':2' --transcribe --model base --language en
```

The first run may download Whisper model weights. Audio is processed locally, with no paid API key. `--language` selects the spoken language; this version transcribes, it does **not** translate between languages. Use a larger model if your CPU and latency budget allow.

Speech is transcribed from the raw copy, not from an aggressively cleaned signal. An energy/zero-crossing heuristic requires at least 0.6 seconds of continuous speech-like audio. The default `--threshold -45` dBFS is a starting point, not a universal calibration. Sustained activity of 12 seconds or clips of 30+ seconds skip transcription as interference candidates. These conservative rules can miss legitimate long speech. Short clicks, static, music, silence, or overlapping speech can still confuse the detector and model.

Every transcript is marked `verified: false`; token/model scores are not proof that someone said those words. Silence/noise hallucinations remain possible. Fixed chunks can split an utterance, and there is no cross-chunk reconstruction yet.

## Lightweight voiceprints (local, optional)

Enroll **consenting participants**, using pseudonymous labels and two or more separate 5–15 second samples of one speaker. Capture samples through the same radio/audio path used for matching; clean studio speech is not a substitute for narrowband radio enrollment.

```sh
python -m pip install -e '.[voiceprint]'
frs-bridge enroll operator_a sample-a.wav sample-b.wav --consent
frs-bridge speakers
frs-bridge identify another-sample.wav
frs-bridge record --backend avfoundation --device ':2' --identify --transcribe
frs-bridge forget operator_a
```

Install both ML features with `python -m pip install -e '.[transcribe,voiceprint]'`. Enrollment stores a **256-dimensional local speaker embedding** (Resemblyzer), averaged from supplied samples, not a copy of their voice or a voice generator. The encoder removes silence and requires at least three seconds of remaining audio. Recognition assumes **one speaker per clip**; it does not diarize a conversation or detect all overlapping speakers. The speaker model runs in a persistent isolated process to avoid OpenMP conflicts with Whisper.

A match requires cosine similarity >= 0.75 and a >= 0.08 lead over the next enrolled speaker by default. These are **uncalibrated starting values**, not measured error guarantees. `identify --threshold ... --margin ...` and record/process `--speaker-threshold ... --speaker-margin ...` let you tune them. Unknown voices, short samples, noise, radios, distance, and a changed microphone can all cause false matches or misses. With only one enrollment, there is no second-speaker margin to measure. Recordings/replays can impersonate a speaker: **never use this as authentication or authorize actions from a match.**

Embeddings stay in `data/voiceprints.json` with restrictive file permissions on POSIX. They are sensitive biometric data even though they are small. `forget` removes the active enrollment, not old recordings, event labels, or backups. Manage those separately. Do not commit or share real samples or the data directory.

## API and AI integration

In a second terminal, using the same data path:

```sh
frs-bridge serve --port 8765
curl 'http://127.0.0.1:8765/health'
curl 'http://127.0.0.1:8765/events?after=0&limit=100'
frs-bridge export > events.jsonl
python examples/poll_events.py
```

Custom storage: `frs-bridge --data /private/path record ...`, and the same `--data` for `serve`. The read-only server binds exclusively to **127.0.0.1**. It has no authentication, no CORS allowance, and no raw-audio or embedding download endpoints. Do not expose it through a tunnel or reverse proxy without adding authentication and transport security. Other local processes can read it.

`GET /events` returns ordered events plus `next_after`. Persist the last successfully processed ID to resume after a restart. Polling is not push delivery; the example prints events and does not send anything to an external AI service. Audio paths are relative to your private data directory, not public URLs.

```json
{
  "schema": "frs-bridge.event.v1",
  "id": 42,
  "type": "audio.recorded",
  "clip_id": "synthetic-example",
  "audio": {"raw": "clips/synthetic-example/raw.wav", "clean": "clips/synthetic-example/clean.wav"},
  "transcription": {"status": "unverified", "text": "Radio check.", "verified": false},
  "speaker": {"label": "unknown", "score": 0.63, "reason": "weak_or_ambiguous", "verified": false}
}
```

This is an illustrative abbreviated event, not a real recording. Additional event types are `capture.saved`, `processing.skipped`, and `processing.error`. A recorded clip's transcription can be `disabled`, `skipped_no_speech_candidate`, `skipped_sustained_signal`, `unverified`, `uncertain`, or `error`. Speaker fields appear only when matching was attempted.

Radio content is **untrusted input**. A remote voice saying “ignore your instructions” must remain data, not become an agent instruction. Keep downstream summarization separate from tool permissions. Neither a transcript nor a voice match should automatically trigger physical actions, purchases, messages, or account access.

## Reproduce checks

```sh
python -m unittest discover -s tests -v
```

Tests generate synthetic audio and mock embeddings/transcription. They check file outputs, silence handling, processing failures, cursor ordering, HTTP boundaries, pitch duration, and unknown/ambiguous speaker matching. See [validation status](docs/VALIDATION.md) for what is and is not established.

## Publication and roadmap

- [Draft: Giving AI Ears in the Physical World](docs/physical-world-ai.md)
- [Architecture and evaluation plan](docs/ARCHITECTURE.md)
- Next: actual radio acceptance run, held-out speaker/noise evaluation, utterance segmentation, disk quotas/retention, health/lag reporting, multi-speaker diarization, and optional language translation.

Use receiving equipment and recording practices appropriate to your jurisdiction and participant expectations. FRS is a radio service, not a privacy guarantee. This software provides no transmit path and does not make noncompliant radios compliant.
