import json
import os
import mimetypes
from urllib.parse import urlparse, unquote
from http.server import BaseHTTPRequestHandler
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

API_URL = "https://router.huggingface.co/v1/chat/completions"
MODEL = "openai/gpt-oss-120b"

class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path.rstrip("/") != "/api/chat":
            return self._send(404, {"error": "Not found."})
        token = os.environ.get("HF_TOKEN")
        if not token:
            return self._send(500, {"error": "Server is missing HF_TOKEN. Add it in Vercel Project Settings → Environment Variables."})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 100_000:
                return self._send(400, {"error": "Invalid request size."})
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            messages = payload.get("messages", [])
            if not isinstance(messages, list) or not messages:
                return self._send(400, {"error": "Send at least one message."})
            clean = [{"role": "system", "content": "You are NOVA AI, a helpful, clear, practical assistant. Use concise answers by default. Format code in Markdown code fences. If you are uncertain, say so."}]
            for msg in messages[-16:]:
                if not isinstance(msg, dict):
                    continue
                role = msg.get("role")
                content = msg.get("content")
                if role not in ("user", "assistant") or not isinstance(content, str):
                    continue
                clean.append({"role": role, "content": content[:6000]})
            body = json.dumps({
                "model": MODEL,
                "messages": clean,
                "max_tokens": 800,
                "temperature": 0.7
            }).encode("utf-8")
            req = Request(API_URL, data=body, headers={
                "Authorization": "Bearer " + token,
                "Content-Type": "application/json"
            }, method="POST")
            with urlopen(req, timeout=55) as resp:
                result = json.loads(resp.read().decode("utf-8"))
            reply = result["choices"][0]["message"]["content"]
            return self._send(200, {"reply": reply})
        except HTTPError as exc:
            try:
                detail = exc.read().decode("utf-8")[:500]
            except Exception:
                detail = ""
            if exc.code in (401, 403):
                return self._send(502, {"error": "The AI provider rejected the token or model access. Check your Hugging Face token and inference permissions."})
            if exc.code == 429:
                return self._send(429, {"error": "AI provider rate limit or free quota reached. Try again later."})
            return self._send(502, {"error": "AI provider error (HTTP %s). %s" % (exc.code, detail)})
        except (URLError, TimeoutError):
            return self._send(504, {"error": "The AI provider took too long to respond. Try again."})
        except (ValueError, KeyError, IndexError, TypeError):
            return self._send(502, {"error": "Unexpected response from the AI provider. Try again later."})
        except Exception:
            return self._send(500, {"error": "Unexpected server error."})

   def do_GET(self):
    path = unquote(urlparse(self.path).path)

    if path == "/api/chat":
        return self._send(
            405,
            {"error": "Use POST for chat requests."}
        )

    relative_path = "index.html" if path == "/" else path.lstrip("/")
    root = os.path.abspath(os.getcwd())
    target = os.path.abspath(os.path.join(root, relative_path))

    if os.path.commonpath([root, target]) != root:
        return self._send(403, {"error": "Forbidden"})

    if not os.path.isfile(target):
        return self._send(404, {"error": "File not found"})

    content_type = mimetypes.guess_type(target)[0]
    if not content_type:
        content_type = "application/octet-stream"

    with open(target, "rb") as file:
        data = file.read()

    self.send_response(200)
    self.send_header("Content-Type", content_type)
    self.send_header("Content-Length", str(len(data)))
    self.send_header("Cache-Control", "no-cache")
    self.end_headers()
    self.wfile.write(data)

    def _send(self, status, data):
        encoded = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)
