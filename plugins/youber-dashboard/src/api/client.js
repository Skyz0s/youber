// Cliente API del dashboard (Fases 3-4).
// Todas las llamadas van al proxy del plugin: /youber-dashboard/api/* → bridge.

const API_BASE = "/youber-dashboard/api";

export const PIPELINES = [
  "screen-demo",
  "documentary-montage",
  "animated-explainer",
  "hybrid",
  "cinematic",
  "talking-head",
  "podcast-repurpose",
  "clip-factory",
];

export const STYLES = ["clean", "classic", "box", "minimal"];

export const CATEGORIES = [
  "tecnología",
  "educación",
  "ciencia",
  "gaming",
  "música",
  "negocios",
  "salud",
  "viajes",
  "cocina",
  "moda",
  "deportes",
  "noticias",
  "entretenimiento",
  "cine",
  "animación",
  "podcast",
  "manualidades",
  "fotografía",
  "marketing",
  "estilo_de_vida",
];

export const PROVIDER_LABELS = {
  pexels: "Pexels",
  minimax: "MiniMax",
  spotify: "Spotify",
  youtube_research: "YouTube API",
  youtube_upload: "YouTube upload",
  openmontage: "OpenMontage",
};

/**
 * Traduce errores técnicos a mensajes humanos (Fase 4).
 * El iframe del tab va con sandbox, así que nada de ventanas nativas:
 * los errores se muestran en la propia página.
 */
function friendlyMessage(err) {
  const raw = err?.message || String(err);
  if (/^Red:/i.test(raw)) {
    return "No se pudo conectar con el servicio local. Comprueba que la Gateway esté activa e inténtalo de nuevo.";
  }
  if (/no JSON/i.test(raw)) {
    return "El servicio devolvió una respuesta inesperada. Recarga la página e inténtalo de nuevo.";
  }
  if (/bridge falló/i.test(raw)) {
    return "El servicio interno falló al procesar la petición. Mira los logs de la Gateway.";
  }
  return raw;
}

async function request(path, options = {}) {
  let res;
  try {
    res = await fetch(`${API_BASE}/${path}`, options);
  } catch (err) {
    throw new Error(friendlyMessage({ message: `Red: ${err.message}` }));
  }
  let envelope;
  try {
    envelope = await res.json();
  } catch {
    throw new Error(friendlyMessage({ message: "Respuesta no JSON" }));
  }
  if (!envelope || envelope.ok !== true) {
    throw new Error(friendlyMessage({ message: envelope?.error || `HTTP ${res.status}` }));
  }
  return envelope.data;
}

export function apiGet(path, params = {}) {
  const qs = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") qs.set(key, String(value));
  }
  const suffix = qs.toString() ? `?${qs}` : "";
  return request(`${path}${suffix}`);
}

export function apiPostJobs(body) {
  return request("jobs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function fmtSeconds(seconds) {
  if (seconds === null || seconds === undefined) return "-";
  const total = Math.round(Number(seconds));
  const m = Math.floor(total / 60);
  const s = total % 60;
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

export function fmtDate(iso) {
  if (!iso) return "-";
  const d = new Date(iso);
  return isNaN(d) ? iso : d.toLocaleString();
}

export function downloadText(filename, text, mime = "text/csv") {
  const blob = new Blob([text], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

export function toCsv(rows) {
  if (!rows.length) return "";
  const headers = Object.keys(rows[0]);
  const escape = (v) => {
    const s = v === null || v === undefined ? "" : String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  return [headers.join(","), ...rows.map((r) => headers.map((h) => escape(r[h])).join(","))].join("\n");
}

export function downloadUrlForJob(jobId) {
  return `${API_BASE}/jobs/download?id=${encodeURIComponent(jobId)}`;
}

// ---------------------------------------------------------------------------
// Diálogo de confirmación (Fase 4) — sin window.confirm (bloqueado en el
// sandbox del tab). Devuelve una promesa: true si el usuario confirma.
// ---------------------------------------------------------------------------

export function askConfirm(message, { title = "Confirmar", confirmLabel = "Confirmar", danger = false } = {}) {
  return new Promise((resolve) => {
    const overlay = document.createElement("div");
    overlay.className = "yb-modal-backdrop";
    overlay.innerHTML = `
      <div class="yb-modal" role="dialog" aria-modal="true">
        <h3 class="yb-modal-title"></h3>
        <p class="yb-modal-text"></p>
        <div class="yb-row-actions yb-modal-actions">
          <button class="yb-btn secondary yb-modal-cancel" type="button">Cancelar</button>
          <button class="yb-btn ${danger ? "danger" : ""} yb-modal-ok" type="button"></button>
        </div>
      </div>`;
    overlay.querySelector(".yb-modal-title").textContent = title;
    overlay.querySelector(".yb-modal-text").textContent = message;
    overlay.querySelector(".yb-modal-ok").textContent = confirmLabel;
    overlay.querySelector(".yb-modal-ok").className = `yb-btn ${danger ? "danger" : ""}`.trim();

    const close = (result) => {
      overlay.remove();
      resolve(result);
    };
    overlay.querySelector(".yb-modal-cancel").addEventListener("click", () => close(false));
    overlay.querySelector(".yb-modal-ok").addEventListener("click", () => close(true));
    overlay.addEventListener("click", (ev) => {
      if (ev.target === overlay) close(false);
    });
    document.body.appendChild(overlay);
    overlay.querySelector(".yb-modal-ok").focus();
  });
}

// ---------------------------------------------------------------------------
// Mini-store compartido entre páginas (pista seleccionada en Música →
// Producción). Persiste en localStorage cuando el sandbox lo permite y cae a
// memoria si no; sobrevive a los cambios de ruta del SPA.
// ---------------------------------------------------------------------------

const TRACK_KEY = "youber.selectedTrack";
let selectedTrack = null;

function trackStorage() {
  try {
    const raw = window.localStorage.getItem(TRACK_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return selectedTrack;
  }
}

export function rememberTrack(track) {
  selectedTrack = track ? { id: track.id, title: track.title } : null;
  try {
    if (selectedTrack) window.localStorage.setItem(TRACK_KEY, JSON.stringify(selectedTrack));
    else window.localStorage.removeItem(TRACK_KEY);
  } catch {
    /* sandbox sin localStorage: vale la memoria de módulo */
  }
}

export function consumeTrack() {
  const stored = trackStorage();
  selectedTrack = null;
  try {
    window.localStorage.removeItem(TRACK_KEY);
  } catch {
    /* sin localStorage */
  }
  return stored;
}
