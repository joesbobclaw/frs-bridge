# Validation receipt — 2026-11-05

## Observed locally

Environment: macOS, x86_64 Python 3.11.15, FFmpeg; separate project virtual environment.

- **16/16 automated checks passed** with `python -m unittest discover -s tests -v`.
- Continuous FFmpeg synthetic input generated three intact recording segments: 5 s, 5 s, and 1 s. Deliberate processing failures retained all recordings and emitted error events.
- File normalization generated readable raw/clean PCM16 WAVs. Silence skipped model calls, and sustained tone interference skipped transcription.
- Pitch-shifted output approximately preserved source duration.
- The HTTP API bound to loopback, returned ordered cursor-based events, rejected malformed bounds, and did not serve recordings or embeddings.
- Deterministic mock-embedding checks exercised known, unknown, ambiguous, deletion, and invalid-enrollment cases. They validate matching logic, **not speaker accuracy**.
- Optional packages installed successfully after compatibility constraints; `pip check` reported no broken requirements.
- Actual local `faster-whisper` **tiny.en** transcribed a synthetic TTS clip: “Radio check 1-2-3. Please meet at the equipment station when the task is complete.” No cloud speech API was called.
- Actual local Resemblyzer generated a **256-value embedding** from two synthetic same-voice enrollment clips. A different held-out sentence from the same TTS voice matched at cosine similarity approximately **0.962**. A second, unenrolled TTS voice returned **unknown**, similarity approximately **0.531**.
- Combined `process --transcribe --model tiny.en --language en --identify` completed with both transcript and tentative speaker fields in one durable event.

These are **synthetic smoke tests**, not a human or radio-channel evaluation. One TTS voice matching itself does not establish real-speaker accuracy or calibration. Fixture recordings and embeddings were generated outside the source repository and are not published.

## Compatibility fixes included

The optional voiceprint extra constrains NumPy below 2 for older Torch compatibility, Numba below 0.62 to retain supported wheels on the tested Intel Mac, and Setuptools below 81 because legacy `webrtcvad` imports `pkg_resources`. The upstream deprecation warning may still appear on stderr. The tested environment used Resemblyzer 0.1.4, Torch 2.2.2, NumPy 1.26.4, Numba 0.61.2, Setuptools 80.10.2, and faster-whisper 1.2.1. These are observed versions, not a cross-platform lockfile.

Whisper and Torch loaded incompatible OpenMP runtime copies in a single process on this host. The speaker encoder therefore runs in one persistent **spawned worker process**, separating those runtimes without an unsafe duplicate-runtime override. This is part of the implementation, not an operator workaround.

## Not established

- Live hardware capture with this new code, input level calibration, radio clock stability, or long-duration uninterrupted operation.
- Windows/Linux device capture or optional-package installation.
- Recognition of actual enrolled people, multi-speaker conversations, cross-radio robustness, or spoof/replay resistance.
- Word error rate, false transcription rate, speech-gate precision/recall, false speaker acceptance/rejection, or confidence calibration.
- Performance of the default Whisper `base` model on this host; the actual model smoke test used `tiny.en`.
- Any safety-critical or emergency-use suitability.

The existing receiver/monitor is not reconfigured or replaced by creating this project. Use the [acceptance experiment](ARCHITECTURE.md) before making field-performance claims.
