# NOVA AI — Python + Vercel + installable PWA

A beginner-friendly AI chatbot with a responsive interface, server-side Python API, and Android home-screen installation support.

## Requirements

- A GitHub account
- A Vercel account
- A Hugging Face account/token with Inference Providers access
- For local development: Python 3.10+ and Node.js/npm (Vercel CLI runs with Node)

## 1. Get an AI token

1. Open https://huggingface.co/settings/tokens
2. Create a token with the permissions needed to use Inference Providers.
3. Keep the token private. Do not paste it into `app.js`, `index.html`, or GitHub files.

The app uses the Hugging Face OpenAI-compatible router with model `openai/gpt-oss-120b`. Availability and free quota can change; if this model is unavailable for your account, choose a currently supported chat model from Hugging Face Inference Providers and update `MODEL` in `api/chat.py`.

## 2. Deploy on Vercel

1. Unzip this project.
2. Upload the contents of the `nova-ai-chatbot` folder to a new GitHub repository.
3. Go to https://vercel.com/new and import that repository.
4. Keep the project root as the repository root. Vercel should detect the Python function in `api/chat.py`.
5. In Vercel Project → Settings → Environment Variables, add:
   - Name: `HF_TOKEN`
   - Value: your Hugging Face token
   - Environments: Production, Preview, Development as needed
6. Redeploy after adding the variable.
7. Open the deployed URL and send a test message.

The API route is `/api/chat`; the token is read only on the server. Never expose it in browser code.

## 3. Run locally (optional)

Install the Vercel CLI and log in:

```bash
npm install -g vercel
vercel dev
```

Add the `HF_TOKEN` variable in Vercel's local environment setup, or create a `.env` file with:

```text
HF_TOKEN=your_token_here
```

Do not commit `.env`. `vercel dev` serves the static frontend and Python function together. If you prefer testing only the interface, opening `index.html` directly will not make AI calls work; the `/api/chat` endpoint must be served.

## 4. Install on Android

1. Open the deployed HTTPS URL in Chrome on Android.
2. Open Chrome's ⋮ menu.
3. Tap **Install app** or **Add to Home screen** (wording depends on Chrome version).
4. Launch NOVA AI from the new home-screen icon.

PWA install prompts vary by browser and device. The web app is not an APK and is not published on Google Play.

## What's included

- Responsive dark interface and starter prompts
- Python serverless chat endpoint
- Conversation kept in the current browser tab session
- Copy-response buttons
- Clear/new conversation
- PWA manifest, icon, and service worker shell caching

## Notes

- AI provider quotas, model availability, Vercel limits, and response times are not guaranteed to be free or unlimited.
- No user accounts or database are included in this starter.
- The service worker caches the app shell only; AI replies require an internet connection.
