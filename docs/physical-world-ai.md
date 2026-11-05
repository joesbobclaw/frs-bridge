# Giving AI Ears in the Physical World

*Draft engineering blog / project report — not a peer-reviewed paper or a validated recognition benchmark.*

AI integrations usually begin with an API. A calendar has structured events. A support platform has tickets. A radio has a speaker.

That last interface is interesting. People use handheld radios precisely where a phone app may be inconvenient: coordinating a small crew, managing an outdoor activity, or working with gloves on. The conversation exists in the physical world, but most software cannot see it.

FRS Bridge is a small experiment in crossing that boundary. Connect a receiver's audio output to a local computer. Keep the recording. Extract tentative words and speaker hints. Make the result available as an event feed that another application can consume.

The ambition is not an autonomous radio operator. It is an observable, inspectable bridge between an analog interaction and software.

## The smallest useful bridge

The system does not decode radio signals directly. The receiver already does that. The computer receives audio through an ordinary audio interface, records it continuously, and keeps raw evidence beside a normalized listening copy.

Optional local models add speech-to-text and a lightweight voiceprint match against explicitly enrolled participants. A read-only local API exposes ordered events. A consumer can build a searchable log, draft a summary, or present a review queue without needing to know anything about audio drivers.

Keeping these stages separate matters. Recording must continue even if a model is slow. A failed transcript should not destroy the original audio. A guessed speaker should not quietly become an authenticated identity.

## The difficult part is knowing when not to believe it

A noise burst is not a sentence. Unfortunately, a speech model can turn one into a plausible sentence. Confidence alone does not solve this: models can be confidently wrong when their input is outside the conditions they were designed for.

FRS Bridge places a simple acoustic gate before optional transcription. It looks for sustained speech-like activity and skips some long interference candidates. These are engineering heuristics, not a claim that static has been solved. The original audio remains the reference, and every transcript is explicitly unverified.

This changes the role of the AI consumer. It is not reading an authoritative event such as “the gate is open.” It is reading evidence that an audio segment may contain those words. An application that summarizes this uncertainty is useful. One that turns it directly into physical action is a different, much harder system.

## A voiceprint is a hint, not a credential

Known-speaker matching adds context. The local registry stores compact embeddings from multiple consented recordings of each participant. New speech is compared with those embeddings. A threshold and separation margin allow the answer to be “unknown.”

Radio audio makes this harder than a clean microphone demonstration. Limited bandwidth, squelch tails, distance, interference, and the receiver's volume all change the signal. Samples need to come from the actual audio path. Thresholds must be calibrated against speakers and conditions that were not used for enrollment.

Even a strong match does not prove who is holding the transmitter. A recording can be replayed. Voiceprints are sensitive biometric data, so this design keeps them local, makes enrollment explicit, and provides deletion. They are never authorization tokens.

## Why local-first?

It makes the boundary understandable. Audio is stored on the computer. Optional inference runs there. The event API listens only on loopback. There is no default upload, notification service, or public dashboard.

This is not the same as having no costs. Continuous recordings consume disk. Models consume memory and CPU. Someone still has to manage retention and evaluate performance. Those are visible engineering constraints, not hidden dependencies on an external endpoint.

## Physical-world AI needs provenance

An API response arrives looking like data. Physical signals arrive messy. A useful bridge should preserve the distinction between the captured signal, the processing applied to it, the model's interpretation, and any action taken later.

FRS Bridge makes that distinction concrete: timestamped recording events, raw and cleaned file references, explicit transcription status, tentative speaker labels, and durable cursors for downstream consumers. The voice on the radio is also untrusted input. It cannot promote itself into an instruction for an AI agent merely by saying the right words.

The practical opportunity is broader than radios. The same pattern applies to microphones on machinery, accessibility interfaces, and other systems where a physical signal becomes software evidence. Capture first. Preserve provenance. Expose uncertainty. Keep consequential actions behind a separate decision boundary.

## What this release establishes—and what it does not

This repository is a runnable prototype with 16 passing synthetic integration checks. Actual local transcription and speaker models also completed synthetic speech smoke tests, including a held-out same-voice match and an unknown-voice rejection. It is not yet a measured live-radio study. No speaker-identification accuracy, word error rate, safety reliability, or field performance is claimed.

The next experiment is deliberately ordinary: a consented set of radio checks, held-out known and unknown speakers, realistic noise, and a report of misses as well as successes. The interesting result will not be a perfect demo. It will be learning where the bridge stops being trustworthy—and making that boundary visible to the software using it.

Source: <https://github.com/joesbobclaw/frs-bridge>

## Building blocks

- [FFmpeg](https://ffmpeg.org/): audio device input, conversion, and playback processing.
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper): local speech recognition based on Whisper.
- [Resemblyzer](https://github.com/resemble-ai/Resemblyzer): pretrained speaker embeddings.
- [Validation receipt](VALIDATION.md): observed checks and the limits of this prototype.
