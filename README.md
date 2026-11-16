# Forge

Forge is an agentic AI platform that builds and hosts a complete online presence for a small
business from one conversation. The owner describes the business or pastes a link to an existing
site, and Forge scrapes the context, builds a private retrieval-augmented knowledge base,
generates a responsive multi-page website, configures grounded customer-facing assistants, and
publishes the result with a share link, an embed widget and a downloadable archive.

## Stack

- Frontend: Next.js (App Router), React, CSS Modules, Zustand
- Backend: FastAPI served with Uvicorn
- Data: Supabase PostgreSQL with row-level security, ChromaDB for per-business vectors
- Scraping: Crawl4AI with Playwright
- Inference: five-provider ordered failover chain selected by environment variables

## Layout

```
backend/        FastAPI service, agents, services, RAG, scraper, migrations, tests
frontend-next/  Next.js client, dashboard, workspace cockpit, assistant sandbox
```

## Run locally

Backend, from `backend`:

```powershell
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
# fill in the values in .env
python -m uvicorn main:app --port 8000 --loop loop_factory:windows_safe_loop_factory
```

Frontend, from `frontend-next`:

```powershell
npm install
npm run dev
```

Then open http://localhost:3000.

## Configuration

All model roles and provider keys are read from environment variables, so a model or provider can
be replaced without a code change. Copy `backend/.env.example` to `backend/.env` and fill in your
own keys. No credentials are stored in this repository.

## Tests

```powershell
cd backend
python tests/run_all.py
```
