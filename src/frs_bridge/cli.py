import argparse
import json
import os
from pathlib import Path
import sys
from .core import Store, Transcriber, effect, process
from .speakers import Encoder, Registry


def parser():
    cli = argparse.ArgumentParser(description="FRS Bridge: local receive audio to AI-ready events")
    cli.add_argument("--data", type=Path, default=Path("data"), help="Private local storage directory")
    sub = cli.add_subparsers(dest="command", required=True)
    sub.add_parser("devices", help="Show FFmpeg device-listing commands")
    for name in ("process", "record"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--transcribe", action="store_true", help="Enable optional local Whisper")
        cmd.add_argument("--model", default="base")
        cmd.add_argument("--language", help="Optional language code, e.g. en (not language translation)")
        cmd.add_argument("--threshold", type=float, default=-45, help="Speech candidate energy floor, dBFS")
        cmd.add_argument("--identify", action="store_true", help="Enable optional local voiceprint matching")
        cmd.add_argument("--speaker-threshold", type=float, default=0.75)
        cmd.add_argument("--speaker-margin", type=float, default=0.08)
        if name == "process":
            cmd.add_argument("file", type=Path)
        else:
            cmd.add_argument("--backend", choices=["avfoundation", "alsa", "pulse", "dshow"], required=True)
            cmd.add_argument("--device", required=True, help="FFmpeg input selector, e.g. :2 or hw:1,0")
            cmd.add_argument("--seconds", type=int, default=15, choices=range(5, 30), metavar="5..29")
    cmd = sub.add_parser("serve", help="Read-only API bound to 127.0.0.1")
    cmd.add_argument("--port", type=int, default=8765)
    cmd = sub.add_parser("export", help="JSONL event feed to stdout")
    cmd.add_argument("--after", type=int, default=0)
    cmd = sub.add_parser("effect", help="Pitch-shift a local playback file, never transmit")
    cmd.add_argument("input", type=Path)
    cmd.add_argument("output", type=Path)
    cmd.add_argument("--semitones", type=float, default=0)
    cmd = sub.add_parser("enroll", help="Enroll a consenting speaker using at least two speech clips")
    cmd.add_argument("label")
    cmd.add_argument("files", type=Path, nargs="+")
    cmd.add_argument("--consent", action="store_true", required=True, help="Confirm speaker agreed to enrollment")
    cmd = sub.add_parser("identify", help="Match a clip against local enrolled speakers")
    cmd.add_argument("file", type=Path)
    cmd.add_argument("--threshold", type=float, default=0.75)
    cmd.add_argument("--margin", type=float, default=0.08)
    sub.add_parser("speakers", help="List enrolled pseudonymous labels (no embeddings)")
    cmd = sub.add_parser("forget", help="Delete one local voiceprint (does not delete recordings/events)")
    cmd.add_argument("label")
    return cli


def main():
    args = parser().parse_args()
    os.umask(0o077)
    try:
        if args.command == "devices":
            print('macOS: ffmpeg -f avfoundation -list_devices true -i ""\n'
                  'Linux ALSA: arecord -l\nLinux PulseAudio: pactl list short sources\n'
                  'Windows: ffmpeg -list_devices true -f dshow -i dummy')
            return 0
        if args.command == "effect":
            if args.input.resolve() == args.output.resolve():
                raise ValueError("Output must differ from input; preserve original evidence")
            effect(args.input, args.output, args.semitones)
            return 0
        store = Store(args.data)
        registry = Registry(args.data)
        if args.command == "serve":
            from .api import server
            print(f"Read-only event API: http://127.0.0.1:{args.port}", flush=True)
            with server(store, args.port) as api:
                api.serve_forever()
        elif args.command == "export":
            cursor = args.after
            while rows := store.events(cursor, 1000):
                for row in rows:
                    print(json.dumps(row))
                cursor = rows[-1]["id"]
        elif args.command == "enroll":
            registry.enroll(args.label, args.files, Encoder())
            print(json.dumps({"enrolled": args.label, "samples": len(args.files)}))
        elif args.command == "speakers":
            print(json.dumps({"speakers": [{"label": label, "samples": row["samples"]}
                                           for label, row in registry.load().items()]}))
        elif args.command == "forget":
            print(json.dumps({"deleted": registry.delete(args.label)}))
        elif args.command == "identify":
            print(json.dumps(registry.match(args.file, Encoder(), args.threshold, args.margin)))
        else:
            transcriber = Transcriber(args.model, args.language) if args.transcribe else None
            encoder = Encoder() if args.identify else None
            matcher = (lambda path: registry.match(path, encoder, args.speaker_threshold, args.speaker_margin)) if encoder else None
            def consume(path, captured_at=None):
                event = process(store, path, transcriber, args.threshold, captured_at, matcher)
                print(json.dumps(event), flush=True)
            if args.command == "process":
                consume(args.file)
            elif args.command == "record":
                from .capture import capture
                capture(store, args.backend, args.device, args.seconds, consume)
        return 0
    except KeyboardInterrupt:
        return 0
    except (ImportError, FileNotFoundError) as error:
        print(f"Missing dependency or file: {error}. See README installation instructions.", file=sys.stderr)
        return 1
    except Exception as error:
        print(f"{type(error).__name__}: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
