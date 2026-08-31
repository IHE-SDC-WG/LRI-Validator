"use strict";

const fs = require("node:fs");

global.__LRI_CATALOG__ = JSON.parse(fs.readFileSync("src/lri_validator/catalog.json", "utf8"));
global.LriValidator = require("../web/validator.js");
const content = require("../web/content.js");
const request = JSON.parse(fs.readFileSync(0, "utf8"));
const index = JSON.parse(fs.readFileSync("tests/fixtures/seer/index.json", "utf8"));

function sorted(value) {
  if (Array.isArray(value)) return value.map(sorted);
  if (value && typeof value === "object") {
    const result = {};
    Object.keys(value).sort().forEach(key => { result[key] = sorted(value[key]); });
    return result;
  }
  return value;
}

async function transport(method, url, body) {
  const key = JSON.stringify(sorted({ method, url, body }));
  if (!index[key]) throw new Error(`Missing recorded SEER fixture for ${key}`);
  return {
    status: Number(index[key].status),
    data: JSON.parse(fs.readFileSync(`tests/fixtures/seer/${index[key].file}`, "utf8"))
  };
}

(async function () {
  try {
    const report = await content.validateContent(request.text, { transport, syntaxValid: true, cache: new Map() });
    process.stdout.write(JSON.stringify({ ok: true, report }));
  } catch (error) {
    process.stdout.write(JSON.stringify({ ok: false, error: error.message || String(error), stack: error.stack || "" }));
  }
}());
