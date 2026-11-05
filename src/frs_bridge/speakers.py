"""Opt-in local speaker embeddings; unknown is a first-class result."""
import json
import math
from pathlib import Path
import re
from contextlib import redirect_stdout
import sys
import atexit
import multiprocessing


def unit(vector):
    values = [float(v) for v in vector]
    norm = math.sqrt(sum(v*v for v in values))
    if not values or not math.isfinite(norm) or norm < 1e-9:
        raise ValueError("Invalid voice embedding")
    return [v/norm for v in values]


class _LocalEncoder:
    def __init__(self):
        from resemblyzer import VoiceEncoder
        with redirect_stdout(sys.stderr):
            self.encoder = VoiceEncoder(device="cpu")

    def __call__(self, path):
        from resemblyzer import preprocess_wav
        wav = preprocess_wav(Path(path))
        if len(wav) < 16000 * 3:
            raise ValueError("Need at least three seconds of speech after silence removal")
        return unit(self.encoder.embed_utterance(wav))


def _encoder_worker(connection):
    """Isolate Torch from Whisper's separate OpenMP runtime."""
    try:
        encoder = _LocalEncoder()
        connection.send((True, None))
        while True:
            path = connection.recv()
            if path is None:
                break
            try:
                connection.send((True, encoder(path)))
            except Exception as error:
                connection.send((False, f"{type(error).__name__}: {error}"))
    except EOFError:
        pass
    except Exception as error:
        connection.send((False, f"{type(error).__name__}: {error}"))
    finally:
        connection.close()


class Encoder:
    """One persistent CPU worker, with no ML imports in the calling process."""
    def __init__(self):
        context = multiprocessing.get_context("spawn")
        self.connection, child = context.Pipe()
        self.worker = context.Process(target=_encoder_worker, args=(child,), daemon=True)
        self.worker.start()
        child.close()
        atexit.register(self.close)
        self._receive()

    def _receive(self):
        if not self.connection.poll(120):
            self.close()
            raise RuntimeError("Speaker encoder timed out")
        try:
            success, result = self.connection.recv()
        except EOFError as error:
            raise RuntimeError("Speaker encoder worker stopped") from error
        if not success:
            raise RuntimeError(result)
        return result

    def __call__(self, path):
        self.connection.send(str(path))
        return self._receive()

    def close(self):
        if self.worker.is_alive():
            self.worker.terminate()
            self.worker.join(timeout=5)
        self.connection.close()


class Registry:
    def __init__(self, root):
        self.path = Path(root) / "voiceprints.json"

    def load(self):
        return json.loads(self.path.read_text()) if self.path.exists() else {}

    def save(self, data):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, indent=2) + "\n")
        temporary.chmod(0o600)
        temporary.replace(self.path)

    def enroll(self, label, paths, encoder):
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,40}", label):
            raise ValueError("Use a pseudonymous label: letters, digits, dash or underscore")
        if len(paths) < 2:
            raise ValueError("Enroll with at least two separate recordings")
        vectors = [unit(encoder(path)) for path in paths]
        if len({len(v) for v in vectors}) != 1:
            raise ValueError("Embedding dimensions disagree")
        centroid = unit([sum(row[i] for row in vectors)/len(vectors) for i in range(len(vectors[0]))])
        data = self.load()
        data[label] = {"embedding": centroid, "samples": len(vectors), "engine": "resemblyzer"}
        self.save(data)

    def delete(self, label):
        data = self.load()
        existed = data.pop(label, None) is not None
        self.save(data)
        return existed

    def match(self, path, encoder, threshold=0.75, margin=0.08):
        if not 0 <= threshold <= 1 or not 0 <= margin <= 1:
            raise ValueError("Threshold and margin must be in [0, 1]")
        data = self.load()
        if not data:
            return {"label": "unknown", "reason": "no_enrollments", "verified": False}
        query = unit(encoder(path))
        scores = sorted([(sum(a*b for a,b in zip(query, row["embedding"])), label)
                         for label,row in data.items() if len(row["embedding"]) == len(query)], reverse=True)
        if not scores:
            return {"label": "unknown", "reason": "incompatible_embeddings", "verified": False}
        best, label = scores[0]
        gap = best - scores[1][0] if len(scores) > 1 else None
        accepted = best >= threshold and (gap is None or gap >= margin)
        return {"label": label if accepted else "unknown", "score": round(best, 4),
                "margin": round(gap, 4) if gap is not None else None,
                "threshold": threshold, "required_margin": margin, "verified": False,
                "reason": "match" if accepted else "weak_or_ambiguous"}
