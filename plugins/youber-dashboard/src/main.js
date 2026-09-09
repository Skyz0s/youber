import { html, render } from "lit";
import "./styles/global.css";
import "./App.js";

const root = document.getElementById("app");
if (!root) {
  throw new Error("Falta #app en index.html");
}

render(html`<yb-app></yb-app>`, root);
