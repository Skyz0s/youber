import { LitElement, html, css } from "lit";

export class YbTable extends LitElement {
  // columns: [{ key, label }] · rows: [objeto] · rowKey: campo id único
  static properties = {
    columns: { type: Array },
    rows: { type: Array },
    rowKey: { type: String },
    empty: { type: String },
  };

  static styles = css`
    :host { display: block; overflow-x: auto; }
    table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
    th, td { text-align: left; padding: 0.4rem 0.55rem; border-bottom: 1px solid var(--border, #21262d); vertical-align: top; }
    th { color: var(--text-dim, #8b949e); font-weight: 600; white-space: nowrap; }
    tbody tr { cursor: pointer; }
    tbody tr:hover { background: var(--bg-input, #0d1117); }
    .empty { color: var(--text-dim, #8b949e); padding: 1rem 0.5rem; text-align: center; }
  `;

  constructor() {
    super();
    this.columns = [];
    this.rows = [];
    this.rowKey = "id";
    this.empty = "Sin datos";
  }

  _onRowClick(row) {
    this.dispatchEvent(new CustomEvent("yb-row", { detail: { row }, bubbles: true, composed: true }));
  }

  _cell(row, key) {
    const value = row[key];
    if (value === null || value === undefined) return "—";
    if (typeof value === "boolean") return value ? "✓" : "—";
    return String(value);
  }

  render() {
    return html`
      <table>
        <thead>
          <tr>${this.columns.map((c) => html`<th>${c.label}</th>`)}</tr>
        </thead>
        <tbody>
          ${this.rows.length === 0
            ? html`<tr><td class="empty" colspan=${this.columns.length}>${this.empty}</td></tr>`
            : this.rows.map(
                (row) => html`
                  <tr @click=${() => this._onRowClick(row)}>
                    ${this.columns.map((c) => html`<td>${this._cell(row, c.key)}</td>`)}
                  </tr>
                `
              )}
        </tbody>
      </table>
    `;
  }
}
customElements.define("yb-table", YbTable);
