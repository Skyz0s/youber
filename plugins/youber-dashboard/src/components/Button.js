import { LitElement, html, css } from "lit";
import "./Spinner.js";

export class YbButton extends LitElement {
  static properties = {
    variant: { type: String },
    disabled: { type: Boolean },
    busy: { type: Boolean },
  };

  static styles = css`
    :host { display: inline-block; }
    button {
      display: inline-flex; align-items: center; gap: 0.45rem;
      background: var(--accent, #2f81f7); color: #fff; border: 0;
      border-radius: 8px; padding: 0.45rem 1rem; font-size: 0.88rem;
      font-family: inherit; cursor: pointer; transition: filter 0.15s;
    }
    button:hover:not(:disabled) { filter: brightness(1.15); }
    button:disabled { opacity: 0.55; cursor: default; }
    button.secondary { background: var(--border-strong, #30363d); }
    button.danger { background: var(--red, #f85149); }
  `;

  constructor() {
    super();
    this.variant = "primary";
    this.disabled = false;
    this.busy = false;
  }

  _onClick(ev) {
    if (this.disabled || this.busy) {
      ev.preventDefault();
      ev.stopPropagation();
      return;
    }
    this.dispatchEvent(new CustomEvent("yb-click", { detail: {}, bubbles: true, composed: true }));
  }

  render() {
    return html`
      <button
        class=${this.variant}
        ?disabled=${this.disabled || this.busy}
        @click=${this._onClick}
      >
        ${this.busy ? html`<yb-spinner style="--yb-spinner-size:14px"></yb-spinner>` : ""}
        <slot></slot>
      </button>
    `;
  }
}
customElements.define("yb-button", YbButton);
