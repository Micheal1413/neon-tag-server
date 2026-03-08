"""
╔══════════════════════════════════════════════════════╗
║        NEON TAG  —  WebSocket Relay Server           ║
╠══════════════════════════════════════════════════════╣
║  Run locally:  python neon_tag_server.py             ║
║  Needs:        pip install websockets                ║
║                                                      ║
║  DEPLOY FREE (Render.com):                           ║
║    1. Push this repo to GitHub                       ║
║    2. render.com → New Web Service → link repo       ║
║    3. It auto-reads render.yaml — done!              ║
║    4. Your URL: wss://your-app.onrender.com          ║
║                                                      ║
║  Players do NOT need to be on the same network!      ║
║  Just share the 4-letter room code.                  ║
╚══════════════════════════════════════════════════════╝

Protocol (all JSON):
  Client→Server:  {"t":"create"}  |  {"t":"join","code":"abcd"}
                  {"t":"state",...} | {"t":"input",...}  (relay)
                  {"t":"ping"}     (latency measurement)
  Server→Client:  {"t":"ok","code":"abcd","role":"host"}
                  {"t":"ok","role":"guest"}
                  {"t":"partner_joined"}
                  {"t":"partner_left"}
                  {"t":"pong","ts":<client_ts>}
                  {"t":"err","msg":"..."}
"""

import asyncio
import json
import os
import random
import sys
import time
from http import HTTPStatus

try:
    import websockets
    # websockets v13+ prefers top-level import
    try:
        from websockets import serve
    except ImportError:
        from websockets.server import serve
except ImportError:
    print("ERROR: websockets not installed.  Run:  pip install websockets")
    sys.exit(1)

# ─────────────────────────────────────────────────────────────────────────────
#  ROOMS
# ─────────────────────────────────────────────────────────────────────────────

# rooms[code] = {"host": ws, "guest": ws|None, "last_active": timestamp}
rooms: dict = {}

LETTERS = "abcdefghijklmnopqrstuvwxyz"
ROOM_TIMEOUT = 600  # 10 minutes — auto-delete stale rooms


def gen_code() -> str:
    """Generate a unique 4-letter lowercase room code."""
    for _ in range(1000):
        code = "".join(random.choices(LETTERS, k=4))
        if code not in rooms:
            return code
    raise RuntimeError("No codes available – server full?")


# ─────────────────────────────────────────────────────────────────────────────
#  ROOM CLEANUP (background task)
# ─────────────────────────────────────────────────────────────────────────────

async def cleanup_stale_rooms() -> None:
    """Periodically remove rooms that haven't had activity in ROOM_TIMEOUT seconds."""
    while True:
        await asyncio.sleep(60)  # check every minute
        now = time.time()
        stale = [code for code, room in rooms.items()
                 if now - room.get("last_active", now) > ROOM_TIMEOUT]
        for code in stale:
            room = rooms.pop(code, None)
            if room:
                for role in ("host", "guest"):
                    ws = room.get(role)
                    if ws:
                        try:
                            await ws.close(1000, "Room timed out")
                        except Exception:
                            pass
                print(f"[~] Room '{code}' cleaned up (stale)")


# ─────────────────────────────────────────────────────────────────────────────
#  HEALTH CHECK — HTTP handler for cloud platforms
# ─────────────────────────────────────────────────────────────────────────────

async def health_check(path, request_headers):
    """Respond to plain HTTP requests with 200 OK (health check for Render/Railway).
    Return None to proceed with normal WebSocket upgrade."""
    # Check if this looks like a normal HTTP request (not a WebSocket upgrade)
    if "Upgrade" not in request_headers:
        body = json.dumps({
            "status": "ok",
            "service": "neon-tag-relay",
            "rooms": len(rooms),
            "players": sum(
                (1 if r.get("host") else 0) + (1 if r.get("guest") else 0)
                for r in rooms.values()
            ),
        }).encode()
        return HTTPStatus.OK, [("Content-Type", "application/json")], body
    return None


# ─────────────────────────────────────────────────────────────────────────────
#  WEBSOCKET HANDLER
# ─────────────────────────────────────────────────────────────────────────────

async def handler(ws) -> None:
    role: str | None = None
    code: str | None = None

    try:
        async for raw in ws:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            t = msg.get("t", "")

            # ── CREATE ROOM ───────────────────────────────────────────────────
            if t == "create":
                code = gen_code()
                rooms[code] = {"host": ws, "guest": None, "last_active": time.time()}
                role = "host"
                await ws.send(json.dumps({"t": "ok", "code": code, "role": "host"}))
                print(f"[+] Room '{code}' created  (active rooms: {len(rooms)})")

            # ── JOIN ROOM ─────────────────────────────────────────────────────
            elif t == "join":
                requested = str(msg.get("code", "")).strip().lower()[:4]
                if requested not in rooms:
                    await ws.send(json.dumps({"t": "err", "msg": "Room not found"}))
                elif rooms[requested]["guest"] is not None:
                    await ws.send(json.dumps({"t": "err", "msg": "Room is full"}))
                else:
                    code = requested
                    rooms[code]["guest"] = ws
                    rooms[code]["last_active"] = time.time()
                    role = "guest"
                    await ws.send(json.dumps({"t": "ok", "role": "guest"}))
                    # Notify host that their partner joined
                    host_ws = rooms[code]["host"]
                    try:
                        await host_ws.send(json.dumps({"t": "partner_joined"}))
                    except Exception:
                        pass
                    print(f"[+] Guest joined room '{code}'  (active rooms: {len(rooms)})")

            # ── PING (latency measurement) ────────────────────────────────────
            elif t == "ping":
                ts = msg.get("ts", 0)
                await ws.send(json.dumps({"t": "pong", "ts": ts}))
                if code and code in rooms:
                    rooms[code]["last_active"] = time.time()

            # ── RELAY MESSAGE ─────────────────────────────────────────────────
            elif t in ("state", "input", "map") and code and code in rooms:
                room = rooms[code]
                room["last_active"] = time.time()
                target = room["guest"] if role == "host" else room["host"]
                if target is not None:
                    try:
                        await target.send(raw)
                    except Exception:
                        pass

    except websockets.exceptions.ConnectionClosed:
        pass
    except Exception as e:
        print(f"[!] Handler error: {e}")

    finally:
        # ── CLEANUP on disconnect ─────────────────────────────────────────────
        if code and code in rooms:
            room = rooms[code]
            other_ws = room["guest"] if role == "host" else room["host"]
            if other_ws is not None:
                try:
                    await other_ws.send(json.dumps({"t": "partner_left"}))
                except Exception:
                    pass
            del rooms[code]
            print(f"[-] Room '{code}' closed ({role} disconnected)  (active rooms: {len(rooms)})")


# ─────────────────────────────────────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────────────────────────────────────

async def main() -> None:
    port = int(os.environ.get("PORT", 8765))
    host = "0.0.0.0"

    print(f"╔══════════════════════════════════════════════╗")
    print(f"║   Neon Tag Relay Server                      ║")
    print(f"║   Listening on  ws://{host}:{port:<5}             ║")
    print(f"║   Health check: http://{host}:{port:<5}/           ║")
    print(f"╚══════════════════════════════════════════════╝")
    print()
    print("Players connect from ANY network using room codes.")
    print("Waiting for players …\n")

    # Start stale room cleanup
    asyncio.create_task(cleanup_stale_rooms())

    async with serve(
        handler, host, port,
        process_request=health_check,
        ping_interval=20,
        ping_timeout=20,
        close_timeout=10,
        max_size=2**16,         # 64KB max message (plenty for game state)
        compression=None,       # disable compression for lower latency
    ):
        await asyncio.Future()  # run forever


if __name__ == "__main__":
    asyncio.run(main())
