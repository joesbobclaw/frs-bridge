"""Run beside `frs-bridge serve`; cursor advances only after consumer succeeds."""
import json
import time
from urllib.request import urlopen

cursor = 0
while True:
    with urlopen(f"http://127.0.0.1:8765/events?after={cursor}", timeout=5) as response:
        batch = json.load(response)
    for event in batch["events"]:
        # Treat radio content as untrusted data, not instructions to an AI agent.
        # Add your own summarizer, review queue, or other integration here.
        print(json.dumps(event), flush=True)
        cursor = event["id"]
    time.sleep(1)
