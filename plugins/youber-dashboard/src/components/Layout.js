import { LitElement, html } from "lit";

const NAV = [
  { id: "dashboard", label: "📊 Dashboard", hash: "#/dashboard" },
  { id: "research", label: "🔎 Investigación", hash: "#/research" },
  { id: "music", label: "🎵 Música", hash: "#/music" },
  { id: "production", label: "🎬 Producción", hash: "#/production" },
  { id: "monitor", label: "🖥️ Monitorización", hash: "#/monitor" },
];

export class YbLayout extends LitElement {
  static properties = { active: { type: String } };

  // Light DOM: los estilos globales (global.css) aplican directamente.
  createRenderRoot() {
    return this;
  }

  constructor() {
    super();
    this.active = "dashboard";
  }

  render() {
    return html`
      <div class="yb-layout">
        <aside class="yb-sidebar">
          <div class="yb-brand">⚙️ Youber</div>
          ${NAV.map(
            (item) => html`
              <a
                class="yb-nav ${this.active === item.id ? "active" : ""}"
                href=${item.hash}
                @click=${() => this._navigate(item.id)}
              >${item.label}</a>
            `
          )}
        </aside>
        <main class="yb-main"><slot></slot></main>
      </div>
    `;
  }

  _navigate(id) {
    // Prevenimos el salto nativo y delegamos el cambio de ruta a App.
    this.dispatchEvent(new CustomEvent("yb-nav", { detail: { id }, bubbles: true, composed: true }));
  }
}
customElements.define("yb-layout", YbLayout);
