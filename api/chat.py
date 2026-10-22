
import json
import os
import mimetypes
import time
import re
from datetime import datetime, timezone
from urllib.parse import urlparse, unquote, parse_qs
from http.server import BaseHTTPRequestHandler
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from bson import ObjectId
from pymongo import MongoClient, DESCENDING

API_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
MODEL = "nvidia/nemotron-3-ultra-550b-a55b"

_mongo_client = None


def get_db():
    global _mongo_client

    uri = os.environ.get("MONGODB_URI")
    if not uri:
        raise RuntimeError("MONGODB_URI is missing.")

    if _mongo_client is None:
        _mongo_client = MongoClient(
            uri,
            serverSelectionTimeoutMS=5000,
            connectTimeoutMS=5000,
            appname="NOVA-AI",
        )

    db = _mongo_client["nova_ai"]
    db.chats.create_index([("guestId", 1), ("updatedAt", DESCENDING)])
    db.messages.create_index([("chatId", 1), ("createdAt", 1)])
    return db


def valid_guest_id(value):
    return isinstance(value, str) and bool(
        re.fullmatch(r"[a-fA-F0-9-]{36}", value)
    )


def valid_chat_id(value):
    return isinstance(value, str) and ObjectId.is_valid(value)


def now():
    return datetime.now(timezone.utc)


class handler(BaseHTTPRequestHandler):

    def do_POST(self):
        if urlparse(self.path).path.rstrip("/") != "/api/chat":
            return self._send(404, {"error": "Not found."})

        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 100_000:
                return self._send(400, {"error": "Invalid request size."})

            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            action = payload.get("action", "chat")

            if action != "chat":
                return self._history_action(action, payload)

            return self._chat(payload)

        except HTTPError as exc:
            try:
                detail = exc.read().decode("utf-8")[:700]
            except Exception:
                detail = ""

            if exc.code in (401, 403):
                return self._send(502, {
                    "error": "NVIDIA rejected the API key or model access. "
                             "Check NVIDIA_API_KEY and model permissions. "
                             + detail
                })

            if exc.code == 429:
                return self._send(429, {
                    "error": "NVIDIA usage limit reached. Try again later. "
                             + detail
                })

            if exc.code in (502, 503, 504):
                return self._send(503, {
                    "error": "NVIDIA is temporarily unavailable. "
                             + detail
                })

            return self._send(502, {
                "error": f"NVIDIA API error (HTTP {exc.code}). {detail}"
            })

        except (URLError, TimeoutError):
            return self._send(504, {
                "error": "NVIDIA timed out or could not be reached."
            })

        except (ValueError, KeyError, IndexError, TypeError):
            return self._send(400, {"error": "Invalid request."})

        except Exception as exc:
            # Do not expose database connection strings or secrets.
            print("NOVA server error:", type(exc).__name__)
            return self._send(500, {
                "error": "Server error. Check the Vercel function logs."
            })

    def _chat(self, payload):
        token = os.environ.get("NVIDIA_API_KEY")
        if not token:
            return self._send(500, {
                "error": "NVIDIA_API_KEY is missing in Vercel settings."
            })

        messages = payload.get("messages", [])
        if not isinstance(messages, list) or not messages:
            return self._send(400, {
                "error": "Send at least one message."
            })

        clean = [{
            "role": "system",
            "content": (
                "You are NOVA AI, a helpful, clear, practical assistant. "
                "Use concise answers by default. Format code in Markdown "
                "code fences. If uncertain, say so."
            )
        }]

        for msg in messages[-16:]:
            if not isinstance(msg, dict):
                continue

            role = msg.get("role")
            content = msg.get("content")

            if role not in ("user", "assistant"):
                continue
            if not isinstance(content, str):
                continue

            clean.append({
                "role": role,
                "content": content[:6000]
            })

        if len(clean) == 1:
            return self._send(400, {
                "error": "No valid messages provided."
            })

        body = json.dumps({
            "model": MODEL,
            "messages": clean,
            "max_tokens": 2048,
            "temperature": 0.7,
            "stream": False,
            "chat_template_kwargs": {"enable_thinking": False}
        }).encode("utf-8")

        req = Request(
            API_URL,
            data=body,
            headers={
                "Authorization": "Bearer " + token,
                "Content-Type": "application/json",
                "Accept": "application/json"
            },
            method="POST"
        )

        result = None
        for attempt in range(3):
            try:
                with urlopen(req, timeout=25) as resp:
                    result = json.loads(resp.read().decode("utf-8"))
                break
            except HTTPError as exc:
                if exc.code in (502, 503, 504) and attempt < 2:
                    time.sleep(1 + attempt * 2)
                    continue
                raise

        if result is None:
            return self._send(502, {
                "error": "NVIDIA did not return a response."
            })

        choices = result.get("choices", [])
        if not choices:
            return self._send(502, {
                "error": "NVIDIA returned no response choices."
            })

        reply = choices[0].get("message", {}).get("content")
        if not isinstance(reply, str) or not reply.strip():
            return self._send(502, {
                "error": "NVIDIA returned an empty answer. Try again."
            })

        reply = reply.strip()

        # Persist history only when the frontend supplies guestId + chatId.
        guest_id = payload.get("guestId")
        chat_id = payload.get("chatId")

        if guest_id and chat_id:
            if not valid_guest_id(guest_id) or not valid_chat_id(chat_id):
                return self._send(400, {
                    "error": "Invalid guest or chat ID."
                })

            db = get_db()
            oid = ObjectId(chat_id)
            chat = db.chats.find_one({
                "_id": oid,
                "guestId": guest_id
            })

            if not chat:
                return self._send(404, {
                    "error": "Chat not found. Create a chat first."
                })

            # Save the current conversation snapshot sent by the frontend.
            saved = []
            for msg in clean[1:]:
                saved.append({
                    "chatId": oid,
                    "guestId": guest_id,
                    "role": msg["role"],
                    "content": msg["content"],
                    "createdAt": now()
                })

            saved.append({
                "chatId": oid,
                "guestId": guest_id,
                "role": "assistant",
                "content": reply,
                "createdAt": now()
            })

            db.messages.delete_many({"chatId": oid, "guestId": guest_id})
            if saved:
                db.messages.insert_many(saved)

            first_user = next(
                (m["content"] for m in clean[1:] if m["role"] == "user"),
                "New chat"
            )
            db.chats.update_one(
                {"_id": oid, "guestId": guest_id},
                {"$set": {
                    "title": first_user[:60],
                    "updatedAt": now()
                }}
            )

        return self._send(200, {"reply": reply})

    def _history_action(self, action, payload):
        guest_id = payload.get("guestId")
        if not valid_guest_id(guest_id):
            return self._send(400, {"error": "Invalid guest ID."})

        db = get_db()

        if action == "create":
            timestamp = now()
            result = db.chats.insert_one({
                "guestId": guest_id,
                "title": "New chat",
                "createdAt": timestamp,
                "updatedAt": timestamp
            })
            return self._send(201, {
                "chatId": str(result.inserted_id),
                "title": "New chat"
            })

        if action == "list":
            chats = list(
                db.chats.find({"guestId": guest_id})
                .sort("updatedAt", DESCENDING)
                .limit(100)
            )
            return self._send(200, {
                "chats": [{
                    "chatId": str(c["_id"]),
                    "title": c.get("title", "New chat"),
                    "createdAt": c["createdAt"].isoformat(),
                    "updatedAt": c["updatedAt"].isoformat()
                } for c in chats]
            })

        chat_id = payload.get("chatId")
        if not valid_chat_id(chat_id):
            return self._send(400, {"error": "Invalid chat ID."})

        oid = ObjectId(chat_id)
        owned_chat = db.chats.find_one({
            "_id": oid,
            "guestId": guest_id
        })

        if not owned_chat:
            return self._send(404, {"error": "Chat not found."})

        if action == "load":
            messages = list(
                db.messages.find({
                    "chatId": oid,
                    "guestId": guest_id
                }).sort("createdAt", 1).limit(500)
            )
            return self._send(200, {
                "chatId": chat_id,
                "messages": [{
                    "role": m["role"],
                    "content": m["content"]
                } for m in messages]
            })

        if action == "delete":
            db.messages.delete_many({
                "chatId": oid,
                "guestId": guest_id
            })
            db.chats.delete_one({
                "_id": oid,
                "guestId": guest_id
            })
            return self._send(200, {"deleted": True})

        return self._send(400, {"error": "Unknown action."})

    def do_GET(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)

        # History can be read using GET query parameters too.
        if path.rstrip("/") == "/api/chat":
            params = parse_qs(parsed.query)
            action = params.get("action", [""])[0]
            guest_id = params.get("guestId", [""])[0]

            if action in ("list", "load"):
                payload = {
                    "action": action,
                    "guestId": guest_id
                }
                if action == "load":
                    payload["chatId"] = params.get("chatId", [""])[0]
                return self._history_get(payload)

            return self._send(405, {
                "error": "Use POST for chat requests."
            })

        relative_path = "index.html" if path == "/" else path.lstrip("/")
        root = os.path.realpath(os.getcwd())
        target = os.path.realpath(os.path.join(root, relative_path))

        if os.path.commonpath([root, target]) != root:
            return self._send(403, {"error": "Forbidden"})
        if not os.path.isfile(target):
            return self._send(404, {"error": "File not found"})

        content_type = mimetypes.guess_type(target)[0] or "application/octet-stream"
        try:
            with open(target, "rb") as file:
                data = file.read()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(data)
        except OSError:
            return self._send(500, {"error": "Could not read the requested file."})

    def _history_get(self, payload):
        guest_id = payload.get("guestId")
        if not valid_guest_id(guest_id):
            return self._send(400, {"error": "Invalid guest ID."})

        db = get_db()
        action = payload["action"]

        if action == "list":
            chats = list(
                db.chats.find({"guestId": guest_id})
                .sort("updatedAt", DESCENDING)
                .limit(100)
            )
            return self._send(200, {
                "chats": [{
                    "chatId": str(c["_id"]),
                    "title": c.get("title", "New chat"),
                    "createdAt": c["createdAt"].isoformat(),
                    "updatedAt": c["updatedAt"].isoformat()
                } for c in chats]
            })

        chat_id = payload.get("chatId")
        if not valid_chat_id(chat_id):
            return self._send(400, {"error": "Invalid chat ID."})

        oid = ObjectId(chat_id)
        if not db.chats.find_one({"_id": oid, "guestId": guest_id}):
            return self._send(404, {"error": "Chat not found."})

        messages = list(
            db.messages.find({"chatId": oid, "guestId": guest_id})
            .sort("createdAt", 1).limit(500)
        )
        return self._send(200, {
            "chatId": chat_id,
            "messages": [{
                "role": m["role"],
                "content": m["content"]
            } for m in messages]
        })

    def _send(self, status, data):
        encoded = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)
