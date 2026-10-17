
import json
import os
import mimetypes
from urllib.parse import urlparse, unquote
from http.server import BaseHTTPRequestHandler
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

API_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
MODEL = "nvidia/nemotron-3-ultra-550b-a55b"


class handler(BaseHTTPRequestHandler):

    def do_POST(self):
        if urlparse(self.path).path.rstrip("/") != "/api/chat":
            return self._send(404, {"error": "Not found."})

        token = os.environ.get("NVIDIA_API_KEY")
        if not token:
            return self._send(
                500,
                {
                    "error": (
                        "NVIDIA_API_KEY is missing. Add it in "
                        "Vercel Project Settings > Environment Variables."
                    )
                },
            )

        try:
            length = int(self.headers.get("Content-Length", "0"))

            if length <= 0 or length > 100_000:
                return self._send(400, {"error": "Invalid request size."})

            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            messages = payload.get("messages", [])

            if not isinstance(messages, list) or not messages:
                return self._send(
                    400, {"error": "Send at least one message."}
                )

            clean = [
                {
                    "role": "system",
                    "content": (
                        "You are NOVA AI, a helpful, clear, practical "
                        "assistant. Use concise answers by default. "
                        "Format code in Markdown code fences. "
                        "If uncertain, say so."
                    ),
                }
            ]

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
                    "content": content[:6000],
                })

            if len(clean) == 1:
                return self._send(
                    400, {"error": "No valid messages provided."}
                )

            body = json.dumps({
                "model": MODEL,
                "messages": clean,
                "max_tokens": 2048,
                "temperature": 0.7,
                "stream": False,
                "chat_template_kwargs": {
                    "enable_thinking": False
                },
            }).encode("utf-8")

            req = Request(
                API_URL,
                data=body,
                headers={
                    "Authorization": "Bearer " + token,
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                method="POST",
            )

            with urlopen(req, timeout=55) as resp:
                result = json.loads(resp.read().decode("utf-8"))

            choices = result.get("choices", [])
            if not choices:
                return self._send(
                    502,
                    {"error": "NVIDIA returned no response choices."},
                )

            message = choices[0].get("message", {})
            reply = message.get("content")

            if not isinstance(reply, str) or not reply.strip():
                return self._send(
                    502,
                    {
                        "error": (
                            "NVIDIA returned an empty answer. "
                            "Please try again."
                        )
                    },
                )

            return self._send(200, {"reply": reply.strip()})

        except HTTPError as exc:
            try:
                detail = exc.read().decode("utf-8")[:700]
            except Exception:
                detail = ""

            if exc.code in (401, 403):
                return self._send(
                    502,
                    {
                        "error": (
                            "NVIDIA rejected the API key or model access. "
                            "Check your NVIDIA_API_KEY and NVIDIA model "
                            "access. " + detail
                        )
                    },
                )

            if exc.code == 429:
                return self._send(
                    429,
                    {
                        "error": (
                            "NVIDIA rate limit or usage limit reached. "
                            "Wait and try again. " + detail
                        )
                    },
                )

            return self._send(
                502,
                {
                    "error": (
                        "NVIDIA API error (HTTP %s). %s"
                        % (exc.code, detail)
                    )
                },
            )

        except (URLError, TimeoutError):
            return self._send(
                504,
                {
                    "error": (
                        "NVIDIA took too long to respond. "
                        "Please try again."
                    )
                },
            )

        except (ValueError, KeyError, IndexError, TypeError):
            return self._send(
                502,
                {"error": "Unexpected response from NVIDIA. Try again."},
            )

        except Exception:
            return self._send(
                500, {"error": "Unexpected server error."}
            )

    def do_GET(self):
        path = unquote(urlparse(self.path).path)

        if path.rstrip("/") == "/api/chat":
            return self._send(
                405, {"error": "Use POST for chat requests."}
            )

        relative_path = "index.html" if path == "/" else path.lstrip("/")

        root = os.path.realpath(os.getcwd())
        target = os.path.realpath(os.path.join(root, relative_path))

        if os.path.commonpath([root, target]) != root:
            return self._send(403, {"error": "Forbidden"})

        if not os.path.isfile(target):
            return self._send(404, {"error": "File not found"})

        content_type = (
            mimetypes.guess_type(target)[0]
            or "application/octet-stream"
        )

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
            return self._send(
                500, {"error": "Could not read the requested file."}
            )

    def _send(self, status, data):
        encoded = json.dumps(data).encode("utf-8")

        self.send_response(status)
        self.send_header(
            "Content-Type", "application/json; charset=utf-8"
        )
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)
