# NOVA AI

NOVA AI is a browser-based assistant with a single FastAPI backend, NVIDIA Nemotron text chat, Gemini 2.5 Flash image/PDF analysis, and optional MongoDB Atlas guest conversation history.

## Features
- NVIDIA Nemotron text chat
- Gemini image and PDF analysis
- Guest conversation history in MongoDB Atlas
- File-analysis results saved to the active conversation when MongoDB is available
- Responsive dark interface and installable PWA
- Chat and file analysis continue even if MongoDB history is unavailable

## Environment variables
Configure these in Vercel Project Settings → Environment Variables:

| Variable | Purpose |
| --- | --- |
| NVIDIA_API_KEY | NVIDIA text-chat API key |
| GEMINI_API_KEY | Gemini image/PDF analysis API key |
| MONGODB_URI | MongoDB Atlas connection string |

NVIDIA and Gemini keys are required for their respective features. MongoDB is required for persistent history, but a database outage should not discard a successful model response. Never put keys in frontend files or commit them to GitHub. Redeploy after changing environment variables.

## Vercel deployment
1. Import this repository into Vercel.
2. Set the Root Directory to the repository root.
3. Add the three environment variables above.
4. Deploy.
5. Open /api/health and check the configured flags.
6. Test text chat, file analysis, and history separately.

The Python entrypoint is main.py, selected by pyproject.toml as main:app. All API routes are served by one FastAPI application. Frontend assets are in public/.

## Local development
Use Python 3.12 or newer:

Windows PowerShell:
```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload
```

Open http://127.0.0.1:8000.

## API routes

| Method | Route | Purpose |
| --- | --- | --- |
| GET | /api/health | Configuration status |
| POST | /api/chat | Text chat and history actions |
| POST | /api/analyze | Image/PDF analysis |

The chat endpoint supports the existing frontend actions: chat, create, list, load, and delete.

## Upload limits
Supported: JPEG, PNG, WebP, GIF, and PDF. Maximum file size: 4 MB.

## Important
The health endpoint confirms whether environment variables are present; it does not validate the credentials or provider quotas. A successful Vercel deployment alone does not prove that NVIDIA, Gemini, or MongoDB is reachable. Test each feature after deployment.
