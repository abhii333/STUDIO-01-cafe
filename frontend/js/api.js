/* STUDIO 01 — shared API client.
 * Handles the API base URL, JWT storage, authenticated fetches with auto-refresh,
 * and simple route guards. Exposed as window.API (+ window.apiUrl helper).
 */
(function () {
  var ACCESS = "studio01_access";
  var REFRESH = "studio01_refresh";
  var USER = "studio01_user";

  function url(path) {
    if (/^https?:\/\//.test(path)) return path;
    return (window.API_BASE || "") + path;
  }

  function setSession(data) {
    if (!data) return;
    if (data.access_token) localStorage.setItem(ACCESS, data.access_token);
    if (data.refresh_token) localStorage.setItem(REFRESH, data.refresh_token);
    if (data.user) localStorage.setItem(USER, JSON.stringify(data.user));
  }
  function clearSession() {
    localStorage.removeItem(ACCESS);
    localStorage.removeItem(REFRESH);
    localStorage.removeItem(USER);
    localStorage.removeItem("cart");
  }
  function getAccess() { return localStorage.getItem(ACCESS); }
  function getRefresh() { return localStorage.getItem(REFRESH); }
  function getUser() {
    try { return JSON.parse(localStorage.getItem(USER)); } catch (e) { return null; }
  }
  function isLoggedIn() { return !!getAccess(); }
  function isAdmin() { var u = getUser(); return !!u && u.role === "Admin"; }

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

  window.apiUrl = url;
  window.API = {
    setSession: setSession, clearSession: clearSession, getAccess: getAccess,
    getRefresh: getRefresh, getUser: getUser, isLoggedIn: isLoggedIn, isAdmin: isAdmin,
    apiFetch: apiFetch, authFetch: authFetch, requireAuth: requireAuth,
    requireAdmin: requireAdmin, logout: logout, url: url
  };
})();
