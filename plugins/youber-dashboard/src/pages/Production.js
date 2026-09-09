import { LitElement, html } from "lit";
import { apiGet, apiPostJobs, askConfirm, PIPELINES, STYLES, consumeTrack } from "../api/client.js";
import "../components/Input.js";
import "../components/Select.js";
import "../components/Button.js";
import "../components/JobStatus.js";

// Producción: formulario de youber-produce + estado del job en tiempo real.
export class YbPageProduction extends LitElement {
  static properties = {
    topic: { type: String },
    pipeline: { type: String },
    track: { type: String },
    trackTitle: { type: String },
    sync: { type: Boolean },
    style: { type: String },
    duration: { type: String },
    resolution: { type: String },
    tracks: { type: Array },
    jobId: { type: String },
    error: { type: String },
    busy: { type: Boolean },
  };

  createRenderRoot() {
    return this;
  }

  constructor() {
    super();
    this.topic = "";
    this.pipeline = "screen-demo";
    this.track = "";
    this.trackTitle = "";
    this.sync = false;
    this.style = "clean";
    this.duration = "30";
    this.resolution = "";
    this.tracks = [];
    this.jobId = "";
    this.error = "";
    this.busy = false;
  }

  connectedCallback() {
    super.connectedCallback();
    this._loadTracks();
    const pending = consumeTrack();
    if (pending) {
      this.track = pending.id;
      this.trackTitle = pending.title;
    }
  }

  async _loadTracks() {
    try {
      const data = await apiGet("music/list", { limit: 200 });
      this.tracks = data.tracks || [];
    } catch {
      this.tracks = [];
    }
  }

  async _submit(jobBody) {
    this.busy = true;
    this.error = "";
    this.jobId = "";
    try {
      const job = await apiPostJobs(jobBody);
      this.jobId = job.id;
    } catch (err) {
      this.error = err.message;
    }
    this.busy = false;
  }

  /** ¿Hay jobs activos? Si sí, pedimos confirmación antes de encolar otro. */
  async _guardActiveJobs() {
    try {
      const status = await apiGet("status");
      const active = (status.jobs?.queued || 0) + (status.jobs?.running || 0);
      if (active === 0) return true;
      return askConfirm(
        `Ya hay ${active} job(s) en cola/ejecución. ¿Lanzar este igualmente?`,
        { title: "Jobs activos", confirmLabel: "Sí, encolar", danger: true }
      );
    } catch {
      return true; // sin estado: no bloquear el lanzamiento
    }
  }

  async _produce() {
    if (!this.topic.trim()) {
      this.error = "El campo Topic es obligatorio";
      return;
    }
    if (!(await this._guardActiveJobs())) return;
    const body = {
      type: "produce",
      topic: this.topic.trim(),
      pipeline: this.pipeline,
      sync: this.sync,
      style: this.style,
      duration: this.duration || "30",
    };
    if (this.track) body.track = this.track;
    if (this.resolution.trim()) body.resolution = this.resolution.trim();
    this._submit(body);
  }

  async _workflowDemo() {
    if (!(await this._guardActiveJobs())) return;
    this._submit({ type: "workflow", demo: true, duration: 8 });
  }

  render() {
    const trackOptions = [
      { value: "", label: this.trackTitle ? `🎵 ${this.trackTitle} (seleccionada en Música)` : "— sin canción del catálogo —" },
      ...this.tracks.map((t) => ({ value: t.id, label: `${t.title}${t.artist ? ` — ${t.artist}` : ""}` })),
    ];
    return html`
      <h1 class="yb-page-title">🎬 Producción</h1>
      <div class="yb-card">
        <h3>Nuevo vídeo (youber-produce)</h3>
        <div class="yb-field-row">
          <yb-input label="Topic (tema)" .value=${this.topic} @yb-change=${(e) => (this.topic = e.detail.value)} placeholder="ej: Python tutorial" hint="Tema o guion del vídeo. Se usa como base de la investigación y del montaje." title="Tema del vídeo (obligatorio)"></yb-input>
          <yb-select label="Pipeline" .value=${this.pipeline} @yb-change=${(e) => (this.pipeline = e.detail.value)} .options=${PIPELINES.map((p) => ({ value: p, label: p }))} hint="Plantilla de montaje (screen-demo: escritura + b-roll)." title="Pipeline de producción"></yb-select>
        </div>
        <div class="yb-field-row">
          <yb-select label="Canción del catálogo (banda sonora)" .value=${this.track} @yb-change=${(e) => (this.track = e.detail.value)} .options=${trackOptions} hint="Pista del catálogo local. Se preselecciona desde la página Música." title="Pista de audio del catálogo"></yb-select>
          <yb-input label="Duración (s)" .value=${this.duration} @yb-change=${(e) => (this.duration = e.detail.value)} hint="Segundos del vídeo final (demo: 8)." title="Duración en segundos"></yb-input>
          <yb-input label="Resolución (opcional, WxH)" .value=${this.resolution} @yb-change=${(e) => (this.resolution = e.detail.value)} placeholder="1920x1080" hint="Vacío = la del pipeline." title="Resolución del vídeo"></yb-input>
        </div>
        <div class="yb-field" style="flex-direction:row;align-items:center;gap:0.6rem">
          <input type="checkbox" id="sync-toggle" ?checked=${this.sync} @change=${(e) => (this.sync = e.target.checked)} style="width:auto" />
          <label for="sync-toggle" style="margin:0" title="Busca la letra (sidecar) de la pista y quema subtítulos sincronizados (libass).">🎤 Sincronizar letras (--sync)</label>
        </div>
        ${this.sync
          ? html`
              <yb-select label="Estilo de subtítulos" .value=${this.style} @yb-change=${(e) => (this.style = e.detail.value)} .options=${STYLES.map((s) => ({ value: s, label: s }))} hint="clean / classic / box / minimal (estilos del renderizador libass)." title="Estilo visual de los subtítulos"></yb-select>
            `
          : ""}
        <div class="yb-row-actions">
          <yb-button variant="primary" ?busy=${this.busy} @yb-click=${() => this._produce()}>🎬 Producir vídeo</yb-button>
          <yb-button variant="secondary" ?busy=${this.busy} @yb-click=${() => this._workflowDemo()}>⚡ Workflow demo (FFmpeg)</yb-button>
        </div>
        ${this.error ? html`<p class="yb-err">${this.error}</p>` : ""}
      </div>
      ${this.jobId ? html`<div style="margin-top:1rem"><yb-job-status jobId=${this.jobId}></yb-job-status></div>` : ""}
    `;
  }
}
customElements.define("yb-page-production", YbPageProduction);
