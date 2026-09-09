import { LitElement, html } from "lit";

export class YbSelect extends LitElement {
  // options: [{ value, label }]
  static properties = {
    label: { type: String },
    options: { type: Array },
    value: { type: String },
  };

  createRenderRoot() {
    return this;
  }

  constructor() {
    super();
    this.label = "";
    this.options = [];
    this.value = "";
  }

  _onChange(ev) {
    this.value = ev.target.value;
    this.dispatchEvent(new CustomEvent("yb-change", { detail: { value: this.value }, bubbles: true, composed: true }));
  }

  render() {
    return html`
      <div class="yb-field">
        ${this.label ? html`<label>${this.label}</label>` : ""}
        <select class="yb-select" .value=${this.value} @change=${this._onChange}>
          ${this.options.map(
            (opt) => html`<option value=${opt.value} ?selected=${String(opt.value) === String(this.value)}>${opt.label}</option>`
          )}
        </select>
      </div>
    `;
  }
}
customElements.define("yb-select", YbSelect);
