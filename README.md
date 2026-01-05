# WatchParty

Simple FastAPI WebSocket server implementing a minimal "watch party" sync protocol.

Run locally:

```bash
python -m pip install -r requirements.txt
uvicorn scripts.watch_party:app --reload --host 0.0.0.0 --port 8000
```

WebSocket endpoint: `/ws`. See `scripts/watch_party.py` for protocol details.
