
import base64
import json
import os
from http.server import BaseHTTPRequestHandler
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-2.5-flash:generateContent"
)

MAX_REQUEST_BYTES = 5_000_000
MAX_FILE_BYTES = 4 * 1024 * 1024

ALLOWED_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/gif",
    "application/pdf",
}


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
request_path = self.path.split("?", 1)[0].rstrip("/")

if request_path not in ("", "/", "/api/analyze"):
    return self.send_json(404, {"error": "Not found."})
        try:
            length = int(self.headers.get("Content-Length", "0"))

            if length <= 0 or length > MAX_REQUEST_BYTES:
                return self.send_json(
                    413, {"error": "Request too large. Use a file under 4 MB."}
                )

            payload = json.loads(self.rfile.read(length).decode("utf-8"))

            mime_type = payload.get("mimeType")
            file_name = payload.get("fileName", "uploaded-file")
            encoded_file = payload.get("fileData")
            question = payload.get("question", "")

            if mime_type not in ALLOWED_TYPES:
                return self.send_json(
                    400, {"error": "Only images and PDF files are supported."}
                )

            if not isinstance(encoded_file, str) or not encoded_file:
                return self.send_json(400, {"error": "No file data received."})

            if not isinstance(question, str):
                return self.send_json(400, {"error": "Invalid question."})

            if len(question) > 4000:
                return self.send_json(400, {"error": "Question is too long."})

            try:
                file_bytes = base64.b64decode(encoded_file, validate=True)
            except Exception:
                return self.send_json(400, {"error": "Invalid file encoding."})

            if not file_bytes or len(file_bytes) > MAX_FILE_BYTES:
                return self.send_json(
                    413, {"error": "File must be smaller than 4 MB."}
                )

            # Basic file signature checks to reject obvious MIME mismatches.
            if mime_type == "application/pdf" and not file_bytes.startswith(b"%PDF-"):
                return self.send_json(400, {"error": "The uploaded file is not a valid PDF."})

            if mime_type == "image/png" and not file_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
                return self.send_json(400, {"error": "The uploaded PNG file appears invalid."})

            if mime_type == "image/jpeg" and not file_bytes.startswith(b"\xff\xd8\xff"):
                return self.send_json(400, {"error": "The uploaded JPEG file appears invalid."})

            api_key = os.environ.get("GEMINI_API_KEY")
            if not api_key:
                return self.send_json(
                    500, {"error": "GEMINI_API_KEY is missing in Vercel settings."}
                )

            prompt = (
                "You are NOVA AI, an assistant that analyses images and documents. "
                "Carefully inspect the supplied file. Extract visible text where "
                "possible, explain important details, preserve table structure using "
                "Markdown tables when useful, and clearly distinguish facts from "
                "uncertainty. Do not invent unreadable content. "
                f"\nFile name: {file_name[:180]}\n"
                f"User request: {question.strip() or 'Describe this file and extract its important information.'}"
            )

            request_body = {
                "contents": [{
                    "parts": [
                        {"text": prompt},
                        {
                            "inline_data": {
                                "mime_type": mime_type,
                                "data": base64.b64encode(file_bytes).decode("ascii")
                            }
                        }
                    ]
                }],
                "generationConfig": {
                    "temperature": 0.2,
                    "maxOutputTokens": 4096
                }
            }

            request = Request(
                GEMINI_URL + "?key=" + api_key,
                data=json.dumps(request_body).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST"
            )

            try:
                with urlopen(request, timeout=45) as response:
                    result = json.loads(response.read().decode("utf-8"))
            except HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")[:500]
                if exc.code == 400:
                    return self.send_json(400, {
                        "error": "Gemini could not process this file. Check its format and try again."
                    })
                if exc.code in (401, 403):
                    return self.send_json(502, {
                        "error": "Gemini rejected the API key or access. Check GEMINI_API_KEY."
                    })
                if exc.code == 429:
                    return self.send_json(429, {
                        "error": "Gemini rate limit reached. Try again later."
                    })
                print("Gemini HTTP error:", exc.code, detail)
                return self.send_json(502, {"error": "Gemini API request failed."})
            except (URLError, TimeoutError):
                return self.send_json(504, {"error": "Gemini request timed out. Try again."})

            candidates = result.get("candidates", [])
            if not candidates:
                return self.send_json(
                    502, {"error": "Gemini returned no analysis. Try another file."}
                )

            parts = candidates[0].get("content", {}).get("parts", [])
            answer = "\n".join(
                part.get("text", "")
                for part in parts
                if isinstance(part, dict) and isinstance(part.get("text"), str)
            ).strip()

            if not answer:
                return self.send_json(502, {"error": "Gemini returned an empty analysis."})

            return self.send_json(200, {
                "analysis": answer,
                "fileName": file_name[:180],
                "mimeType": mime_type
            })

        except (ValueError, TypeError):
            return self.send_json(400, {"error": "Invalid request body."})
        except Exception as exc:
            print("NOVA analysis error:", type(exc).__name__)
            return self.send_json(500, {"error": "Analysis failed. Check Vercel function logs."})

    def do_GET(self):
        return self.send_json(405, {"error": "Use POST for file analysis."})

    def send_json(self, status, data):
        encoded = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)
