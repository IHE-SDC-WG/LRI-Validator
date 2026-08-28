"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

class Element {
  constructor(id) {
    this.id = id || "";
    this.value = "";
    this.textContent = "";
    this.hidden = false;
    this.checked = true;
    this.dataset = {};
    this.files = [];
    this.children = [];
    this.listeners = {};
  }
  get firstChild() { return this.children[0] || null; }
  addEventListener(name, callback) { (this.listeners[name] ||= []).push(callback); }
  appendChild(child) { this.children.push(child); return child; }
  removeChild(child) { this.children.splice(this.children.indexOf(child), 1); }
  focus() {}
  setSelectionRange() {}
  setAttribute(name, value) { this[name] = value; }
  click() { (this.listeners.click || []).forEach(callback => callback({ target: this })); }
}

const ids = [
  "message", "file", "sample", "load-sample", "validate", "clear", "input-error", "startup-error",
  "no-report", "report", "status", "result-label", "style-label", "ruleset-label", "counts",
  "findings", "coverage", "download", "print"
];
const elements = Object.fromEntries(ids.map(id => [id, new Element(id)]));
elements.report.hidden = true;
const severities = ["error", "warning", "information"].map(value => {
  const element = new Element();
  element.dataset.severity = value;
  return element;
});
const document = {
  documentElement: new Element("html"),
  getElementById(id) { return elements[id]; },
  createElement() { return new Element(); },
  querySelectorAll(selector) {
    if (selector === "[data-severity]:checked") return severities.filter(element => element.checked);
    if (selector === "[data-severity]") return severities;
    return [];
  }
};
const context = {
  console,
  document,
  Blob,
  URL: { createObjectURL() { return "blob:test"; }, revokeObjectURL() {} }
};
context.window = context;
context.globalThis = context;
context.setTimeout = callback => callback();
context.print = () => {};
context.FileReader = class {};
vm.createContext(context);

const html = fs.readFileSync("dist/naaccr-lri-validator.html", "utf8");
const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(match => match[1]);
assert.equal(scripts.length, 4, "expected diagnostic, catalog, validator, and application scripts");
scripts.forEach(script => vm.runInContext(script, context));

assert.equal(document.documentElement["data-validator-ready"], "true");
assert.equal(elements["startup-error"].hidden, true);
assert.equal(context.__LRI_CATALOG__.schema_version, "1.0.0");
assert.deepEqual(Object.keys(context.__LRI_SAMPLES__).sort(), [
  "cap-ecp", "structured-narrative", "synoptic-segmented", "synoptic-summary", "unstructured-narrative"
]);
assert.deepEqual(
  JSON.parse(JSON.stringify(context.__LRI_CATALOG__)),
  JSON.parse(fs.readFileSync("src/lri_validator/catalog.json", "utf8"))
);
for (const name of Object.keys(context.__LRI_SAMPLES__)) {
  assert.equal(context.__LRI_SAMPLES__[name], fs.readFileSync(`tests/fixtures/valid/${name}.hl7`, "utf8"));
}

elements.message.value = context.__LRI_SAMPLES__["unstructured-narrative"];
elements.validate.click();
assert.equal(elements.report.hidden, false, "Validate should display a report");
assert.match(elements["result-label"].textContent, /^(PASS|FAIL):/);

elements.file.value = "selected.hl7";
elements.clear.click();
assert.equal(elements.message.value, "", "Clear should empty pasted or uploaded text");
assert.equal(elements.file.value, "", "Clear should reset the file control");
assert.equal(elements.report.hidden, true, "Clear should reset the report");
