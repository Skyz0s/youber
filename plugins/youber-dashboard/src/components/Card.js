import { LitElement, html, css } from "lit";

export class YbCard extends LitElement {
  static properties = { title: { type: String } };

  static styles = css`
    :host {
      display: block; background: var(--bg-card, #161b22);
      border: 1px solid var(--border, #21262d); border-radius: 10px;
      padding: 1rem 1.1rem;
    }
    h3 { margin: 0 0 0.6rem; font-size: 0.85rem; color: var(--text-dim, #8b949e); font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em; }
    .body { color: var(--text, #e6edf3); }
  `;

  render() {
    return html`
      ${this.title ? html`<h3>${this.title}</h3>` : ""}
      <div class="body"><slot></slot></div>
    `;
  }
}
customElements.define("yb-card", YbCard);
