/* STUDIO 01 — single place to point the frontend at the backend API.
 *
 * Local dev  -> http://localhost:5000
 * Production -> your Render backend URL (edit API_BASE_PROD below after deploy)
 */
window.STUDIO01_CONFIG = {
  // After deploying the backend to Render, replace this with your Render URL,
  // e.g. "https://studio01-api.onrender.com"
  API_BASE_PROD: "https://YOUR-RENDER-APP.onrender.com"
};

window.API_BASE = ["localhost", "127.0.0.1", ""].indexOf(window.location.hostname) !== -1
  ? "http://localhost:5000"
  : window.STUDIO01_CONFIG.API_BASE_PROD;
