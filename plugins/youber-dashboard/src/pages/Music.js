import { LitElement, html } from "lit";
import { apiGet, fmtSeconds, rememberTrack } from "../api/client.js";
import "../components/Input.js";
import "../components/Button.js";
import "../components/Table.js";
import "../components/Spinner.js";

// Música: catálogo, búsqueda y letras (sidecar).
export class YbPageMusic extends LitElement {
  static properties = {
    tracks: { type: Array },
    query: { type: String },
    selected: { type: Object },
    lyrics: { type: Object },
    loading: { type: Boolean },
    error: { type: String },
  };

  createRenderRoot() {
    return this;
  }

  constructor() {
    super();
    this.tracks = [];
    this.query = "";
    this.selected = null;
    this.lyrics = null;
    this.loading = false;
    this.error = "";
  }

  connectedCallback() {
    super.connectedCallback();
    this._load("");
  }

  async _load(query) {
    this.loading = true;
    this.error = "";
    try {
      const data = query
        ? await apiGet("music/search", { query, limit: 50 })
        : await apiGet("music/list", { limit: 50 });
      this.tracks = data.tracks || [];
    } catch (err) {
      this.error = err.message;
    }
    this.loading = false;
  }

  async _select(track) {
    this.selected = track;
    this.lyrics = null;
    try {
      const data = await apiGet("music/lyrics", { query: track.id });
      this.lyrics = data.lyrics;
      this._lyricsHint = data.hint || "";
    } catch (err) {
      this._lyricsHint = err.message;
      this.lyrics = null;
    }
  }

  _useInProduction() {
    // Mini-store compartido: sobrevive al cambio de ruta (evento window no).
    rememberTrack({ id: this.selected.id, title: this.selected.title });
    location.hash = "#/production";
  }

  render() {
    const timed = this.lyrics?.timed === true;
    return html`
      <h1 class="yb-page-title">🎵 Música</h1>
      <div class="yb-card">
        <div class="yb-field-row">
          <yb-input label="Buscar por título/artista" .value=${this.query} @yb-change=${(e) => (this.query = e.detail.value)} placeholder="ej: Bohemian"></yb-input>
        </div>
        <div class="yb-row-actions">
          <yb-button ?busy=${this.loading} @yb-click=${() => this._load(this.query)}>Buscar</yb-button>
          <yb-button variant="secondary" @yb-click=${() => this._load("")}>Ver todo</yb-button>
        </div>
      </div>
      ${this.error ? html`<p class="yb-err">${this.error}</p>` : ""}
      <div class="yb-card" style="margin-top:1rem">
        <h3>Catálogo (${this.tracks.length})</h3>
        <yb-table
          .columns=${[
            { key: "title", label: "Título" },
            { key: "artist", label: "Artista" },
            { key: "duration", label: "Duración" },
            { key: "moods", label: "Moods" },
            { key: "favorite", label: "Fav" },
          ]}
          .rows=${this.tracks.map((t) => ({ ...t, moods: (t.moods || []).join(", "), duration: fmtSeconds(t.duration), artist: t.artist || "—" }))}
          empty="Catálogo vacío (youber-music scan)"
          @yb-row=${(e) => this._select(e.detail.row)}
        ></yb-table>
        <p class="yb-muted">💡 Haz clic en una canción para ver su letra.</p>
      </div>
      ${this.selected ? this._renderLyrics() : ""}
    `;
  }

  _renderLyrics() {
    const timed = this.lyrics?.timed === true;
    return html`
      <div class="yb-card" style="margin-top:1rem">
        <h3>📜 ${this.selected.title}${this.selected.artist ? ` — ${this.selected.artist}` : ""}
          ${this.lyrics ? html`<span class="yb-chip">${timed ? "con timestamps" : "texto plano"}</span>` : ""}
        </h3>
        ${this.lyrics
          ? html`
              <div class="yb-lyrics">${this.lyrics.lines.map((l) => l.text).join("\n")}</div>
              <div class="yb-row-actions">
                <yb-button @yb-click=${() => this._useInProduction()}>🎬 Usar en producción</yb-button>
              </div>
            `
          : html`<p class="yb-muted">${this._lyricsHint || "Sin letra disponible."}</p>`}
      </div>
    `;
  }
}
customElements.define("yb-page-music", YbPageMusic);
