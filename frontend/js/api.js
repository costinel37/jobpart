const API_BASE = (window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1")
  ? "http://localhost:8080/api"
  : window.location.origin + "/api";

function getToken() {
  return localStorage.getItem("token");
}

function getUser() {
  const u = localStorage.getItem("user");
  return u ? JSON.parse(u) : null;
}

function saveSession(data) {
  localStorage.setItem("token", data.access_token);
  localStorage.setItem("user", JSON.stringify({ id: data.user_id, nume: data.nume, rol: data.rol }));
}

function logout() {
  localStorage.removeItem("token");
  localStorage.removeItem("user");
  window.location.href = "/static/login.html";
}

async function apiFetch(path, options = {}) {
  const token = getToken();
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const res = await fetch(API_BASE + path, { ...options, headers });

  const data = await res.json().catch(() => ({}));
  if (res.status === 401 && !options.skipAuth) {
    if (token) { logout(); return; }
  }
  if (!res.ok) {
    const msg = Array.isArray(data.detail)
      ? data.detail.map(e => e.msg || e.message || JSON.stringify(e)).join(", ")
      : (data.detail || "Eroare la server");
    throw new Error(msg);
  }
  return data;
}

function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#x27;');
}

function formatData(dateStr) {
  return new Date(dateStr).toLocaleDateString("ro-RO", { day: "2-digit", month: "long", year: "numeric" });
}

function statusBadge(status) {
  const colors = {
    trimisa: "bg-blue-100 text-blue-700",
    vizualizata: "bg-yellow-100 text-yellow-700",
    acceptata: "bg-green-100 text-green-700",
    respinsa: "bg-red-100 text-red-700",
  };
  const labels = { trimisa: "Trimisă", vizualizata: "Vizualizată", acceptata: "Acceptată", respinsa: "Respinsă" };
  return `<span class="px-2 py-1 rounded-full text-xs font-semibold ${colors[status] || ''}">${labels[status] || status}</span>`;
}

function updateNav() {
  const user = getUser();
  const navAuth = document.getElementById("nav-auth");
  const navUser = document.getElementById("nav-user");
  if (!navAuth || !navUser) return;

  if (user) {
    navAuth.classList.add("hidden");
    navUser.classList.remove("hidden");
    const nameEl = document.getElementById("nav-username");
    if (nameEl) nameEl.textContent = user.nume;
    const dashLink = document.getElementById("nav-dashboard");
    if (dashLink) {
      if (user.rol === "candidat") dashLink.href = "/static/dashboard-candidat.html";
      else if (user.rol === "angajator") dashLink.href = "/static/dashboard-angajator.html";
      else if (user.rol === "admin") dashLink.href = "/static/admin.html";
    }
    initNotifBell();
  } else {
    navAuth.classList.remove("hidden");
    navUser.classList.add("hidden");
  }
}

async function initNotifBell() {
  const bell = document.getElementById("nav-notif-bell");
  if (!bell || !getToken()) return;
  try {
    const r = await apiFetch("/notificari/necitite/count");
    const badge = bell.querySelector(".notif-badge");
    if (!badge) return;
    if (r && r.count > 0) {
      badge.textContent = r.count > 9 ? "9+" : r.count;
      badge.classList.remove("hidden");
    } else {
      badge.classList.add("hidden");
    }
  } catch (e) {}
}
