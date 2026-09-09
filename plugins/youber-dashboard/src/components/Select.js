import { LitElement, html } from "lit";

export class YbSelect extends LitElement {
  // options: [{ value, label }]
  static properties = {
    label: { type: String },
    options: { type: Array },
    value: { type: String },
    hint: { type: String },
    title: { type: String },
  };

  createRenderRoot() {
    return this;
  }

  constructor() {
    super();
    this.label = "";
    this.options = [];
    this.value = "";
    this.hint = "";
    this.title = "";
  }

  _onChange(ev) {
    this.value = ev.target.value;
    this.dispatchEvent(new CustomEvent("yb-change", { detail: { value: this.value }, bubbles: true, composed: true }));
  }

  render() {
    return html`
      <div class="yb-field">
        ${this.label ? html`<label title=${this.title || this.hint || this.label}>${this.label}</label>` : ""}
        <select class="yb-select" .value=${this.value} title=${this.title || this.hint || ""} @change=${this._onChange}>
          ${this.options.map(
            (opt) => html`<option value=${opt.value} ?selected=${String(opt.value) === String(this.value)}>${opt.label}</option>`
          )}
        </select>
        ${this.hint ? html`<p class="yb-hint">${this.hint}</p>` : ""}
      </div>
    `;
  }
}
customElements.define("yb-select", YbSelect);
