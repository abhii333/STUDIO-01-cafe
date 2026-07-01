# STUDIO 01 — Deployment Guide (Netlify + Render + Neon)

The frontend is hosted on Netlify, the Flask API runs on Render, and the database is on Neon PostgreSQL. All three have free tiers.

```
Browser ──> Netlify (frontend/)  ──HTTPS──>  Render (backend/)  ──SSL──>  Neon (PostgreSQL)
```

Do the steps in this order: **GitHub → Neon → Render → Netlify → connect the two URLs**.

---

## 0. Prerequisites
- A GitHub account, and this project pushed to it (see step 1).
- Free accounts at [neon.tech](https://neon.tech), [render.com](https://render.com), [netlify.com](https://netlify.com).
- Rotate the old Razorpay **test** keys (the ones previously in `.env` are considered leaked). Get fresh test keys from the Razorpay dashboard. Payments are optional — skip if you just want the demo.

---

## 1. Push to GitHub
From the project root:
```bash
git add -A
git commit -m "STUDIO 01 launch"
git branch -M main
git remote add origin https://github.com/abhii333/STUDIO-01-cafe.git   # skip if already added
git push -u origin main
```
`.env` is git-ignored, so no secrets are pushed. Only `.env.example` (placeholders) goes up.

---

## 2. Neon — the database
1. Create a project at neon.tech (region closest to you).
2. On the dashboard, copy the **pooled** connection string. It looks like:
   `postgresql://user:password@ep-xxxx-pooler.region.aws.neon.tech/neondb?sslmode=require`
3. Keep it handy — it becomes `DATABASE_URL` on Render. (The app also accepts the `postgres://` form; it auto-normalizes to `postgresql://`.)

---

## 3. Render — the Flask backend
**Option A — Blueprint (easiest):** New + → **Blueprint** → pick your GitHub repo. Render reads `render.yaml` and pre-fills everything. Then just set the `sync:false` env vars below.

**Option B — Manual:** New + → **Web Service** → your repo, then:
- **Root Directory:** `backend`
- **Build Command:** `pip install -r requirements.txt`
- **Start Command:** `gunicorn app:app --bind 0.0.0.0:$PORT`

Set these **Environment Variables** (Render dashboard → Environment):

| Key | Value |
|-----|-------|
| `DATABASE_URL` | your Neon connection string (step 2) |
| `SECRET_KEY` | any long random string |
| `JWT_SECRET` | a different long random string |
| `ADMIN_PASSWORD` | the password you want for the `admin` account |
| `FRONTEND_ORIGIN` | your Netlify URL (fill after step 4, e.g. `https://your-cafe.netlify.app`) |
| `AUTO_INIT_DB` | `1` |
| `PRODUCTION` | `1` |
| `RAZORPAY_KEY_ID` / `RAZORPAY_KEY_SECRET` | optional (payments) |

Deploy. On first boot the app creates all tables and seeds the menu, tables, badges, and sample events. Note your backend URL, e.g. `https://studio01-api.onrender.com`. Test it: open `https://studio01-api.onrender.com/health` → should return JSON.

> Free Render services sleep after ~15 min idle; the first request then takes ~30–60s to wake. Open `/health` a minute before demoing to warm it up.

---

## 4. Netlify — the frontend
1. First, tell the frontend where the API lives: edit **`frontend/js/config.js`** and set `API_BASE_PROD` to your Render URL:
   ```js
   API_BASE_PROD: "https://studio01-api.onrender.com"
   ```
   Commit and push this change.
2. In Netlify: **Add new site → Import from Git →** your repo.
   - **Base directory:** `frontend`
   - **Build command:** leave empty
   - **Publish directory:** `frontend` (or `.` if base is already `frontend`)
3. Deploy. Note your Netlify URL, e.g. `https://your-cafe.netlify.app`.

---

## 5. Connect them (the important bit)
- Put the **Netlify URL** into Render's `FRONTEND_ORIGIN` env var (so CORS allows it), then trigger a redeploy on Render.
- Make sure `frontend/js/config.js` `API_BASE_PROD` holds the **Render URL** (step 4.1).

That's the whole link: the browser loads the site from Netlify, and the JS calls the Render API using the bearer token.

---

## 6. Verify
1. Open the Netlify URL — the menu should load (data comes from Render/Neon).
2. Register a customer, place an order, check the dashboard (coins + badges appear).
3. Log in as `admin` / your `ADMIN_PASSWORD` → go to `/admin-dashboard.html` → manage menu, offers, tables, events, gallery; see orders + reservations.
4. Book a table for a date/time, then try the same slot again → it should be blocked.

---

## Troubleshooting
- **Menu doesn't load / CORS error in console:** `FRONTEND_ORIGIN` on Render must exactly match your Netlify origin (no trailing slash), and `API_BASE_PROD` must be the Render URL. Redeploy Render after changing env vars.
- **First request hangs ~30–60s:** Render free tier waking from sleep. Normal. Warm with `/health`.
- **DB errors on first boot:** confirm `DATABASE_URL` is the Neon **pooled** string and `AUTO_INIT_DB=1`.
- **Login fails for admin:** the admin is seeded only on first boot with `ADMIN_PASSWORD` set. If you set it later, either reset the Neon DB or create the admin manually.
- **Selling later:** move `DATABASE_URL` to a paid always-on DB and point Render/`API_BASE_PROD` at a paid host — no code changes needed.
