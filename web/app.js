(function () {
  "use strict";

  function byId(id) { return document.getElementById(id); }
  function empty(element) { while (element.firstChild) element.removeChild(element.firstChild); }

  var message = byId("message");
  var fileInput = byId("file");
  var inputError = byId("input-error");
  var startupError = byId("startup-error");
  var sample = byId("sample");
  var currentReport = null;
  var samples = window.__LRI_SAMPLES__ || {};
  var sampleLabels = {
    "unstructured-narrative": "Unstructured narrative",
    "structured-narrative": "Structured narrative",
    "synoptic-summary": "Synoptic summary",
    "synoptic-segmented": "Synoptic segmented",
    "cap-ecp": "CAP eCP"
  };

  function failInput(text) { inputError.textContent = text; inputError.hidden = false; }
  function clearInputError() { inputError.textContent = ""; inputError.hidden = true; }
  function resetReport() {
    message.value = "";
    fileInput.value = "";
    sample.value = "";
    clearInputError();
    currentReport = null;
    byId("report").hidden = true;
    byId("no-report").hidden = false;
  }

  // Register Clear before checking the validator so it remains usable if startup fails.
  byId("clear").addEventListener("click", function () {
    resetReport();
    message.focus();
  });

  function focusLine(line) {
    if (!line) return;
    var lines = message.value.split(/\r\n|\r|\n/);
    var start = 0;
    var index;
    for (index = 0; index < line - 1 && index < lines.length; index += 1) start += lines[index].length + 1;
    var end = start + (lines[line - 1] || "").length;
    message.focus();
    message.setSelectionRange(start, end);
    message.scrollTop = Math.max(0, (line - 3) * 19);
  }

  function renderFindings() {
    var enabled = {};
    Array.prototype.forEach.call(document.querySelectorAll("[data-severity]:checked"), function (input) {
      enabled[input.dataset.severity] = true;
    });
    var list = byId("findings");
    empty(list);
    var visible = currentReport.findings.filter(function (finding) { return enabled[finding.severity]; });
    if (!visible.length) {
      var none = document.createElement("li");
      none.className = "empty";
      none.textContent = currentReport.findings.length ? "No findings match the active severity filters." : "No findings.";
      list.appendChild(none);
      return;
    }
    visible.forEach(function (finding) {
      var item = document.createElement("li");
      var button = document.createElement("button");
      var head = document.createElement("div");
      var severity = document.createElement("span");
      var rule = document.createElement("span");
      var detail = document.createElement("p");
      var expected = document.createElement("small");
      item.className = "finding";
      button.type = "button";
      head.className = "finding-head";
      severity.className = "severity " + finding.severity;
      severity.textContent = finding.severity;
      rule.className = "rule";
      rule.textContent = finding.rule_id + " · " + finding.location + (finding.line_number ? " · line " + finding.line_number : "");
      detail.textContent = finding.message;
      expected.textContent = "Expected: " + finding.expected_behavior + " Source: " + finding.source_section;
      head.appendChild(severity);
      head.appendChild(rule);
      button.appendChild(head);
      button.appendChild(detail);
      button.appendChild(expected);
      button.addEventListener("click", function () { focusLine(finding.line_number); });
      item.appendChild(button);
      list.appendChild(item);
    });
  }

  function render() {
    byId("no-report").hidden = true;
    byId("report").hidden = false;
    var status = byId("status");
    status.className = "status " + (currentReport.valid ? "pass" : "fail");
    byId("result-label").textContent = currentReport.valid ? "PASS: no validation errors" : "FAIL: validation errors found";
    byId("style-label").textContent = "Detected style: " + currentReport.detected_report_style;
    byId("ruleset-label").textContent = currentReport.ruleset_version;
    var counts = byId("counts");
    empty(counts);
    [["error", "Errors"], ["warning", "Warnings"], ["information", "Information"]].forEach(function (entry) {
      var count = document.createElement("span");
      count.className = "count " + entry[0];
      count.textContent = entry[1] + ": " + currentReport.counts[entry[0]];
      counts.appendChild(count);
    });
    renderFindings();
    var coverage = byId("coverage");
    empty(coverage);
    currentReport.coverage_notices.forEach(function (text) {
      var item = document.createElement("li");
      item.textContent = text;
      coverage.appendChild(item);
    });
  }

  Object.keys(samples).sort().forEach(function (key) {
    var option = document.createElement("option");
    option.value = key;
    option.textContent = sampleLabels[key] || key;
    sample.appendChild(option);
  });

  byId("validate").addEventListener("click", function () {
    clearInputError();
    if (!window.LriValidator || typeof window.LriValidator.validateMessage !== "function") {
      startupError.textContent = "The validator could not start in this browser. Open the HTML file in a current version of Safari, Chrome, Firefox, or Edge.";
      startupError.hidden = false;
      return;
    }
    try {
      currentReport = window.LriValidator.validateMessage(message.value);
      render();
    } catch (error) {
      failInput(error && error.message ? error.message : String(error));
    }
  });
  byId("load-sample").addEventListener("click", function () {
    if (sample.value && samples[sample.value]) {
      message.value = samples[sample.value];
      clearInputError();
      message.focus();
    }
  });
  fileInput.addEventListener("change", function (event) {
    clearInputError();
    var file = event.target.files && event.target.files[0];
    if (!file) return;
    if (!/\.(hl7|er7|txt)$/i.test(file.name)) {
      failInput("Choose a .hl7, .er7, or .txt file.");
      event.target.value = "";
      return;
    }
    var reader = new FileReader();
    reader.onload = function () { message.value = String(reader.result || ""); };
    reader.onerror = function () { failInput("The selected file could not be read as text."); };
    reader.readAsText(file);
  });
  Array.prototype.forEach.call(document.querySelectorAll("[data-severity]"), function (input) {
    input.addEventListener("change", function () { if (currentReport) renderFindings(); });
  });
  byId("download").addEventListener("click", function () {
    if (!currentReport) return;
    var blob = new Blob([JSON.stringify(currentReport, null, 2) + "\n"], { type: "application/json" });
    var link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = "naaccr-lri-validation-report.json";
    link.click();
    window.setTimeout(function () { URL.revokeObjectURL(link.href); }, 0);
  });
  byId("print").addEventListener("click", function () { window.print(); });

  if (window.LriValidator && typeof window.LriValidator.validateMessage === "function") {
    startupError.hidden = true;
    document.documentElement.setAttribute("data-validator-ready", "true");
  } else {
    startupError.textContent = "Startup error: the embedded validator engine was not available.";
    startupError.hidden = false;
    document.documentElement.setAttribute("data-validator-ready", "false");
  }
}());
