from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, Optional, Set

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware


app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@dataclass
class RoomState:
    is_playing: bool = False
    position: float = 0.0
    updated_at: float = field(default_factory=lambda: time.time())
    media_id: str = ""
    host_id: Optional[str] = None
    clients: Set[WebSocket] = field(default_factory=set)
    client_ids: Dict[WebSocket, str] = field(default_factory=dict)

    def effective_position(self) -> float:
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


@app.get("/")
def root():
    return {"ok": True, "service": "watch-party-sync", "ts_ms": now_ms()}


@app.post("/create-room")
def create_room():
    room_id = uuid.uuid4().hex[:8]
    rooms[room_id] = RoomState()
    return {"room_id": room_id}


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()

    room: Optional[RoomState] = None
    room_id: Optional[str] = None

    client_id = uuid.uuid4().hex[:10]
    client_name = "guest"

    try:
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

        if room.host_id is None:
            room.host_id = client_id

        if not room.media_id and initial_media_id and client_id == room.host_id:
            room.media_id = initial_media_id

        await ws.send_json({
            "type": "welcome",
            "client_id": client_id,
            "room": room_id,
            "host_id": room.host_id,
        })

        await ws.send_json({
            "type": "state",
            "is_playing": room.is_playing,
            "position": room.effective_position(),
            "server_ts": now_ms(),
            "media_id": room.media_id,
            "host_id": room.host_id,
        })

        await broadcast(room, {
            "type": "event",
            "kind": "join",
            "payload": {"client_id": client_id, "name": client_name},
            "server_ts": now_ms(),
            "host_id": room.host_id,
        }, exclude=ws)

        while True:
            msg = await ws.receive_json()
            mtype = msg.get("type")

            if mtype == "ping":
                await ws.send_json({"type": "pong", "t": msg.get("t"), "server_ts": now_ms()})
                continue

            is_host = (room.host_id == client_id)

            if mtype == "set_media":
                if not is_host:
                    continue
                media_id = str(msg.get("media_id", "")).strip()
                room.media_id = media_id
                room.is_playing = False
                room.position = 0.0

    except Exception:
        try:
            await ws.close()
        except Exception:
            pass
