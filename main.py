import base64, json, os, re, time
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from bson import ObjectId
from fastapi import FastAPI, Request as Req
from fastapi.responses import JSONResponse
from pymongo import MongoClient, DESCENDING

NVIDIA_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"
MODEL = "nvidia/nemotron-3-ultra-550b-a55b"
MAX_FILE = 4 * 1024 * 1024
_client = None
_indexes = False
app = FastAPI(title="NOVA AI", version="2.0.0")

def now():
    return datetime.now(timezone.utc)

def get_db():
    global _client, _indexes
    uri = os.getenv("MONGODB_URI", "").strip()
    if not uri:
        raise RuntimeError("MONGODB_URI is not configured.")
    if _client is None:
        _client = MongoClient(uri, serverSelectionTimeoutMS=5000, connectTimeoutMS=5000, socketTimeoutMS=10000, appname="NOVA-AI")
    database = _client["nova_ai"]
    if not _indexes:
        database.chats.create_index([("guestId", 1), ("updatedAt", DESCENDING)])
        database.messages.create_index([("chatId", 1), ("createdAt", 1)])
        _indexes = True
    return database

def valid_guest(v):
    return isinstance(v, str) and bool(re.fullmatch(r"[a-fA-F0-9-]{36}", v))

def valid_chat(v):
    return isinstance(v, str) and ObjectId.is_valid(v)

def err(status, message):
    return JSONResponse(status_code=status, content={"error": message})

async def read_payload(request, limit=120000):
    length = request.headers.get("content-length")
    if length and int(length) > limit:
        raise ValueError("Request body too large.")
    raw = await request.body()
    if not raw or len(raw) > limit:
        raise ValueError("Request body empty or too large.")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("Expected JSON object.")
    return value

def history(action, data):
    guest = data.get("guestId")
    if not valid_guest(guest):
        return err(400, "Invalid guest ID.")
    try:
        database = get_db()
        if action == "create":
            stamp = now()
            result = database.chats.insert_one({"guestId": guest, "title": "New chat", "createdAt": stamp, "updatedAt": stamp})
            return JSONResponse(status_code=201, content={"chatId": str(result.inserted_id), "title": "New chat"})
        if action == "list":
            chats = list(database.chats.find({"guestId": guest}).sort("updatedAt", DESCENDING).limit(100))
            return JSONResponse(content={"chats": [{"chatId": str(c["_id"]), "title": c.get("title", "New chat"), "createdAt": c["createdAt"].isoformat(), "updatedAt": c["updatedAt"].isoformat()} for c in chats]})
        chat_id = data.get("chatId")
        if not valid_chat(chat_id):
            return err(400, "Invalid chat ID.")
        oid = ObjectId(chat_id)
        if not database.chats.find_one({"_id": oid, "guestId": guest}):
            return err(404, "Chat not found.")
        if action == "load":
            msgs = list(database.messages.find({"chatId": oid, "guestId": guest}).sort("createdAt", 1).limit(500))
            return JSONResponse(content={"chatId": chat_id, "messages": [{"role": m["role"], "content": m["content"]} for m in msgs]})
        if action == "delete":
            database.messages.delete_many({"chatId": oid, "guestId": guest})
            database.chats.delete_one({"_id": oid, "guestId": guest})
            return JSONResponse(content={"deleted": True})
        return err(400, "Unknown history action.")
    except Exception as exc:
        print("NOVA history error:", type(exc).__name__)
        return err(503, "Chat history unavailable. Check MONGODB_URI and Atlas network access.")

def call_nvidia(messages):
    key = os.getenv("NVIDIA_API_KEY", "").strip()
    if not key:
        raise RuntimeError("NVIDIA_API_KEY is missing in Vercel Environment Variables.")
    clean = [{"role": "system", "content": "You are NOVA AI, a helpful, clear, practical assistant. Use concise answers by default. Format code in Markdown code fences. If uncertain, say so."}]
    for item in messages[-16:]:
        if isinstance(item, dict) and item.get("role") in ("user", "assistant") and isinstance(item.get("content"), str):
            clean.append({"role": item["role"], "content": item["content"][:6000]})
    if len(clean) == 1:
        raise ValueError("No valid messages.")
    body = json.dumps({"model": MODEL, "messages": clean, "max_tokens": 2048, "temperature": 0.7, "stream": False, "chat_template_kwargs": {"enable_thinking": False}}).encode()
    req = Request(NVIDIA_URL, data=body, headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"}, method="POST")
    for attempt in range(2):
        try:
            with urlopen(req, timeout=20) as response:
                result = json.loads(response.read().decode())
            choices = result.get("choices") or []
            answer = choices[0].get("message", {}).get("content") if choices else None
            if not isinstance(answer, str) or not answer.strip():
                raise RuntimeError("NVIDIA returned an empty response.")
            return answer.strip(), clean[1:]
        except HTTPError as exc:
            if exc.code in (502, 503, 504) and attempt == 0:
                time.sleep(1)
                continue
            if exc.code in (401, 403):
                raise RuntimeError("NVIDIA rejected the API key or model access. Check NVIDIA_API_KEY.") from exc
            if exc.code == 429:
                raise RuntimeError("NVIDIA usage limit reached. Check your API quota.") from exc
            raise RuntimeError("NVIDIA API request failed (HTTP " + str(exc.code) + ").") from exc
        except (URLError, TimeoutError) as exc:
            if attempt == 0:
                time.sleep(1)
                continue
            raise RuntimeError("NVIDIA timed out or could not be reached.") from exc

def persist_chat(guest, chat_id, messages, answer):
    if not valid_guest(guest) or not valid_chat(chat_id):
        return False
    database = get_db()
    oid = ObjectId(chat_id)
    if not database.chats.find_one({"_id": oid, "guestId": guest}):
        return False
    stamp = now()
    saved = [{"chatId": oid, "guestId": guest, "role": m["role"], "content": m["content"][:6000], "createdAt": stamp} for m in messages if m["role"] in ("user", "assistant")]
    saved.append({"chatId": oid, "guestId": guest, "role": "assistant", "content": answer[:20000], "createdAt": now()})
    database.messages.delete_many({"chatId": oid, "guestId": guest})
    if saved:
        database.messages.insert_many(saved)
    title = next((m["content"] for m in saved if m["role"] == "user"), "New chat")
    database.chats.update_one({"_id": oid, "guestId": guest}, {"$set": {"title": title[:60], "updatedAt": now()}})
    return True

@app.get("/api/health")
def health():
    return {"service": "NOVA AI", "status": "ready", "version": "2.0.0", "nvidiaConfigured": bool(os.getenv("NVIDIA_API_KEY")), "geminiConfigured": bool(os.getenv("GEMINI_API_KEY")), "mongodbConfigured": bool(os.getenv("MONGODB_URI"))}

@app.post("/api/chat")
async def chat(request: Req):
    try:
        data = await read_payload(request)
        action = data.get("action", "chat")
        if action != "chat":
            return history(action, data)
        messages = data.get("messages")
        if not isinstance(messages, list) or not messages:
            return err(400, "Send at least one message.")
        try:
            answer, clean = call_nvidia(messages)
        except ValueError as exc:
            return err(400, str(exc))
        except RuntimeError as exc:
            message = str(exc)
            status = 429 if "usage limit" in message.lower() else 504 if "timed out" in message.lower() else 502
            return err(status, message)
        saved = False
        if data.get("guestId") and data.get("chatId"):
            try:
                saved = persist_chat(data["guestId"], data["chatId"], clean, answer)
            except Exception as exc:
                print("NOVA history save failed:", type(exc).__name__)
        return JSONResponse(content={"reply": answer, "historySaved": saved})
    except (ValueError, json.JSONDecodeError):
        return err(400, "Invalid JSON request.")
    except Exception as exc:
        print("NOVA chat error:", type(exc).__name__)
        return err(500, "Unexpected server error. Check Vercel function logs.")

@app.post("/api/analyze")
async def analyze(request: Req):
    try:
        data = await read_payload(request, 5900000)
    except (ValueError, json.JSONDecodeError):
        return err(400, "Invalid or oversized request. Choose a file under 4 MB.")
    mime, filename = data.get("mimeType"), data.get("fileName", "uploaded-file")
    encoded, question = data.get("fileData"), data.get("question", "")
    allowed = {"image/jpeg", "image/png", "image/webp", "image/gif", "application/pdf"}
    if mime not in allowed:
        return err(400, "Unsupported file type. Upload an image or PDF.")
    if not isinstance(encoded, str) or not isinstance(question, str) or len(question) > 4000:
        return err(400, "Invalid file data or question.")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except Exception:
        return err(400, "Invalid file encoding.")
    if not raw or len(raw) > MAX_FILE:
        return err(413 if raw else 400, "File must be non-empty and 4 MB or smaller.")
    signatures = {"application/pdf": b"%PDF-", "image/jpeg": b"\xff\xd8\xff", "image/png": b"\x89PNG\r\n\x1a\n", "image/gif": b"GIF8"}
    if mime in signatures and not raw.startswith(signatures[mime]):
        return err(400, "File content does not match its declared type.")
    if mime == "image/webp" and (len(raw) < 12 or raw[:4] != b"RIFF" or raw[8:12] != b"WEBP"):
        return err(400, "Invalid WebP file.")
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key:
        return err(500, "GEMINI_API_KEY is missing in Vercel Environment Variables.")
    name = re.sub(r"[\r\n\x00]", "", filename)[:180] if isinstance(filename, str) else "uploaded-file"
    prompt = question.strip() or "Analyse this file and explain its important information."
    gemini_body = {"contents": [{"parts": [{"text": "You are NOVA AI. Analyse the supplied file accurately, extract readable text, explain relevant details, and state uncertainty rather than inventing details.\nFile: " + name + "\nRequest: " + prompt}, {"inline_data": {"mime_type": mime, "data": base64.b64encode(raw).decode("ascii")}}]}], "generationConfig": {"temperature": 0.2, "maxOutputTokens": 4096}}
    req = Request(GEMINI_URL, data=json.dumps(gemini_body).encode(), headers={"Content-Type": "application/json", "x-goog-api-key": key}, method="POST")
    try:
        with urlopen(req, timeout=45) as response:
            result = json.loads(response.read().decode())
    except HTTPError as exc:
        print("Gemini HTTP error:", exc.code, exc.read().decode(errors="replace")[:300])
        return err(429 if exc.code == 429 else 502, "Gemini request failed (HTTP " + str(exc.code) + "). Check API key, quota, and file format.")
    except (URLError, TimeoutError):
        return err(504, "Gemini timed out. Try again.")
    except Exception:
        return err(502, "Gemini returned an invalid response.")
    candidates = result.get("candidates") or []
    parts = candidates[0].get("content", {}).get("parts", []) if candidates else []
    answer = "\n".join(p.get("text", "") for p in parts if isinstance(p, dict) and isinstance(p.get("text"), str)).strip()
    if not answer:
        return err(502, "Gemini returned no analysis. Try another file.")
    saved = False
    guest, chat_id = data.get("guestId"), data.get("chatId")
    if valid_guest(guest) and valid_chat(chat_id):
        try:
            database = get_db()
            oid = ObjectId(chat_id)
            if database.chats.find_one({"_id": oid, "guestId": guest}):
                user_text = (question.strip() + "\n\n" if question.strip() else "") + "Attached file: " + str(filename)[:180]
                stamp = now()
                database.messages.insert_many([
                    {"chatId": oid, "guestId": guest, "role": "user", "content": user_text[:6000], "createdAt": stamp},
                    {"chatId": oid, "guestId": guest, "role": "assistant", "content": answer[:20000], "createdAt": now()}
                ])
                database.chats.update_one({"_id": oid, "guestId": guest}, {"$set": {"title": user_text[:60], "updatedAt": now()}})
                saved = True
        except Exception as exc:
            print("NOVA analysis history save failed:", type(exc).__name__)
    return JSONResponse(content={"analysis": answer, "fileName": name, "mimeType": mime, "historySaved": saved})

