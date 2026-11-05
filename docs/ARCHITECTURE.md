# Architecture and evaluation

## Boundaries

The hardware receiver turns RF into audio. FFmpeg turns an OS audio source into 16 kHz mono PCM16. The main capture loop writes short WAV segments and durably records their paths. One bounded processing thread normalizes audio, evaluates heuristic activity, and optionally runs local STT. A separate persistent spawned process handles speaker embeddings, isolating Torch's OpenMP runtime from Whisper's runtime. SQLite provides monotonic event IDs and concurrent read access. The loopback HTTP API and JSONL export are the application boundary.

No credentials, messaging provider, radio location, real voice enrollment, or actual recordings belong in the repository. No PTT, transmission, shell execution from transcripts, or automatic downstream actions are implemented.

## Why preserve raw evidence?

Speech normalization is useful for listening but can delete or amplify meaningful details. A transcript is a model output, not the signal itself. Every analysis event links back to its raw and normalized files; `capture.saved` also preserves the original segment when later processing fails. Audio stays on disk and is never served by the built-in API.

## Known failure modes

- Wrong input device or missing permission can yield no audio.
- An audio adapter can advertise an inaccurate sample clock. Verify duration and real-time playback. No universal clock-correction factor is applied.
- Loud static can resemble speech. Whisper can hallucinate confident phrases from noise.
- The conservative sustained-signal gate can reject genuine speech; weak speech can fall below the threshold.
- Fixed chunks split speech; no diarization, cross-chunk deduplication, or automatic gain calibration exists yet.
- Speaker embeddings can mismatch over radio distortion, cross-talk, illness, or channel changes. Similarity is not a probability of identity.
- A replay can match an enrolled voice. This is recognition assistance, not anti-spoofing or authentication.
- Overload skips analysis while preserving recording files; disk exhaustion can still stop capture.
- Stop/drain waits for running ML inference. No service manager or automatic restart is installed.
- SQLite events and audio have no automatic retention policy. Backups can retain deleted biometrics.

## Acceptance experiment before real-world claims

1. Record a consented radio check. Verify selected hardware, elapsed time, no clipping, and intelligible playback; never infer these from a process merely being alive.
2. Build separate enrollment and held-out test sets per consenting participant, across sessions and realistic distance/channel conditions. Include unknown speakers.
3. Separately label clean speech, weak speech, silence, pulse clicks, sustained interference, overlaps, and replayed speech.
4. Report speech-detection precision/recall, transcription word error rate on manually transcribed references, and false transcripts per hour of noise.
5. Calibrate voiceprint threshold/margin only on a development set. Report false acceptance and false rejection on a held-out set, including unknown-speaker and replay cases.
6. Measure end-to-end latency, capture continuity, disk growth, CPU/RAM use, backlog skips, and recovery after device disconnect.
7. Publish only consented, de-identified examples or synthetic fixtures. Publish methodology and aggregate metrics, not raw private communications or embeddings.

Until these runs exist, this project supports an engineering blog/prototype report, not a scientific accuracy claim.
