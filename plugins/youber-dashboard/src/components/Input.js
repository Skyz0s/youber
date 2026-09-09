import { LitElement, html } from "lit";

export class YbInput extends LitElement {
  static properties = {
    label: { type: String },
    value: { type: String },
    type: { type: String },
    placeholder: { type: String },
    hint: { type: String },
    title: { type: String },
  };

  createRenderRoot() {
    return this;
  }

  constructor() {
    super();
    this.label = "";
    this.value = "";
    this.type = "text";
    this.placeholder = "";
    this.hint = "";
    this.title = "";
  }

  _onInput(ev) {
    this.value = ev.target.value;
    this.dispatchEvent(new CustomEvent("yb-change", { detail: { value: this.value }, bubbles: true, composed: true }));
  }

  render() {
    return html`
      <div class="yb-field">
        ${this.label ? html`<label title=${this.title || this.hint || this.label}>${this.label}</label>` : ""}
        <input
          class="yb-input"
          type=${this.type}
          .value=${this.value}
          placeholder=${this.placeholder}
          title=${this.title || this.hint || ""}
          @input=${this._onInput}
        />
        ${this.hint ? html`<p class="yb-hint">${this.hint}</p>` : ""}
      </div>
    `;
  }
}
customElements.define("yb-input", YbInput);
