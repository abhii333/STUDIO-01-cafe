/* STUDIO 01 — shared API client.
 * Handles the API base URL, JWT storage, authenticated fetches with auto-refresh,
 * and simple route guards. Exposed as window.API (+ window.apiUrl helper).
 */
(function () {
  var ACCESS = "studio01_access";
  var REFRESH = "studio01_refresh";
  var USER = "studio01_user";
  // Username is mirrored into sessionStorage (case-preserved, exactly as the
  // server returns it) so consumers like the Razorpay prefill never uppercase
  // or lose the original casing.
  var USERNAME = "studio01_username";
  // Where to send the user after a successful login (set before bouncing a
  // guest to the login page). Kept in sessionStorage so it dies with the tab.
  var RETURN_URL = "studio01_return_url";
  // Cart keys: logged-in carts persist in localStorage, guest carts live in
  // sessionStorage (cleared when the tab closes).
  var CART = "cart";
  var GUEST_CART = "studio01_guest_cart";

  function url(path) {
    if (/^https?:\/\//.test(path)) return path;
    return (window.API_BASE || "") + path;
  }

  function setSession(data) {
    if (!data) return;
    if (data.access_token) localStorage.setItem(ACCESS, data.access_token);
    if (data.refresh_token) localStorage.setItem(REFRESH, data.refresh_token);
    if (data.user) {
      localStorage.setItem(USER, JSON.stringify(data.user));
      // Preserve the exact case of the username for display/prefill use.
      if (data.user.username != null) {
        try { sessionStorage.setItem(USERNAME, String(data.user.username)); } catch (e) {}
      }
    }
  }
  function clearSession() {
    localStorage.removeItem(ACCESS);
    localStorage.removeItem(REFRESH);
    localStorage.removeItem(USER);
    localStorage.removeItem(CART);
    try {
      sessionStorage.removeItem(USERNAME);
      sessionStorage.removeItem(GUEST_CART);
    } catch (e) {}
  }
  function getAccess() { return localStorage.getItem(ACCESS); }
  function getRefresh() { return localStorage.getItem(REFRESH); }
  function getUser() {
    try { return JSON.parse(localStorage.getItem(USER)); } catch (e) { return null; }
  }
  function isLoggedIn() { return !!getAccess(); }
  function isAdmin() { var u = getUser(); return !!u && u.role === "Admin"; }

  // Case-preserved username. Prefers the stored user object, falls back to the
  // sessionStorage mirror, then to null. Never transforms case.
  function getUsername() {
    var u = getUser();
    if (u && u.username != null) return String(u.username);
    try { return sessionStorage.getItem(USERNAME); } catch (e) { return null; }
  }

  // ----- Post-login routing (role-based, honours a stored returnUrl) -----
  function setReturnUrl(u) {
    try { sessionStorage.setItem(RETURN_URL, u || (window.location.pathname.split("/").pop() + window.location.hash)); } catch (e) {}
  }
  function takeReturnUrl() {
    try {
      var u = sessionStorage.getItem(RETURN_URL);
      sessionStorage.removeItem(RETURN_URL);
      return u;
    } catch (e) { return null; }
  }
  // Decide where a freshly-authenticated user should land.
  // Admins always go to the admin dashboard; customers resume their returnUrl
  // (if a safe same-app relative path) or fall back to the storefront.
  function postLoginTarget(user) {
    var role = user && user.role;
    if (role === "Admin") { takeReturnUrl(); return "admin-dashboard.html"; }
    var ret = takeReturnUrl();
    if (ret && !/^https?:|^\/\//i.test(ret) && ret.indexOf("login") === -1) return ret;
    return "index.html";
  }
  function goPostLogin(user) { window.location.href = postLoginTarget(user); }

  // ----- Cart storage: localStorage when logged in, sessionStorage for guests -----
  function cartStore() { return isLoggedIn() ? localStorage : sessionStorage; }
  function cartKey() { return isLoggedIn() ? CART : GUEST_CART; }
  function getCart() {
    try { return JSON.parse(cartStore().getItem(cartKey())) || {}; } catch (e) { return {}; }
  }
  function saveCart(cart) {
    try { cartStore().setItem(cartKey(), JSON.stringify(cart || {})); } catch (e) {}
  }
  function clearCart() {
    try { localStorage.removeItem(CART); sessionStorage.removeItem(GUEST_CART); } catch (e) {}
  }
  // When a guest logs in, fold any sessionStorage cart into their localStorage cart.
  function adoptGuestCart() {
    if (!isLoggedIn()) return getCart();
    var guest = {};
    try { guest = JSON.parse(sessionStorage.getItem(GUEST_CART)) || {}; } catch (e) { guest = {}; }
    if (Object.keys(guest).length) {
      var merged = getCart();
      Object.keys(guest).forEach(function (k) {
        if (merged[k]) merged[k].qty += guest[k].qty;
        else merged[k] = guest[k];
      });
      saveCart(merged);
      try { sessionStorage.removeItem(GUEST_CART); } catch (e) {}
    }
    return getCart();
  }

  function buildInit(options) {
    options = options || {};
    var init = { method: options.method || "GET", headers: {} };
    if (options.headers) {
      for (var k in options.headers) init.headers[k] = options.headers[k];
    }
    if (options.json !== undefined) {
      init.body = JSON.stringify(options.json);
      init.headers["Content-Type"] = "application/json";
    } else if (options.body !== undefined) {
      init.body = options.body; // e.g. FormData — let the browser set the header
    }
    return init;
  }

  // Public (unauthenticated) request.
  function apiFetch(path, options) {
    return fetch(url(path), buildInit(options));
  }

  function tryRefresh() {
    var rt = getRefresh();
    if (!rt) return Promise.resolve(false);
    return fetch(url("/api/auth/refresh"), {
      method: "POST", headers: { Authorization: "Bearer " + rt }
    }).then(function (res) {
      if (!res.ok) return false;
      return res.json().then(function (d) {
        if (d.access_token) { localStorage.setItem(ACCESS, d.access_token); return true; }
        return false;
      });
    }).catch(function () { return false; });
  }

  // Authenticated request with one automatic refresh retry; redirects to login on failure.
  function authFetch(path, options) {
    var init = buildInit(options);
    var at = getAccess();
    if (at) init.headers["Authorization"] = "Bearer " + at;
    return fetch(url(path), init).then(function (res) {
      if (res.status !== 401) return res;
      return tryRefresh().then(function (ok) {
        if (!ok) { clearSession(); redirectToLogin(); throw new Error("unauthorized"); }
        var retry = buildInit(options);
        retry.headers["Authorization"] = "Bearer " + getAccess();
        return fetch(url(path), retry).then(function (r2) {
          if (r2.status === 401) { clearSession(); redirectToLogin(); throw new Error("unauthorized"); }
          return r2;
        });
      });
    });
  }

  function redirectToLogin() {
    if (!/login\.html$/.test(window.location.pathname)) window.location.href = "login.html";
  }
  function requireAuth() {
    if (!isLoggedIn()) { window.location.href = "login.html"; return false; }
    return true;
  }
  function requireAdmin() {
    if (!isAdmin()) { window.location.href = "login.html"; return false; }
    return true;
  }
  function logout() { clearSession(); window.location.href = "index.html"; }

  // ----- Shared toast (works on any page; reuses #toastContainer if present) -----
  function ensureToastContainer() {
    var c = document.getElementById("toastContainer");
    if (c) return c;
    c = document.createElement("div");
    c.id = "toastContainer";
    c.className = "toast-container";
    // Minimal inline styling so the toast shows even on pages without the CSS.
    c.style.cssText = "position:fixed;bottom:32px;left:50%;transform:translateX(-50%);z-index:4000;display:flex;flex-direction:column;gap:8px;align-items:center;pointer-events:none";
    document.body.appendChild(c);
    return c;
  }
  function _escHtml(s) {
    var d = document.createElement('div');
    d.appendChild(document.createTextNode(s));
    return d.innerHTML;
  }
  function toast(msg, icon) {
    if (typeof document === "undefined") return;
    var c = ensureToastContainer();
    var t = document.createElement("div");
    t.className = "toast";
    if (!t.style.background) {
      t.style.cssText = "background:#1C1410;color:#fff;padding:12px 24px;border-radius:9999px;font-size:.8125rem;font-weight:500;box-shadow:0 12px 40px rgba(28,20,16,.12);opacity:0;transform:translateY(20px);transition:all .35s ease;display:flex;align-items:center;gap:8px";
    }
    t.innerHTML = '<iconify-icon icon="' + (icon || "lucide:info") + '" width="16"></iconify-icon> ' + _escHtml(msg);
    c.appendChild(t);
    requestAnimationFrame(function () { t.classList.add("toast--visible"); t.style.opacity = "1"; t.style.transform = "translateY(0)"; });
    setTimeout(function () { t.classList.remove("toast--visible"); t.style.opacity = "0"; setTimeout(function () { t.remove(); }, 350); }, 3200);
  }

  // ----- handleApiCall: one place that turns fetch failures into a toast -----
  // Usage:
  //   var res = await API.handleApiCall(function () { return API.authFetch(path, opts); });
  //   if (!res) return;              // network error already surfaced
  //   var data = await res.json();
  // Options: { silent, errorMessage, networkMessage, onError }
  function messageForStatus(res, fallback) {
    if (res.status === 429) return "Too many attempts. Please wait a minute and try again.";
    if (res.status === 401) return "Please log in to continue.";
    if (res.status === 403) return "You don't have access to do that.";
    if (res.status >= 500) return "The server had a problem. Please try again shortly.";
    return fallback || "Something went wrong. Please try again.";
  }
  function handleApiCall(doFetch, options) {
    options = options || {};
    var p;
    try { p = typeof doFetch === "function" ? doFetch() : doFetch; }
    catch (e) { p = Promise.reject(e); }
    return Promise.resolve(p).then(function (res) {
      if (res && !res.ok && !options.silent) {
        // Prefer a server-provided message, else a status-appropriate default.
        return res.clone().json().catch(function () { return null; }).then(function (body) {
          var msg = (body && (body.message || body.error)) || messageForStatus(res, options.errorMessage);
          toast(msg, "lucide:alert-circle");
          if (options.onError) { try { options.onError(res, body); } catch (e) {} }
          return res;
        });
      }
      return res;
    }).catch(function (err) {
      // Thrown by authFetch on unrecoverable 401 (already redirects) — stay quiet then.
      if (err && err.message === "unauthorized") return null;
      if (!options.silent) toast(options.networkMessage || "Could not reach the server. Check your connection and try again.", "lucide:x-circle");
      if (options.onError) { try { options.onError(null, null, err); } catch (e) {} }
      return null;
    });
  }

  window.apiUrl = url;
  window.API = {
    setSession: setSession, clearSession: clearSession, getAccess: getAccess,
    getRefresh: getRefresh, getUser: getUser, getUsername: getUsername,
    isLoggedIn: isLoggedIn, isAdmin: isAdmin,
    apiFetch: apiFetch, authFetch: authFetch, requireAuth: requireAuth,
    requireAdmin: requireAdmin, logout: logout, url: url,
    setReturnUrl: setReturnUrl, takeReturnUrl: takeReturnUrl,
    postLoginTarget: postLoginTarget, goPostLogin: goPostLogin,
    getCart: getCart, saveCart: saveCart, clearCart: clearCart, adoptGuestCart: adoptGuestCart,
    toast: toast, handleApiCall: handleApiCall
  };
})();
