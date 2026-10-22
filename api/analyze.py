
import base64
import json
import os
import re
from http.server import BaseHTTPRequestHandler
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-2.5-flash:generateContent"
)

MAX_REQUEST_BYTES = 5_700_000
MAX_FILE_BYTES = 4 * 1024 * 1024

ALLOWED_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/gif",
    "application/pdf",
}


def json_bytes(data):
    return json.dumps(data).encode("utf-8")


class handler(BaseHTTPRequestHandler):

    def send_json(self, status, data):
        body = json_bytes(data)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        return self.send_json(200, {
            "service": "NOVA file analysis",
            "status": "ready",
            "method": "POST",
        })

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))

            if length <= 0 or length > MAX_REQUEST_BYTES:
                return self.send_json(413, {
                    "error": "Request too large. Choose a file under 4 MB."
                })

            raw = self.rfile.read(length)
            payload = json.loads(raw.decode("utf-8"))

            if not isinstance(payload, dict):
                return self.send_json(400, {
                    "error": "Invalid request body."
                })

            file_name = payload.get("fileName", "uploaded-file")
            mime_type = payload.get("mimeType", "")
            file_data = payload.get("fileData", "")
            question = payload.get("question", "")

            if mime_type not in ALLOWED_TYPES:
                return self.send_json(400, {
                    "error": "Unsupported file type. Upload an image or PDF."
                })

            if not isinstance(file_data, str) or not file_data:
                return self.send_json(400, {
                    "error": "No file data received. Please attach the file again."
                })

            if not isinstance(question, str) or len(question) > 4000:
                return self.send_json(400, {
                    "error": "The question is invalid or too long."
                })

            try:
                file_bytes = base64.b64decode(file_data, validate=True)
            except Exception:
                return self.send_json(400, {
                    "error": "The file encoding is invalid. Upload it again."
                })

            if not file_bytes:
                return self.send_json(400, {
                    "error": "The uploaded file is empty."
                })

            if len(file_bytes) > MAX_FILE_BYTES:
                return self.send_json(413, {
                    "error": "File must be 4 MB or smaller."
                })

            # Basic file-signature validation.
            signatures = {
                "application/pdf": b"%PDF-",
                "image/jpeg": b"\xff\xd8\xff",
                "image/png": b"\x89PNG\r\n\x1a\n",
                "image/gif": b"GIF8",
            }

            signature = signatures.get(mime_type)
            if signature and not file_bytes.startswith(signature):
                return self.send_json(400, {
                    "error": "The file content does not match its file type."
                })

            if (
                mime_type == "image/webp"
                and (
                    len(file_bytes) < 12
                    or file_bytes[:4] != b"RIFF"
                    or file_bytes[8:12] != b"WEBP"
                )
            ):
                return self.send_json(400, {
                    "error": "The uploaded WebP image appears invalid."
                })

            api_key = os.environ.get("GEMINI_API_KEY", "").strip()
            if not api_key:
                return self.send_json(500, {
                    "error": "GEMINI_API_KEY is missing in Vercel Environment Variables."
                })

            safe_name = (
                re.sub(r"[\r\n\x00]", "", file_name)[:180]
                if isinstance(file_name, str)
                else "uploaded-file"
            )

            user_question = question.strip() or (
                "Analyse this file and explain its important information."
            )

            prompt = (
                "You are NOVA AI, a precise assistant for image and document "
                "analysis. Inspect the supplied file carefully. Extract visible "
                "text when possible, explain relevant details, preserve tables "
                "using Markdown when useful, and clearly state uncertainty. "
                "Never invent unreadable information.\n\n"
                f"File name: {safe_name}\n"
                f"User request: {user_question}"
            )

            request_body = {
                "contents": [{
                    "parts": [
                        {"text": prompt},
                        {
                            "inline_data": {
                                "mime_type": mime_type,
                                "data": base64.b64encode(
                                    file_bytes
                                ).decode("ascii"),
                            }
                        },
                    ]
                }],
                "generationConfig": {
                    "temperature": 0.2,
                    "maxOutputTokens": 4096,
                },
            }

            request = Request(
                GEMINI_URL + "?key=" + api_key,
                data=json_bytes(request_body),
                headers={"Content-Type": "application/json"},
                method="POST",
            )

            try:
                with urlopen(request, timeout=45) as response:
                    result = json.loads(
                        response.read().decode("utf-8")
                    )

            except HTTPError as exc:
                detail = exc.read().decode(
                    "utf-8", errors="replace"
                )[:1200]
                print("Gemini HTTP error:", exc.code, detail)

                if exc.code in (400, 415):
                    return self.send_json(502, {
                        "error": (
                            "Gemini could not process this file. "
                            "Check the file format and try another file."
                        )
                    })

                if exc.code in (401, 403):
                    return self.send_json(502, {
                        "error": (
                            "Gemini rejected the API key or access. "
                            "Check GEMINI_API_KEY and API permissions."
                        )
                    })

                if exc.code == 429:
                    return self.send_json(429, {
                        "error": "Gemini quota or rate limit reached. Try again later."
                    })

                return self.send_json(502, {
                    "error": f"Gemini API request failed (HTTP {exc.code})."
                })

            except (URLError, TimeoutError):
                return self.send_json(504, {
                    "error": "Gemini timed out. Please try again."
                })

            candidates = result.get("candidates", [])
            if not candidates:
                print(
                    "Gemini returned no candidates:",
                    result.get("promptFeedback", {})
                )
                return self.send_json(502, {
                    "error": "Gemini returned no analysis. Try another file."
                })

            parts = candidates[0].get("content", {}).get("parts", [])
            answer = "\n".join(
                part.get("text", "")
                for part in parts
                if isinstance(part, dict)
                and isinstance(part.get("text"), str)
            ).strip()

            if not answer:
                return self.send_json(502, {
                    "error": "Gemini returned an empty analysis."
                })

            return self.send_json(200, {
                "analysis": answer,
                "fileName": safe_name,
                "mimeType": mime_type,
            })

        except (ValueError, TypeError):
            return self.send_json(400, {
                "error": "Invalid request. Please upload the file again."
            })

        except Exception as exc:
            print("NOVA analysis error:", type(exc).__name__)
            return self.send_json(500, {
                "error": "Analysis failed. Check the Vercel function logs."
            })
