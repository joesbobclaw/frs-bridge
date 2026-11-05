"""Continuous FFmpeg PCM capture with bounded background processing."""
from datetime import datetime, timezone
from pathlib import Path
import queue
import subprocess
import sys
import threading
import uuid
from .core import RATE, write_wav


def input_args(backend, device):
    return ["-f", backend, "-i", device]


def capture(store, backend, device, seconds, consume):
    jobs = queue.Queue(maxsize=8)
    def worker():
        while True:
            job = jobs.get()
            try:
                if job is None:
                    return
                path, started = job
                try:
                    consume(path, started)
                except Exception:
                    store.emit({"type": "processing.error", "recording": str(path.relative_to(store.root))})
            finally:
                jobs.task_done()
    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    command = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", *input_args(backend, device),
               "-ac", "1", "-ar", str(RATE), "-f", "s16le", "pipe:1"]
    process = subprocess.Popen(command, stdout=subprocess.PIPE)
    directory = store.root / "recordings"
    directory.mkdir(exist_ok=True)
    size = int(RATE * 2 * seconds)
    buffer = bytearray()
    started = datetime.now(timezone.utc).isoformat()
    def finish():
        if not buffer:
            return
        path = directory / (uuid.uuid4().hex + ".wav")
        write_wav(path, buffer)
        store.emit({"type": "capture.saved", "recording": str(path.relative_to(store.root)),
                    "captured_at": started, "duration_seconds": len(buffer)/(RATE*2)})
        try:
            jobs.put_nowait((path, started))
        except queue.Full:
            store.emit({"type": "processing.skipped", "reason": "backlog_full",
                        "recording": str(path.relative_to(store.root))})
        buffer.clear()
    try:
        while True:
            block = process.stdout.read(min(3200, size-len(buffer)))
            if not block:
                break
            buffer.extend(block)
            if len(buffer) == size:
                finish()
                started = datetime.now(timezone.utc).isoformat()
    except KeyboardInterrupt:
        print("Stopping capture; draining queued clips...", file=sys.stderr)
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        finish()
        jobs.put(None)
        thread.join()
        process.stdout.close()
    if process.returncode not in (0, -15, 255):
        raise RuntimeError(f"Capture process exited {process.returncode}; check audio device and permissions")
