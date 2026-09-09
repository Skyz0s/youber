import { LitElement, html } from "lit";
import { apiGet, fmtSeconds, PROVIDER_LABELS } from "../api/client.js";

// Página principal: resumen del sistema + claves configuradas.
export class YbPageDashboard extends LitElement {
  static properties = { status: { type: Object }, error: { type: String } };

  createRenderRoot() {
    return this;
  }

  connectedCallback() {
    super.connectedCallback();
    this._load();
  }

  async _load() {
    this.error = "";
    try {
      this.status = await apiGet("status");
    } catch (err) {
      this.error = err.message;
    }
  }

  _go(hash) {
    window.dispatchEvent(new CustomEvent("yb-nav", { detail: { id: hash }, bubbles: true, composed: true }));
  }

  render() {
    const s = this.status;
    return html`
      <h1 class="yb-page-title">📊 Dashboard</h1>
      ${this.error ? html`<p class="yb-err">${this.error}</p>` : ""}
      ${s ? this._renderContent(s) : html`<p class="yb-muted">Cargando estado…</p>`}
    `;
  }

  _renderContent(s) {
    return html`
      <div class="yb-cols yb-grid">
        <div class="yb-card yb-stat"><b>${s.music.tracks}</b><span>canciones en catálogo</span></div>
        <div class="yb-card yb-stat"><b>${s.jobs.queued} / ${s.jobs.running}</b><span>jobs en cola / ejecución</span></div>
        <div class="yb-card yb-stat"><b>${s.schedule.enabled} / ${s.schedule.jobs}</b><span>tareas programadas activas</span></div>
        <div class="yb-card yb-stat">
          <b>${s.system.ffmpeg ? "✅" : "❌"}</b>
          <span>FFmpeg ${s.system.ffmpeg ? "disponible" : "no instalado"}</span>
        </div>
      </div>
      <div class="yb-card" style="margin-top:1rem">
        <h3>Claves configuradas</h3>
        <div style="display:flex;gap:0.5rem;flex-wrap:wrap">
          ${Object.entries(s.providers).map(
            ([key, ok]) => html`
              <span class="yb-chip"><span class="dot ${ok ? "ok" : "off"}"></span>${PROVIDER_LABELS[key] || key}</span>
            `
          )}
        </div>
        <div class="yb-row-actions">
          <button class="yb-btn" @click=${() => (location.hash = "#/production")}>🎬 Nuevo Workflow</button>
          <button class="yb-btn secondary" @click=${() => this._load()}>Refrescar</button>
        </div>
      </div>
    `;
  }
}
customElements.define("yb-page-dashboard", YbPageDashboard);
