// Cliente API del dashboard (Fase 3).
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

async function request(path, options = {}) {
  let res;
  try {
    res = await fetch(`${API_BASE}/${path}`, options);
  } catch (err) {
    throw new Error(`Red: ${err.message}`);
  }
  let envelope;
  try {
    envelope = await res.json();
  } catch {
    throw new Error(`Respuesta no JSON (HTTP ${res.status})`);
  }
  if (!envelope || envelope.ok !== true) {
    throw new Error(envelope?.error || `HTTP ${res.status}`);
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

// Mini-store compartido entre páginas (pista seleccionada en Música →
// Producción). El estado de módulo sobrevive a los cambios de ruta del SPA.
let selectedTrack = null;

export function rememberTrack(track) {
  selectedTrack = track ? { id: track.id, title: track.title } : null;
}

export function consumeTrack() {
  const track = selectedTrack;
  selectedTrack = null;
  return track;
}
