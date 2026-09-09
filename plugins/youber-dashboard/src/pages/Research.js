import { LitElement, html } from "lit";
import { apiGet, CATEGORIES, downloadText, toCsv, fmtSeconds } from "../api/client.js";
import "../components/Input.js";
import "../components/Select.js";
import "../components/Button.js";
import "../components/Table.js";
import "../components/Spinner.js";

const MODES = ["auto", "api", "html", "demo"];

// Investigación: búsqueda de canales (discovery) + análisis detallado (research).
export class YbPageResearch extends LitElement {
  static properties = {
    query: { type: String },
    category: { type: String },
    mode: { type: String },
    limit: { type: String },
    results: { type: Array },
    detail: { type: Object },
    loading: { type: Boolean },
    error: { type: String },
  };

  createRenderRoot() {
    return this;
  }

  constructor() {
    super();
    this.query = "python";
    this.category = "";
    this.mode = "demo";
    this.limit = "10";
    this.results = [];
    this.detail = null;
    this.loading = false;
    this.error = "";
  }

  async _search() {
    this.loading = true;
    this.error = "";
    this.detail = null;
    try {
      const data = await apiGet("discovery/search", {
        query: this.query,
        category: this.category,
        mode: this.mode,
        limit: this.limit,
      });
      this.results = data.channels || [];
    } catch (err) {
      this.error = err.message;
      this.results = [];
    }
    this.loading = false;
  }

  async _analyze(channel) {
    this.loading = true;
    this.error = "";
    try {
      const data = await apiGet("research/channel", {
        channel: channel.url || channel.handle,
        limit: 10,
      });
      this.detail = { ...data, _channel: channel };
    } catch (err) {
      this.error = err.message;
    }
    this.loading = false;
  }

  _exportCsv() {
    const rows = this.results.map((c) => ({
      title: c.title,
      handle: c.handle || "",
      url: c.url,
      subscribers: c.subscriber_count ?? "",
      views: c.view_count ?? "",
      category: c.category ?? "",
      score: c.score ?? "",
    }));
    downloadText("youber_discovery.csv", toCsv(rows));
  }

  _exportVideosCsv() {
    if (!this.detail?.videos) return;
    const rows = this.detail.videos.map((v) => ({
      title: v.title,
      url: v.url,
      views: v.views,
      duration: v.duration,
      publish_date: v.publish_date ?? "",
    }));
    downloadText("youber_channel_videos.csv", toCsv(rows));
  }

  render() {
    return html`
      <h1 class="yb-page-title">🔎 Investigación</h1>
      <div class="yb-card">
        <div class="yb-field-row">
          <yb-input label="Tema" .value=${this.query} @yb-change=${(e) => (this.query = e.detail.value)}></yb-input>
          <yb-select label="Categoría" .value=${this.category} @yb-change=${(e) => (this.category = e.detail.value)} .options=${[{ value: "", label: "— cualquiera —" }, ...CATEGORIES.map((c) => ({ value: c, label: c }))]}></yb-select>
          <yb-select label="Modo" .value=${this.mode} @yb-change=${(e) => (this.mode = e.detail.value)} .options=${MODES.map((m) => ({ value: m, label: m }))}></yb-select>
          <yb-input label="Límite" .value=${this.limit} @yb-change=${(e) => (this.limit = e.detail.value)}></yb-input>
        </div>
        <div class="yb-row-actions">
          <yb-button ?busy=${this.loading} @yb-click=${() => this._search()}>Buscar</yb-button>
          <yb-button class="secondary" variant="secondary" ?disabled=${!this.results.length} @yb-click=${() => this._exportCsv()}>💾 Guardar CSV</yb-button>
        </div>
      </div>
      ${this.error ? html`<p class="yb-err">${this.error}</p>` : ""}
      <div class="yb-card" style="margin-top:1rem">
        <h3>Resultados (${this.results.length})</h3>
        <yb-table
          .columns=${[
            { key: "title", label: "Canal" },
            { key: "handle", label: "Handle" },
            { key: "subscriber_count", label: "Suscriptores" },
            { key: "view_count", label: "Vistas" },
            { key: "category", label: "Categoría" },
          ]}
          .rows=${this.results}
          empty="Sin resultados. Prueba con modo demo (sin red)."
          @yb-row=${(e) => this._analyze(e.detail.row)}
        ></yb-table>
        <p class="yb-muted">💡 Haz clic en una fila para analizar el canal en detalle.</p>
      </div>
      ${this.detail ? this._renderDetail() : ""}
    `;
  }

  _renderDetail() {
    const d = this.detail;
    return html`
      <div class="yb-card" style="margin-top:1rem">
        <h3>📡 ${d.name} (${d.handle || ""})</h3>
        <p class="yb-muted">Suscriptores: ${d.subscribers ?? "—"} · Vídeos totales: ${d.total_views ?? "—"}</p>
        <h3>Últimos vídeos (${(d.videos || []).length})</h3>
        <yb-table
          .columns=${[
            { key: "title", label: "Título" },
            { key: "views", label: "Vistas" },
            { key: "duration", label: "Duración" },
            { key: "publish_date", label: "Publicado" },
          ]}
          .rows=${(d.videos || []).map((v) => ({ ...v }))}
          empty="Sin vídeos"
        ></yb-table>
        <div class="yb-row-actions">
          <yb-button variant="secondary" ?disabled=${!(d.videos || []).length} @yb-click=${() => this._exportVideosCsv()}>💾 Vídeos CSV</yb-button>
        </div>
      </div>
    `;
  }
}
customElements.define("yb-page-research", YbPageResearch);
