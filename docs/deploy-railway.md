# Deploy on Railway

Single-container Docker deploy. Frontend is built and served by the FastAPI
backend; SQLite + Garmin tokens + parsed plans live on a persistent volume.

## One-time setup

1. **Create the Railway project**
   - From GitHub: `vitor-mafra/claude-coach` → Deploy from repo → it will pick
     up `railway.json` and use the `Dockerfile`.
2. **Add a persistent volume**
   - Service → **Volumes** → Add volume.
   - Mount path: `/data`. Size: 1 GB is plenty.
3. **Set environment variables** (Service → **Variables**):

   | Key | Value |
   |---|---|
   | `APP_PASSWORD` | a long random string (this is your login password) |
   | `APP_SESSION_SECRET` | another long random string (signs the cookie) |
   | `AUTH_COOKIE_SECURE` | `true` |
   | `CORS_ORIGINS` | `["https://YOUR-RAILWAY-DOMAIN"]` (and any custom domain) |
   | `ANTHROPIC_API_KEY` | your Claude key (optional) |
   | `OPENAI_API_KEY` | your OpenAI key |
   | `GARMIN_EMAIL` | only needed for first login |
   | `GARMIN_PASSWORD` | only needed for first login |
   | `RESEND_API_KEY` | for weekly email |
   | `RESEND_FROM_EMAIL` | `onboarding@resend.dev` or your verified sender |
   | `WEEKLY_REPORT_TO_EMAIL` | where the weekly report goes |
   | `SCHEDULER_TIMEZONE` | `America/Sao_Paulo` |
   | `DATA_DIR` | `/data` (matches the volume mount) |

4. **Deploy**. Railway builds, runs alembic migrations on boot, then serves.

## Seeding personal data on the volume

The repo ships with `data/exercises/` baked into the image. Everything else
(profile, plans, reports, DB, Garmin tokens) starts empty on the volume. Two
options:

### A. Configure inside the app
- Open the deployed URL → login with `APP_PASSWORD`.
- Wizard prompts you to fill profile → writes `/data/profile.yaml`.
- Import your PDF: `Plans → Import` (or `POST /api/plans/parse` via curl).
- For Garmin: temporarily set `GARMIN_EMAIL` / `GARMIN_PASSWORD` env vars,
  redeploy, and run `scripts/garmin_login.py` via Railway shell. Then remove
  the password env var (tokens persist on `/data/garmin_tokens/`).

### B. Push existing data via the Railway CLI
```bash
# from your local machine
railway run --service claude-coach cp -r data/profile.yaml ./
# or use railway shell + scp/rclone
```

In practice the simplest is to run `railway shell` and use `cat > /data/...`
or `railway run sh` to drop the files in.

## Updating

Push to `main` → Railway redeploys automatically. Volume content is preserved
across deploys.

## Notes

- `AUTH_COOKIE_SECURE=true` is mandatory in prod — without it, the cookie
  won't be sent over HTTPS.
- If you add a custom domain, also add it to `CORS_ORIGINS`.
- The scheduler runs **inside** the web process (APScheduler in-process). If
  you scale to >1 replica, the weekly job will run multiple times. Stay at 1
  replica or wrap with a leader election if you need to scale.
- Garmin's `curl_cffi` flow needs the `libcurl4` apt package — already
  installed in the Dockerfile.
