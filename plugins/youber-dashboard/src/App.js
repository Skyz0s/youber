import { LitElement, html } from "lit";
import "./components/Layout.js";
import "./pages/Dashboard.js";
import "./pages/Research.js";
import "./pages/Music.js";
import "./pages/Production.js";
import "./pages/Monitor.js";

const VALID_ROUTES = new Set(["dashboard", "research", "music", "production", "monitor"]);

// App: enrutado por hash (#/dashboard, #/research, ...) + layout común.
export class YbApp extends LitElement {
  static properties = { route: { type: String } };

  createRenderRoot() {
    return this;
  }

  constructor() {
    super();
    this.route = "dashboard";
    this._onHash = () => this._sync();
  }

  connectedCallback() {
    super.connectedCallback();
    window.addEventListener("hashchange", this._onHash);
    this._sync();
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    window.removeEventListener("hashchange", this._onHash);
  }

  _sync() {
    const raw = location.hash.replace(/^#\/?/, "");
    const route = raw.split("?")[0];
    this.route = VALID_ROUTES.has(route) ? route : "dashboard";
  }

  _page() {
    switch (this.route) {
      case "research":
        return html`<yb-page-research></yb-page-research>`;
      case "music":
        return html`<yb-page-music></yb-page-music>`;
      case "production":
        return html`<yb-page-production></yb-page-production>`;
      case "monitor":
        return html`<yb-page-monitor></yb-page-monitor>`;
      default:
        return html`<yb-page-dashboard></yb-page-dashboard>`;
    }
  }

  render() {
    return html`<yb-layout active=${this.route}>${this._page()}</yb-layout>`;
  }
}
customElements.define("yb-app", YbApp);
