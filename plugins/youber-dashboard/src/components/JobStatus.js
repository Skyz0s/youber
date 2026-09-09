import { LitElement, html } from "lit";
import { apiGet, fmtDate, downloadUrlForJob } from "../api/client.js";
import "./Spinner.js";

const TERMINAL = new Set(["done", "failed"]);
const POLL_MS = 2000;

// Polling en tiempo real del estado de un job (cada 2 s) + log + descarga.
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
  }

  updated(changed) {
    if (changed.has("jobId") && this.jobId) {
      this._error = "";
      this.job = null;
      this._poll();
    }
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    this._stop();
  }

  _stop() {
    if (this._timer) {
      clearTimeout(this._timer);
      this._timer = null;
    }
  }

  async _poll() {
    if (!this.jobId) return;
    try {
      const job = await apiGet("jobs/status", { id: this.jobId });
      this.job = job;
      if (TERMINAL.has(job.status)) {
        this._stop();
        this.dispatchEvent(new CustomEvent("yb-job-done", { detail: { job }, bubbles: true, composed: true }));
        return;
      }
    } catch (err) {
      this._error = err.message;
    }
    if (this.isConnected) {
      this._timer = setTimeout(() => this._poll(), POLL_MS);
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
