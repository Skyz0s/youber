import { LitElement, html } from "lit";

export class YbInput extends LitElement {
  static properties = {
    label: { type: String },
    value: { type: String },
    type: { type: String },
    placeholder: { type: String },
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
  }

  _onInput(ev) {
    this.value = ev.target.value;
    this.dispatchEvent(new CustomEvent("yb-change", { detail: { value: this.value }, bubbles: true, composed: true }));
  }

  render() {
    return html`
      <div class="yb-field">
        ${this.label ? html`<label>${this.label}</label>` : ""}
        <input
          class="yb-input"
          type=${this.type}
          .value=${this.value}
          placeholder=${this.placeholder}
          @input=${this._onInput}
        />
      </div>
    `;
  }
}
customElements.define("yb-input", YbInput);
