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
    this.disabled = false;
    this.dataset = {};
    this.files = [];
    this.children = [];
    this.listeners = {};
    this.className = "";
  }
  get firstChild() { return this.children[0] || null; }
  addEventListener(name, callback) { (this.listeners[name] ||= []).push(callback); }
  appendChild(child) { this.children.push(child); return child; }
  removeChild(child) { this.children.splice(this.children.indexOf(child), 1); }
  focus() {}
  setSelectionRange() {}
  setAttribute(name, value) {
    this[name] = value;
    if (name.startsWith("data-")) this.dataset[name.slice(5).replace(/-([a-z])/g, (_match, letter) => letter.toUpperCase())] = value;
  }
  dispatch(name, event) {
    return Promise.all((this.listeners[name] || []).map(callback => callback(event || { target: this })));
  }
  click() { return this.dispatch("click", { target: this }); }
}

const ids = [
  "message", "file", "sample", "load-sample", "validate", "clear", "input-error", "startup-error",
  "no-report", "report", "status", "result-label", "style-label", "ruleset-label", "counts",
  "findings", "coverage", "download", "print", "content-panel", "content-disclosure", "seer-key",
  "run-content", "cancel-content", "content-status", "content-error", "content-report", "content-result",
  "content-result-label", "content-ruleset-label", "content-counts", "content-findings", "content-queries",
  "content-coverage", "content-download", "content-attribution"
];
const elements = Object.fromEntries(ids.map(id => [id, new Element(id)]));
elements.report.hidden = true;
elements["content-panel"].hidden = true;
elements["content-report"].hidden = true;
elements["content-error"].hidden = true;
elements["cancel-content"].disabled = true;
const severities = ["error", "warning", "information"].map(value => {
  const element = new Element();
  element.dataset.severity = value;
  return element;
});
const validSamples = {
  "breast-synoptic-summary": "tests/fixtures/valid/breast-synoptic-summary.hl7",
  "cap-ecp": "tests/fixtures/valid/cap-ecp.hl7",
  "structured-narrative": "tests/fixtures/valid/structured-narrative.hl7",
  "synoptic-segmented": "tests/fixtures/valid/synoptic-segmented.hl7",
  "synoptic-summary": "tests/fixtures/valid/synoptic-summary.hl7",
  "unstructured-narrative": "tests/fixtures/valid/unstructured-narrative.hl7"
};
const invalidSamples = {
  "invalid-ecp-link": { path: "tests/fixtures/negative/invalid-ecp-link.hl7", ruleId: "ECP-003" },
  "invalid-message-type": { path: "tests/fixtures/negative/invalid-message-type.hl7", ruleId: "LRI-15" },
  "invalid-missing-specimen": { path: "tests/fixtures/negative/invalid-missing-specimen.hl7", ruleId: "STRUCTURE-001" }
};
const document = {
  documentElement: new Element("html"),
  getElementById(id) { return elements[id]; },
  createElement(tagName) {
    const element = new Element();
    element.tagName = String(tagName || "").toUpperCase();
    return element;
  },
  querySelectorAll(selector) {
    if (selector === "[data-severity]:checked") return severities.filter(element => element.checked);
    if (selector === "[data-severity]") return severities;
    return [];
  }
};

let timerId = 0;
const longTimers = new Map();
const context = {
  console,
  document,
  Blob,
  Response,
  AbortController,
  URL: { createObjectURL() { return "blob:test"; }, revokeObjectURL() {} }
};
context.window = context;
context.globalThis = context;
context.setTimeout = (callback, delay) => {
  timerId += 1;
  if (Number(delay) >= 60000) longTimers.set(timerId, callback);
  else Promise.resolve().then(callback);
  return timerId;
};
context.clearTimeout = id => longTimers.delete(id);
context.print = () => {};
context.FileReader = class {};
vm.createContext(context);

function sorted(value) {
  if (Array.isArray(value)) return value.map(sorted);
  if (value && typeof value === "object") {
    const result = {};
    Object.keys(value).sort().forEach(key => { result[key] = sorted(value[key]); });
    return result;
  }
  return value;
}

async function settle() {
  for (let index = 0; index < 10; index += 1) await Promise.resolve();
}

function descendantText(element) {
  return [element.textContent, ...element.children.map(descendantText)].join(" ");
}

async function main() {
  const html = fs.readFileSync("dist/naaccr-lri-validator.html", "utf8");
  const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(match => match[1]);
  assert.equal(scripts.length, 4, "expected diagnostic, catalog, engines, and application scripts");
  scripts.forEach(script => vm.runInContext(script, context));

  assert.equal("fetch" in context, false, "boot must not require or call a fetch global");
  assert.equal(document.documentElement["data-validator-ready"], "true");
  assert.equal(elements["startup-error"].hidden, true);
  assert.equal(context.__LRI_CATALOG__.schema_version, "1.0.0");
  assert.deepEqual(Object.keys(context.__LRI_SAMPLES__).sort(), [
    "breast-synoptic-summary", "cap-ecp", "invalid-ecp-link", "invalid-message-type", "invalid-missing-specimen",
    "structured-narrative", "synoptic-segmented", "synoptic-summary", "unstructured-narrative"
  ]);
  assert.deepEqual(
    JSON.parse(JSON.stringify(context.__LRI_CATALOG__)),
    JSON.parse(fs.readFileSync("src/lri_validator/catalog.json", "utf8"))
  );
  for (const [name, path] of Object.entries(validSamples)) {
    assert.equal(context.__LRI_SAMPLES__[name], fs.readFileSync(path, "utf8"));
  }
  for (const [name, example] of Object.entries(invalidSamples)) {
    assert.equal(context.__LRI_SAMPLES__[name], fs.readFileSync(example.path, "utf8"));
  }
  assert.deepEqual(elements.sample.children.map(option => option.value), [
    "breast-synoptic-summary", "cap-ecp", "structured-narrative", "synoptic-segmented", "synoptic-summary",
    "unstructured-narrative", "invalid-ecp-link", "invalid-message-type", "invalid-missing-specimen"
  ]);
  assert.deepEqual(elements.sample.children.slice(-3).map(option => option.textContent), [
    "Invalid: CAP eCP response link", "Invalid: wrong message type", "Invalid: missing specimen"
  ]);

  for (const name of Object.keys(validSamples)) {
    elements.message.value = context.__LRI_SAMPLES__[name];
    await elements.validate.click();
    assert.equal(elements.report.hidden, false, `${name} should display a report`);
    assert.match(elements["result-label"].textContent, /^PASS:/);
    assert.equal(elements["content-panel"].hidden, false, `${name} should expose the SEER check`);
    const disclosure = elements["content-disclosure"].children.map(item => item.textContent).join(" ");
    assert.match(disclosure, /Primary site \(ICD-O-3\): C\d{3}/);
    assert.match(disclosure, /Histology \(ICD-O-3\): \d{4}/);
  }

  for (const [name, example] of Object.entries(invalidSamples)) {
    elements.sample.value = name;
    await elements["load-sample"].click();
    assert.equal(elements.message.value, context.__LRI_SAMPLES__[name]);
    await elements.validate.click();
    assert.equal(elements.report.hidden, false, `${name} should display a report`);
    assert.match(elements["result-label"].textContent, /^FAIL:/);
    assert.equal(elements["content-panel"].hidden, true, `${name} should not expose the online check`);
    assert.ok(descendantText(elements.findings).includes(example.ruleId), `${name} should display ${example.ruleId}`);
  }

  elements.message.value = context.__LRI_SAMPLES__["breast-synoptic-summary"];
  await elements.validate.click();
  assert.equal(elements["content-panel"].hidden, false, "content panel appears after valid local validation");
  const disclosure = elements["content-disclosure"].children.map(item => item.textContent).join(" ");
  assert.match(disclosure, /Primary site \(ICD-O-3\): C504 \(message line 9\)/);
  assert.match(disclosure, /Histology \(ICD-O-3\): 8500 \(message line 9\)/);
  assert.match(disclosure, /Behavior \(ICD-O-3\): 3 \(message line 9\)/);
  assert.match(disclosure, /Diagnosis year: 2026 \(message line 10\)/);
  assert.doesNotMatch(disclosure, /Laterality/);
  assert.doesNotMatch(disclosure, /Grade/);
  assert.equal(elements["content-panel"]["data-content-state"], "idle");

  elements.message.value = fs.readFileSync("tests/fixtures/content/two-group-mph.hl7", "utf8");
  await elements.validate.click();
  const pairDisclosure = elements["content-disclosure"].children.map(item => item.textContent).join(" ");
  assert.match(pairDisclosure, /Order group 1, Laterality \(NAACCR\): 2/);
  assert.match(pairDisclosure, /Order group 2, Laterality \(NAACCR\): 1/);
  assert.doesNotMatch(pairDisclosure, /Grade/);

  elements.message.value = context.__LRI_SAMPLES__["breast-synoptic-summary"];
  await elements.validate.click();

  await elements["run-content"].click();
  assert.equal(elements["content-panel"]["data-content-state"], "error");
  assert.match(elements["content-error"].textContent, /Enter a SEER API key/);

  const index = JSON.parse(fs.readFileSync("tests/fixtures/seer/index.json", "utf8"));
  const requests = [];
  context.fetch = async (url, options) => {
    assert.match(url, /^https:\/\/api[.]seer[.]cancer[.]gov\/rest\//);
    assert.equal(options.headers["X-SEERAPI-Key"], "browser-test-key");
    const body = options.body ? JSON.parse(options.body) : null;
    const method = options.method || "GET";
    const key = JSON.stringify(sorted({ method, url, body }));
    assert.ok(index[key], `missing fixture for ${key}`);
    requests.push({ method, url, body });
    return {
      status: Number(index[key].status),
      async text() { return fs.readFileSync(`tests/fixtures/seer/${index[key].file}`, "utf8"); }
    };
  };
  elements["seer-key"].value = "browser-test-key";
  await elements["run-content"].click();
  assert.equal(elements["content-panel"]["data-content-state"], "done");
  assert.equal(elements["content-report"].hidden, false);
  assert.match(elements["content-result-label"].textContent, /^PASS:/);
  assert.ok(requests.length > 0);
  assert.ok(requests.every(request => !JSON.stringify(request).includes("PATBREAST1")));
  assert.equal(elements["content-queries"].children.length, requests.length);
  const queryDetails = elements["content-queries"].children.map(item => item.children[0]);
  const querySummaries = queryDetails.map(details => details.children[0].textContent).join(" ");
  assert.ok(queryDetails.every(details => details.tagName === "DETAILS"));
  assert.ok(queryDetails.every(details => details.children[0].tagName === "SUMMARY"));
  assert.match(querySummaries, /Find a staging schema for site C504 and histology 8500\/3 using EOD 3\.3 \(Completed\)/);
  assert.match(querySummaries, /Find the site-recode group for site C504 and histology 8500\/3 \(Completed\)/);
  assert.match(querySummaries, /Check Laterality using NAACCR item 410 \(version 26\) \(Completed\)/);
  assert.match(queryDetails[0].children[1].textContent, /^POST https:\/\/api[.]seer[.]cancer[.]gov\/rest\/.*body=.*\(HTTP 200\)$/);

  for (const failure of [
    { status: 401, label: /Authentication failed/ },
    { status: 403, label: /Blocked or rate-limited/ },
    { status: 429, label: /Blocked or rate-limited/ }
  ]) {
    context.LriContent.sessionCache.clear();
    await elements.validate.click();
    context.fetch = async () => ({ status: failure.status, async text() { return ""; } });
    await elements["run-content"].click();
    assert.equal(elements["content-panel"]["data-content-state"], "done", "HTTP failures resolve to reports");
    assert.match(elements["content-result-label"].textContent, /^INCOMPLETE:/);
    assert.equal(elements["content-error"].hidden, true);
    const failureSummary = elements["content-queries"].children[0].children[0].children[0].textContent;
    assert.match(failureSummary, failure.label, `empty HTTP ${failure.status} body keeps status classification`);
    assert.doesNotMatch(failureSummary, /Network request failed/);
  }

  context.LriContent.sessionCache.clear();
  await elements.validate.click();
  context.fetch = async () => { throw new Error("offline"); };
  await elements["run-content"].click();
  assert.equal(elements["content-panel"]["data-content-state"], "done", "network failures resolve to reports");
  assert.match(elements["content-result-label"].textContent, /^INCOMPLETE:/);

  context.LriContent.sessionCache.clear();
  await elements.validate.click();
  context.fetch = (_url, options) => new Promise((_resolve, reject) => {
    options.signal.addEventListener("abort", () => reject(Object.assign(new Error("aborted"), { name: "AbortError" })));
  });
  const cancelledRun = elements["run-content"].click();
  await settle();
  assert.equal(elements["content-panel"]["data-content-state"], "busy");
  await elements["cancel-content"].click();
  await cancelledRun;
  assert.equal(elements["content-panel"]["data-content-state"], "error");
  assert.match(elements["content-error"].textContent, /cancelled/);

  context.LriContent.sessionCache.clear();
  await elements.validate.click();
  context.fetch = (_url, options) => new Promise((_resolve, reject) => {
    options.signal.addEventListener("abort", () => reject(new Error("stale")));
  });
  const staleRun = elements["run-content"].click();
  await settle();
  await elements.message.dispatch("input", { target: elements.message });
  await staleRun;
  assert.equal(elements["content-panel"].hidden, true, "message edits clear stale content state");

  elements["seer-key"].value = "keep-in-memory";
  elements.file.value = "selected.hl7";
  await elements.clear.click();
  assert.equal(elements.message.value, "", "Clear should empty pasted or uploaded text");
  assert.equal(elements.file.value, "", "Clear should reset the file control");
  assert.equal(elements.report.hidden, true, "Clear should reset the report");
  assert.equal(elements["seer-key"].value, "keep-in-memory", "Clear should retain the in-memory key");
}

main().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
