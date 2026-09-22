# AI Highlight Reel Maker

Turn long videos into captioned highlight clips using local AI. The app transcribes speech with faster-whisper, selects moments with Ollama/Qwen3:4b, and renders clips with FFmpeg. Finished clips are stored in a private Supabase Storage bucket. The original upload and processing files are temporary.

## Requirements

- Node.js and npm
- Python 3.14
- FFmpeg on `PATH`
- Ollama with the `qwen3:4b` model
- A Supabase project with a private Storage bucket named `highlight-videos`

## Setup

```powershell
npm install
cd backend
python -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Set `SUPABASE_URL` and `SUPABASE_SECRET_KEY` in `backend/.env`. Keep the secret key on the backend only. The Free Supabase plan limits individual clip files to 50 MB.

## Run

Start Ollama, then start the backend and frontend in separate terminals:

```powershell
cd backend
.\venv\Scripts\python.exe -m uvicorn main:app --reload --port 8000
```

```powershell
npm run dev
```

Open [http://localhost:3000](http://localhost:3000). Upload an MP4, MOV, MKV, or WebM video, choose the clip settings, and generate highlights.
