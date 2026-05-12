# Deployment Guide

WebLens can be deployed to Railway (recommended), Heroku, AWS, or any cloud platform supporting Python ASGI apps.

## Quick Start: Railway

Railway is the easiest option—just link your repo and deploy.

### Prerequisites

- [Railway CLI](https://docs.railway.app/develop/cli) installed
- GitHub account (repo linked)
- Required environment variables set

### Deploy Steps

1. **Install Railway CLI:**
   ```bash
   npm install -g @railway/cli
   ```

2. **Link and deploy:**
   ```bash
   railway link
   railway up
   ```

   This automatically reads `railway.toml` and `Procfile`.

3. **Set environment variables in Railway dashboard:**
   - `DATABASE_URL` — Supabase connection string (use pooled, port 6543)
   - `DEEPSEEK_API_KEY` — Required for answer generation
   - `OPENAI_API_KEY` — Optional fallback
   - `TAVILY_API_KEY` — Required for URL discovery
   - `ENVIRONMENT` — Set to `production`
   - `LOG_LEVEL` — `INFO` (or `DEBUG` for troubleshooting)

4. **Initialize database (one-time):**
   ```bash
   railway run python db/setup.py
   ```

5. **View logs:**
   ```bash
   railway logs
   ```

### Monitoring

```bash
# Check status
railway status

# View environment
railway env

# Open dashboard
railway open
```

---

## Environment Variables

### Required

| Variable | Purpose | Example |
|----------|---------|---------|
| `DATABASE_URL` | PostgreSQL connection (pgvector required) | `postgresql://user:pass@host:6543/db` |
| `DEEPSEEK_API_KEY` | LLM for answer generation | `sk-...` |
| `TAVILY_API_KEY` | URL discovery API | `tvly-...` |

### Optional

| Variable | Purpose | Default |
|----------|---------|---------|
| `OPENAI_API_KEY` | LLM fallback if DeepSeek fails | — |
| `ENVIRONMENT` | `production` or `development` | `development` |
| `LOG_LEVEL` | `DEBUG`, `INFO`, `WARNING`, `ERROR` | `INFO` |
| `PORT` | Server port (Railway sets automatically) | `8000` |
| `PUBLIC_MODE` | Anon-session mode for production (see below) | `false` |
| `SEMANTIC_CACHE_ENABLED` | Enable pgvector semantic cache | `false` |

### Public mode (production anon-session pattern)

In production we want chat history hidden from end-users (and from devs/admins
visiting the public site) — but still persisted in the DB for analytics.

| Mode | Sidebar lists past sessions | session_id persistence | DB persistence |
|---|---|---|---|
| dev (`PUBLIC_MODE=false`) | Yes, full list | `localStorage` (survives reload) | Always |
| prod (`PUBLIC_MODE=true`) | No (returns `[]`) | In-memory only (lost on reload or tab close) | Always |

To enable:
- **Backend**: set `PUBLIC_MODE=true` in Railway env vars
- **Frontend build**: set `VITE_PUBLIC_MODE=true` in the build step (the value is baked into the JS bundle at build time, not read at runtime)

Verify post-deploy:
```bash
curl https://<your-app>.railway.app/api/sessions
# Should return: []
```

Sessions are still in Postgres; query Supabase directly to inspect.

### Supabase Setup

To use Supabase for pgvector:

1. Create a Supabase project
2. In Settings → Database, copy the **pooler** connection string (port 6543, PgBouncer transaction mode)
3. Paste into `DATABASE_URL` environment variable

Why pgvector? It natively stores 384-dim embeddings for fast similarity search.

---

## Database Initialization

The `railway.toml` specifies a one-time database setup task:

```bash
railway run python db/setup.py
```

This creates:
- `chat_sessions` table
- `chat_messages` table (with traces)
- `page_cache` table (with 24h TTL)
- `web_chunks` table (with pgvector embeddings)
- Indexes for performance

**Run this once after first deploy, before sending queries.**

---

## Frontend Deployment

### Option 1: Serve Pre-Built Frontend

If you've already built the frontend locally (`npm run build`):

1. Commit the `frontend/dist/` directory
2. Railway will auto-serve `frontend/dist/index.html` at `/`

### Option 2: Build on Railway

Uncomment `nodejs = "18"` in `railway.toml`:

```toml
[build.nixpacks]
python = "3.11"
nodejs = "18"
```

Add a build script to `Procfile`:

```
web: npm run build --prefix frontend && python -m uvicorn app:app --host 0.0.0.0 --port $PORT
```

This builds the frontend during deploy.

### Option 3: Deploy Frontend Separately

Deploy frontend to Vercel/Netlify and update CORS in `app.py`:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5174",
        "https://your-frontend.vercel.app",  # Add your domain
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)
```

---

## Performance Tuning

### Database Connection Pooling

Supabase handles this automatically via port 6543 (PgBouncer). Use the **pooler** connection string, not direct.

### Embedding Device

The system auto-detects GPU/CPU. On Railway:
- GPU: Not available (CPU only)
- Batch size: 32 (sufficient for Railway's resources)

### LLM Stream Timeout

DeepSeek might timeout on slow connections. Add retry logic if needed (handled in `llm/deepseek.py`).

---

## Scaling

### Horizontal Scaling

Railway can run multiple instances:

```bash
railway add postgres  # Add database replica (if scaling queries)
```

### Vertical Scaling

Upgrade Railway plan to increase:
- RAM (for larger embeddings)
- CPU (for faster chunking)

### Caching Strategy

The system caches:
- **Page cache:** 24-hour TTL (check `page_cache` before extraction)
- **Embeddings:** Stored in pgvector (no re-compute on duplicate URLs)
- **In-memory:** Per-query RRF ranking (not persistent)

---

## Troubleshooting

### Database Connection Error

```
ERROR: could not connect to database
```

**Fix:**
1. Verify `DATABASE_URL` is set and correct
2. Check Supabase network access rules
3. Use pooled connection (port 6543), not direct (5432)
4. Test locally: `python -c "import asyncpg; print(asyncpg.__version__)"`

### "No URLs found"

```
error: No URLs found. Check TAVILY_API_KEY.
```

**Fix:**
1. Verify `TAVILY_API_KEY` is set in Railway environment
2. Check Tavily API status and rate limits
3. Try a simple query: "What is Python?"

### "Could not extract content from any URL"

```
error: Could not extract content from any URL.
```

**Causes:**
- All URLs blocked Jina Reader (IP-based blocks common)
- trafilatura fallback didn't work
- Network connectivity issue

**Fix:**
1. Check `LOG_LEVEL=DEBUG` for detailed extraction logs
2. Verify URLs are accessible from Railway's IP range
3. Try a query with mainstream tech sites (less likely to block)

### LLM Generation Timeout

```
error: LLM request timed out
```

**Fix:**
1. Increase timeout in `config.py` (default: 60s)
2. Use DeepSeek (cheaper, faster) over OpenAI
3. Check API key validity

---

## Monitoring & Observability

### Health Check

```bash
curl https://your-railway-app.up.railway.app/api/health
```

Returns:
```json
{
  "status": "ok",
  "env": "production",
  "dev_mode": false,
  "version": "3.0.0"
}
```

### Logs

In Railway dashboard → Deployments → View Logs:

- **Info level:** Pipeline stages + latencies
- **Debug level:** Detailed traces (verbose, slower)

### Session History

```bash
curl https://your-railway-app.up.railway.app/api/sessions?limit=10
```

Lists recent sessions with latency breakdowns.

---

## Cost Estimate (Monthly)

| Service | Cost | Notes |
|---------|------|-------|
| Railway (Python app) | $5-20 | Auto-scales, ~200 req/min free tier |
| Supabase (pgvector) | $10-50 | Depends on data size & query volume |
| DeepSeek API | $0.01-1 | ~0.01¢ per query |
| Tavily API | $0.20-5 | Free tier included |
| **Total** | **~$15-75** | Scaling from hobby to production |

**Optimizer tip:** Enable page caching (24h TTL) to reduce Tavily & extraction costs.

---

## Security Checklist

- ✅ Use Environment Variables (never commit API keys)
- ✅ Enable HTTPS (Railway handles this automatically)
- ✅ Set `ENVIRONMENT=production` to disable debug mode
- ✅ Regularly rotate API keys (Tavily, DeepSeek, OpenAI)
- ✅ Monitor rate limits to detect abuse
- ✅ Use database authentication (Supabase handles)
- ✅ Restrict CORS to trusted domains (if needed)

---

## Rollback & Disaster Recovery

### Rollback Deployment

```bash
railway logs --limit=1  # Find previous deployment ID
railway rollback <deployment-id>
```

### Database Backups

Supabase automatically backs up hourly. To restore:
1. Go to Supabase dashboard → Settings → Backups
2. Choose a point-in-time restore
3. Update `DATABASE_URL` if needed

### Disaster Recovery Plan

1. **Database down:** Switch to backup database (Supabase handles)
2. **API keys compromised:** Rotate immediately in Railway + provider dashboards
3. **Deployment failed:** Rollback to last working version

---

## Next Steps

1. Set environment variables in Railway dashboard
2. Run `railway run python db/setup.py` to initialize database
3. Test with `/api/health` endpoint
4. Monitor logs with `railway logs --follow`
5. Keep API keys secured and rotate periodically

For more Railway docs: https://docs.railway.app
