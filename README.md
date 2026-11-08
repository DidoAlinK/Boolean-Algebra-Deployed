# Boolean Lab

FastAPI backend (`app/`) + React/Vite frontend (`frontend/`), deployed as ONE service: the Docker image builds
the frontend and FastAPI serves it next to the API, so there is one URL and no CORS to configure.

## Run locally
    pip install -r requirements.txt && uvicorn app.main:app --reload      # API on :8000
    cd frontend && npm install && npm run dev                              # UI on :5173

## Deploy (Render, free)
1. Push this folder to a GitHub repo.
2. Render -> New + -> Blueprint -> pick the repo -> Apply (reads `render.yaml`).
3. When it is live, open `https://<service>.onrender.com/api/health`, then the root URL.
4. UptimeRobot: HTTP monitor on `/api/health` every 5 min (the app also pings itself every 10 min).

## Split deploy (optional)
Frontend elsewhere: build with `VITE_API_URL=https://<api-host>`, and set `BOOLEAN_LAB_CORS=https://<frontend-host>` on the API.

## Useful env vars
`BOOLEAN_LAB_CLIENT_IP_HEADER`, `BOOLEAN_LAB_RATE_ANALYZE|SIMPLIFY|SYNTHESIZE|OTHER`, `BOOLEAN_LAB_SIMPLIFY_PARALLEL`,
`BOOLEAN_LAB_MAX_VARIABLES`, `BOOLEAN_LAB_CORS`.
# Boolean-Algebra-Deployed
