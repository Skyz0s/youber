import { LitElement, html } from "lit";
import { apiGet, fmtDate, downloadUrlForJob } from "../api/client.js";
import "./Spinner.js";

const TERMINAL = new Set(["done", "failed"]);
const POLL_MS = 2000;
const BACKOFF_MS = 5000; // tras 60 s de ejecución, espaciar a 5 s

// Polling en tiempo real del estado de un job + log + descarga.
// Fase 4: con backoff (2 s → 5 s si el job va largo) y pausa cuando la
// pestaña no es visible (no malgastamos peticiones en segundo plano).
export class YbJobStatus extends LitElement {
  static properties = {
    jobId: { type: String },
    job: { type: Object },
    showLog: { type: Boolean },
  };

  createRenderRoot() {
    return this;
  }

  constructor() {
    super();
    this.jobId = "";
    this.job = null;
    this.showLog = false;
    this._timer = null;
    this._error = "";
    this._startedAt = null;
    this._onVisible = () => {
      if (!document.hidden && this.jobId && !this._timer) this._poll();
    };
  }

  updated(changed) {
    if (changed.has("jobId") && this.jobId) {
      this._error = "";
      this.job = null;
      this._startedAt = Date.now();
      this._poll();
    }
  }

  connectedCallback() {
    super.connectedCallback();
    document.addEventListener("visibilitychange", this._onVisible);
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    document.removeEventListener("visibilitychange", this._onVisible);
    this._stop();
  }

  _stop() {
    if (this._timer) {
      clearTimeout(this._timer);
      this._timer = null;
    }
  }

  _nextDelay() {
    const elapsed = Date.now() - (this._startedAt || Date.now());
    return elapsed > 60_000 ? BACKOFF_MS : POLL_MS;
  }

  async _poll() {
    if (!this.jobId) return;
    try {
      const job = await apiGet("jobs/status", { id: this.jobId });
      this.job = job;
      if (TERMINAL.has(job.status)) {
        this._stop();
        this.dispatchEvent(
          new CustomEvent("yb-job-done", { detail: { job }, bubbles: true, composed: true })
        );
        return;
      }
    } catch (err) {
      this._error = err.message;
    }
    if (this.isConnected && !document.hidden) {
      this._timer = setTimeout(() => this._poll(), this._nextDelay());
    }
  }

  _statusChip(status) {
    const labels = { queued: "en cola", running: "en ejecución", done: "completado", failed: "fallido" };
    return html`<span class="yb-status ${status}">${status === "running" ? html`<yb-spinner style="--yb-spinner-size:12px"></yb-spinner>` : ""} ${labels[status] || status}</span>`;
  }

  render() {
    if (!this.jobId) return html``;
    if (!this.job && !this._error) {
      return html`<p class="yb-muted">Consultando job <code>${this.jobId}</code>…</p>`;
    }
    const job = this.job;
    const logTail = job?.log ? job.log.slice(-2000) : "";
    return html`
      <div class="yb-card">
        <h3>Job ${job?.id || this.jobId} ${job ? this._statusChip(job.status) : ""}</h3>
        ${this._error ? html`<p class="yb-err">${this._error}</p>` : ""}
        ${job
          ? html`
              <p class="yb-muted">
                Tipo: ${job.type} · creado ${fmtDate(job.created_at)}
                ${job.exit_code !== null && job.exit_code !== undefined ? html`· exit ${job.exit_code}` : ""}
              </p>
              ${job.error ? html`<p class="yb-err">${job.error}</p>` : ""}
              ${job.output_path
                ? html`
                    <div class="yb-row-actions">
                      <a class="yb-btn" style="text-decoration:none;display:inline-block" href=${downloadUrlForJob(job.id)} download>⬇️ Descargar vídeo</a>
                      <code class="yb-muted">${job.output_path}</code>
                    </div>
                  `
                : ""}
              ${logTail
                ? html`
                    <div class="yb-row-actions">
                      <button class="yb-btn secondary" @click=${() => (this.showLog = !this.showLog)}>
                        ${this.showLog ? "Ocultar log" : "Ver log"}
                      </button>
                    </div>
                    ${this.showLog ? html`<pre class="yb-log">${logTail}</pre>` : ""}
                  `
                : ""}
            `
          : ""}
      </div>
    `;
  }
}
customElements.define("yb-job-status", YbJobStatus);
