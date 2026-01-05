from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, Optional, Set, Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware


app = FastAPI()

# If you serve the client from a different origin, CORS may matter for non-WS endpoints.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -----------------------------
# In-memory room state (simple)
# -----------------------------

@dataclass
class RoomState:
    is_playing: bool = False
    position: float = 0.0          # seconds
    updated_at: float = field(default_factory=lambda: time.time())  # server time of last state change
    media_id: str = ""             # arbitrary identifier (e.g., filename hash or URL)
    host_id: Optional[str] = None  # client_id of the host/controller
    clients: Set[WebSocket] = field(default_factory=set)
    client_ids: Dict[WebSocket, str] = field(default_factory=dict)

    def effective_position(self) -> float:
        """If playing, position advances with time since updated_at."""
        if not self.is_playing:
            return self.position
        return self.position + (time.time() - self.updated_at)


rooms: Dict[str, RoomState] = {}


def now_ms() -> int:
    return int(time.time() * 1000)


async def broadcast(room: RoomState, msg: dict, exclude: Optional[WebSocket] = None):
    dead = []
    for ws in list(room.clients):
        if exclude is not None and ws is exclude:
            continue
        try:
            await ws.send_json(msg)
        except Exception:
            dead.append(ws)
    for ws in dead:
        room.clients.discard(ws)
        room.client_ids.pop(ws, None)


def require_room(room_id: str) -> RoomState:
    if room_id not in rooms:
        rooms[room_id] = RoomState()
    return rooms[room_id]


# -----------------------------
# Optional tiny endpoints
# -----------------------------

@app.get("/")
def root():
    return {"ok": True, "service": "watch-party-sync", "ts_ms": now_ms()}


@app.post("/create-room")
def create_room():
    room_id = uuid.uuid4().hex[:8]
    rooms[room_id] = RoomState()
    return {"room_id": room_id}


# -----------------------------
# WebSocket protocol
# -----------------------------
# Client -> Server messages:
#   {"type":"join","room":"abcd1234","name":"Sasan","want_host":true/false,"media_id":"..."}
#   {"type":"set_media","media_id":"..."}                    (host only)
#   {"type":"play","at":123.4}                               (host only)
#   {"type":"pause","at":123.4}                              (host only)
#   {"type":"seek","to":200.0,"playing":true/false}          (host only)
#   {"type":"ping","t":<client_ms>}                          (any)
#
# Server -> Client messages:
#   {"type":"welcome","client_id":"...","room":"...","host_id":"..."}
#   {"type":"state","is_playing":...,"position":...,"server_ts":...,"media_id":"...","host_id":"..."}
#   {"type":"event","kind":"play/pause/seek/set_media","payload":...,"server_ts":...,"host_id":"..."}
#   {"type":"pong","t":<client_ms>,"server_ts":...}

@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()

    room: Optional[RoomState] = None
    room_id: Optional[str] = None

    client_id = uuid.uuid4().hex[:10]
    client_name = "guest"

    try:
        # First message MUST be join
        join = await ws.receive_json()
        if join.get("type") != "join":
            await ws.close(code=1002)
            return

        room_id = str(join.get("room", "")).strip()
        if not room_id:
            await ws.close(code=1008)
            return

        client_name = str(join.get("name", "guest"))[:40]
        want_host = bool(join.get("want_host", False))
        initial_media_id = str(join.get("media_id", "")).strip()

        room = require_room(room_id)
        room.clients.add(ws)
        room.client_ids[ws] = client_id

        # Assign host if none, or if want_host and host is missing (simple policy).
        if room.host_id is None:
            room.host_id = client_id
        elif want_host and room.host_id is None:
            room.host_id = client_id

        # If room has no media_id yet and a joiner provides one, accept it only if host.
        if not room.media_id and initial_media_id and client_id == room.host_id:
            room.media_id = initial_media_id

        await ws.send_json({
            "type": "welcome",
            "client_id": client_id,
            "room": room_id,
            "host_id": room.host_id,
        })

        # Send current state to this client
        await ws.send_json({
            "type": "state",
            "is_playing": room.is_playing,
            "position": room.effective_position(),
            "server_ts": now_ms(),
            "media_id": room.media_id,
            "host_id": room.host_id,
        })

        # Notify others someone joined (optional)
        await broadcast(room, {
            "type": "event",
            "kind": "join",
            "payload": {"client_id": client_id, "name": client_name},
            "server_ts": now_ms(),
            "host_id": room.host_id,
        }, exclude=ws)

        # Main loop
        while True:
            msg = await ws.receive_json()
            mtype = msg.get("type")

            if mtype == "ping":
                await ws.send_json({"type": "pong", "t": msg.get("t"), "server_ts": now_ms()})
                continue

            # Only host can control playback state
            is_host = (room.host_id == client_id)

            if mtype == "set_media":
                if not is_host:
                    continue
                media_id = str(msg.get("media_id", "")).strip()
                room.media_id = media_id
                # Reset to start on media change
                room.is_playing = False
                room.position = 0.0
