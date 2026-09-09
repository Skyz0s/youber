import { LitElement, html, css } from "lit";

export class YbSpinner extends LitElement {
  static styles = css`
    :host { display: inline-flex; align-items: center; justify-content: center; }
    .ring {
      width: var(--yb-spinner-size, 18px);
      height: var(--yb-spinner-size, 18px);
      border: 2px solid var(--border-strong, #30363d);
      border-top-color: var(--accent, #2f81f7);
      border-radius: 50%;
      animation: spin 0.8s linear infinite;
    }
    @keyframes spin { to { transform: rotate(360deg); } }
  `;
  render() {
    return html`<span class="ring" role="status" aria-label="cargando"></span>`;
  }
}
customElements.define("yb-spinner", YbSpinner);
