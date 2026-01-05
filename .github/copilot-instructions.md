# Copilot / AI agent instructions

Purpose: give an AI coding agent the minimal, concrete context to be productive in this repository.

Quick start
- Install Python deps: `python -m pip install -r requirements.txt`.
- Run server locally: `uvicorn scripts.watch_party:app --reload --port 8000`.

Architecture (what to know)
- Single FastAPI app in `scripts/watch_party.py` exposing a WebSocket `/ws` and small HTTP helpers (`/`, `/create-room`).
- In-memory rooms: `rooms: Dict[str, RoomState]` — no DB or persistence.

Data flow and conventions
- WebSocket first message: `{"type":"join","room":"...","name":"...","want_host":bool,"media_id":"..."}`.
- Host (controller) is identified by `host_id` assigned on join. Only host messages change playback state (`set_media`, `play`, `pause`, `seek`).

Project-specific gotchas
- State is in-memory; restarting the server loses rooms.
- No auth — think carefully before exposing to the public.

Files to check
- `scripts/watch_party.py` — main server and protocol.
- `requirements.txt` — runtime deps.
- `README.md` — run instructions.
