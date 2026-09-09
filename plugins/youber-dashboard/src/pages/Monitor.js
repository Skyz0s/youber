import { LitElement, html } from "lit";
import { apiGet, fmtDate } from "../api/client.js";
import "../components/Button.js";
import "../components/Table.js";
import "../components/Spinner.js";

// Monitorización: tareas programadas, historial de jobs y estado de subidas.
export class YbPageMonitor extends LitElement {
  static properties = {
    schedule: { type: Array },
    jobs: { type: Array },
    uploads: { type: Object },
    loading: { type: Boolean },
    error: { type: String },
  };

  createRenderRoot() {
    return this;
  }

  constructor() {
    super();
    this.schedule = [];
    this.jobs = [];
    this.uploads = null;
    this.loading = false;
    this.error = "";
  }

  connectedCallback() {
    super.connectedCallback();
    this._refresh();
  }

  async _refresh() {
    this.loading = true;
    this.error = "";
    try {
      const [scheduleData, jobsData, uploadsData] = await Promise.all([
        apiGet("schedule/list"),
        apiGet("jobs/history", { limit: 20 }),
        apiGet("uploads/status"),
      ]);
      this.schedule = scheduleData.jobs || [];
      this.jobs = jobsData.jobs || [];
      this.uploads = uploadsData;
    } catch (err) {
      this.error = err.message;
    }
    this.loading = false;
  }

  render() {
    return html`
      <h1 class="yb-page-title">🖥️ Monitorización</h1>
      ${this.error ? html`<p class="yb-err">${this.error}</p>` : ""}
      <div class="yb-row-actions">
        <yb-button ?busy=${this.loading} @yb-click=${() => this._refresh()}>Refrescar</yb-button>
      </div>

      <div class="yb-card" style="margin-top:1rem">
        <h3>Tareas programadas (${this.schedule.length})</h3>
        <yb-table
          .columns=${[
            { key: "name", label: "Nombre" },
            { key: "job_type", label: "Tipo" },
            { key: "schedule_type", label: "Schedule" },
            { key: "schedule_value", label: "Valor" },
            { key: "enabled", label: "Activa" },
            { key: "last_run", label: "Última ejecución" },
          ]}
          .rows=${this.schedule.map((j) => ({ ...j, last_run: fmtDate(j.last_run), enabled: j.enabled }))}
          empty="No hay tareas programadas (youber-schedule)"
        ></yb-table>
      </div>

      <div class="yb-card" style="margin-top:1rem">
        <h3>Historial de jobs (${this.jobs.length})</h3>
        <yb-table
          .columns=${[
            { key: "id", label: "Id" },
            { key: "type", label: "Tipo" },
            { key: "status", label: "Estado" },
            { key: "exit_code", label: "Exit" },
            { key: "created_at", label: "Creado" },
            { key: "output_path", label: "Salida" },
          ]}
          .rows=${this.jobs.map((j) => ({ ...j, created_at: fmtDate(j.created_at), output_path: j.output_path || "—" }))}
          empty="Sin jobs todavía"
        ></yb-table>
      </div>

      <div class="yb-card" style="margin-top:1rem">
        <h3>Subida a YouTube</h3>
        ${this.uploads
          ? html`
              <p class="yb-muted">
                Cliente OAuth: <b class=${this.uploads.youtube.client_configured ? "yb-ok" : ""}>${this.uploads.youtube.client_configured ? "configurado" : "no configurado"}</b>
                · Token guardado: <b class=${this.uploads.youtube.token_saved ? "yb-ok" : ""}>${this.uploads.youtube.token_saved ? "sí" : "no"}</b>
                · ${this.uploads.youtube.ready ? html`<span class="yb-ok">Listo para subir</span>` : html`<span class="yb-muted">Ejecuta: youber-upload auth</span>`}
              </p>
            `
          : ""}
      </div>
    `;
  }
}
customElements.define("yb-page-monitor", YbPageMonitor);
