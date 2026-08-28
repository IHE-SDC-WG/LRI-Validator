const fs = require("fs");
global.__LRI_CATALOG__ = JSON.parse(fs.readFileSync("src/lri_validator/catalog.json", "utf8"));
const validator = require("../web/validator.js");
const request = JSON.parse(fs.readFileSync(0, "utf8"));
try {
  process.stdout.write(JSON.stringify({ ok: true, report: validator.validateMessage(request.text) }));
} catch (error) {
  process.stdout.write(JSON.stringify({ ok: false, error: error.message || String(error) }));
}
