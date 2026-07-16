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


---

## Skeleton loading screens (Boneyard)

While data loads, the storefront and dashboards show pixel-matched skeleton
placeholders extracted from the real rendered DOM (via a vendored subset of
[`boneyard-js`](https://www.npmjs.com/package/boneyard-js), MIT). No build step
and no runtime third-party dependency — the core is vendored and imported
natively.

### Files
- `frontend/js/vendor/boneyard/` — vendored core (`extract`, `runtime`, `shared`, `responsive`, `types`). See its `VENDORED.md`.
- `frontend/js/bones/*.bones.json` — captured responsive bones (source of truth), one per component at 375/768/1280.
- `frontend/js/bones/index.mjs` — generated bundle of all bones (statically imported for instant paint). **Generated — do not edit by hand.**
- `frontend/js/bones/registry.mjs` — registers the bones by name.
- `frontend/js/skeleton-boot.js` — tiny classic stub (loads in `<head>`) that queues `Skeletons.fill/clear` until the module is ready.
- `frontend/js/skeleton-runtime.mjs` — `window.Skeletons.fill(containerId, name, count)` / `.clear(containerId)`.
- `frontend/css/skeletons.css` — bone colours (CSS vars), pulse animation, `prefers-reduced-motion` + `html.sk-dark` hooks.
- `frontend/tools/` — dev-only: `capture-bones.html` (re-capture harness), `bone-fixtures.mjs` (fixtures), `build-bones-index.mjs` (bundle generator), `tests/*.test.mjs`.

### Re-capturing bones after a design change
When you change a card's markup or CSS, re-capture so the skeletons stay pixel-accurate:

1. Serve the frontend over HTTP (e.g. `python3 -m http.server 8199` from `frontend/`).
   `file://` will not work — the harness uses `fetch()` to load each page's CSS.
2. Open `http://localhost:8199/tools/capture-bones.html`.
3. Click **Capture all**, then **Download all JSON** (or per-component **Download**).
4. Move the downloaded `*.bones.json` files into `frontend/js/bones/`.
5. Regenerate the bundle: `node frontend/tools/build-bones-index.mjs`.
6. Verify: `node --test frontend/tools/tests/vendor.test.mjs frontend/tools/tests/bones.test.mjs frontend/tools/tests/runtime.test.mjs`

No manual pixel measurement is ever needed — positions come straight from the
browser's layout of the real markup.

### Notes
- `.mjs`/`.js` modules are same-origin, so they load under the existing CSP (`default-src 'self' …`). Netlify and Cloudflare Pages both serve `.mjs` as `text/javascript`.
- If the runtime module ever fails to load, skeletons simply don't appear — pages still work normally (graceful degradation).
