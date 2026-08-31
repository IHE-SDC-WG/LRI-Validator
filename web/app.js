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
  var currentContentReport = null;
  var contentController = null;
  var contentGeneration = 0;
  var contentCancelled = false;
  var samples = window.__LRI_SAMPLES__ || {};
  var sampleLabels = {
    "unstructured-narrative": "Unstructured narrative",
    "structured-narrative": "Structured narrative",
    "synoptic-summary": "Synoptic summary",
    "synoptic-segmented": "Synoptic segmented",
    "cap-ecp": "CAP eCP",
    "breast-synoptic-summary": "Breast synoptic summary"
  };

  function failInput(text) { inputError.textContent = text; inputError.hidden = false; }
  function clearInputError() { inputError.textContent = ""; inputError.hidden = true; }
  function setContentState(state) { byId("content-panel").setAttribute("data-content-state", state); }
  function clearContentError() { byId("content-error").textContent = ""; byId("content-error").hidden = true; }

  function resetContent(hidePanel) {
    contentGeneration += 1;
    if (contentController) contentController.abort();
    contentController = null;
    contentCancelled = false;
    currentContentReport = null;
    byId("content-report").hidden = true;
    byId("content-status").textContent = "";
    byId("run-content").disabled = false;
    byId("cancel-content").disabled = true;
    clearContentError();
    setContentState("idle");
    if (hidePanel) byId("content-panel").hidden = true;
  }

  function resetReport() {
    resetContent(true);
    message.value = "";
    fileInput.value = "";
    sample.value = "";
    clearInputError();
    currentReport = null;
    byId("report").hidden = true;
    byId("no-report").hidden = false;
  }

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

  function enabledSeverities() {
    var enabled = {};
    Array.prototype.forEach.call(document.querySelectorAll("[data-severity]:checked"), function (input) {
      enabled[input.dataset.severity] = true;
    });
    return enabled;
  }

  function renderFindingList(list, findings) {
    var enabled = enabledSeverities();
    empty(list);
    var visible = findings.filter(function (finding) { return enabled[finding.severity]; });
    if (!visible.length) {
      var none = document.createElement("li");
      none.className = "empty";
      none.textContent = findings.length ? "No findings match the active severity filters." : "No findings.";
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

  function renderFindings() {
    if (currentReport) renderFindingList(byId("findings"), currentReport.findings);
    if (currentContentReport) renderFindingList(byId("content-findings"), currentContentReport.findings);
  }

  function renderDisclosure(extraction) {
    var list = byId("content-disclosure");
    empty(list);
    var fields = [
      ["site", "Primary site (ICD-O-3)"],
      ["histology", "Histology (ICD-O-3)"],
      ["behavior", "Behavior (ICD-O-3)"],
      ["laterality", "Laterality (NAACCR)"],
      ["grade", "Grade (NAACCR)"],
      ["year", "Diagnosis year"]
    ];
    extraction.groups.forEach(function (group) {
      fields.forEach(function (definition) {
        var field = group[definition[0]];
        if (!field) return;
        var item = document.createElement("li");
        var line = field.line_number == null ? "" : " (message line " + field.line_number + ")";
        item.textContent = "Order group " + group.group + ", " + definition[1] + ": " + field.value + line;
        list.appendChild(item);
      });
    });
  }

  function humanizeToken(value) {
    return String(value || "").replace(/[_-]+/g, " ").replace(/\b[a-z]/g, function (letter) { return letter.toUpperCase(); });
  }

  function algorithmLabel(value) {
    if (value === "eod_public") return "EOD";
    if (value === "tnm") return "TNM";
    if (value === "cs") return "CS";
    return humanizeToken(value);
  }

  function queryParameters(url) {
    var result = {};
    var query = String(url || "").split("?", 2)[1];
    if (!query) return result;
    query.split("&").forEach(function (part) {
      var pieces = part.split("=");
      var key = decodeURIComponent((pieces.shift() || "").replace(/\+/g, " "));
      var value = decodeURIComponent(pieces.join("=").replace(/\+/g, " "));
      if (key) result[key] = value;
    });
    return result;
  }

  function morphologyLabel(histology, behavior) {
    return histology ? String(histology) + (behavior == null || behavior === "" ? "" : "/" + behavior) : "the extracted histology";
  }

  function queryState(query) {
    if (query.cached) return "Used cached response";
    if (Number(query.status) >= 200 && Number(query.status) < 300) return "Completed";
    if (Number(query.status) === 401) return "Authentication failed";
    if (Number(query.status) === 403 || Number(query.status) === 429) return "Blocked or rate-limited";
    if (query.status === "network") return "Network request failed";
    if (query.status === "budget") return "Local request limit reached";
    return "Returned HTTP " + query.status;
  }

  function queryDescription(query) {
    var base = "https://api.seer.cancer.gov/rest/";
    var relative = String(query.url || "").indexOf(base) === 0 ? String(query.url).slice(base.length) : String(query.url || "");
    var parts = relative.split("?", 1)[0].split("/");
    var parameters = queryParameters(query.url);
    var body = query.body || {};
    var description;
    if (parts[0] === "staging" && parts[3] === "schemas" && parts[4] === "lookup") {
      description = "Find a staging schema for site " + body.site + " and histology " + morphologyLabel(body.hist, body.behavior) + " using " + algorithmLabel(parts[1]) + " " + parts[2];
    } else if (parts[0] === "staging" && parts[3] === "schema") {
      description = "Load the " + humanizeToken(parts[4]) + " staging schema using " + algorithmLabel(parts[1]) + " " + parts[2];
    } else if (parts[0] === "staging" && parts[3] === "table") {
      description = "Load the " + humanizeToken(parts[4]) + " value table using " + algorithmLabel(parts[1]) + " " + parts[2];
    } else if (parts[0] === "recode" && parts[1] === "sitegroup") {
      description = "Find the site-recode group for site " + parameters.site + " and histology " + morphologyLabel(parameters.hist, parameters.behavior);
    } else if (parts[0] === "naaccr") {
      var items = ((window.__LRI_CATALOG__ || {}).content || {}).naaccr_items || {};
      var fieldName = Object.keys(items).find(function (key) { return String(items[key]) === String(parts[2]); });
      description = "Check " + (fieldName ? humanizeToken(fieldName) : "a coded value") + " using NAACCR item " + parts[2] + " (version " + parts[1] + ")";
    } else if (parts[0] === "disease" && parts[2] === "same_primary") {
      description = "Compare " + parameters.d1 + " and " + parameters.d2 + " using the hematopoietic same-primary rules";
    } else if (parts[0] === "disease" && parts[2] === "id") {
      description = "Load hematopoietic disease record " + parts[3];
    } else if (parts[0] === "disease") {
      description = "Search the hematopoietic disease data for " + (parameters.q || "the extracted morphology");
    } else if (parts[0] === "mph") {
      description = "Compare two tumors using the SEER multiple-primary rules";
    } else {
      description = "Send a SEER API request";
    }
    return description + " (" + queryState(query) + ")";
  }

  function rawQuery(query) {
    return query.method + " " + query.url + (query.body ? " body=" + JSON.stringify(query.body) : "") + (query.cached ? " (session cache)" : " (HTTP " + query.status + ")");
  }

  function prepareContentPanel() {
    resetContent(true);
    if (!currentReport || !currentReport.valid || !window.LriContent || typeof window.LriContent.extractContent !== "function") return;
    try {
      var extraction = window.LriContent.extractContent(message.value);
      if (!extraction.groups.some(function (group) { return group.site || group.histology; })) return;
      renderDisclosure(extraction);
      byId("content-panel").hidden = false;
    } catch (_error) {
      byId("content-panel").hidden = true;
    }
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
    prepareContentPanel();
  }

  function renderContent(report) {
    currentContentReport = report;
    byId("content-report").hidden = false;
    var result = byId("content-result");
    var label;
    if (report.status === "partial") {
      result.className = "status partial";
      label = "INCOMPLETE: some online checks were skipped";
    } else if (report.status === "not-applicable") {
      result.className = "status partial";
      label = "NOT APPLICABLE: no registry codes extracted";
    } else if (report.valid) {
      result.className = "status pass";
      label = "PASS: no registry-content errors";
    } else {
      result.className = "status fail";
      label = "FAIL: registry-content errors found";
    }
    byId("content-result-label").textContent = label;
    byId("content-ruleset-label").textContent = report.content_ruleset_version;
    var counts = byId("content-counts");
    empty(counts);
    [["error", "Errors"], ["warning", "Warnings"], ["information", "Information"]].forEach(function (entry) {
      var count = document.createElement("span");
      count.className = "count " + entry[0];
      count.textContent = entry[1] + ": " + report.counts[entry[0]];
      counts.appendChild(count);
    });
    renderFindingList(byId("content-findings"), report.findings);
    var queries = byId("content-queries");
    empty(queries);
    report.queries.forEach(function (query) {
      var item = document.createElement("li");
      item.className = "query-item";
      var details = document.createElement("details");
      var summary = document.createElement("summary");
      var raw = document.createElement("pre");
      summary.textContent = queryDescription(query);
      raw.className = "query-raw";
      raw.textContent = rawQuery(query);
      details.appendChild(summary);
      details.appendChild(raw);
      item.appendChild(details);
      queries.appendChild(item);
    });
    var coverage = byId("content-coverage");
    empty(coverage);
    report.coverage_notices.forEach(function (text) {
      var item = document.createElement("li");
      item.textContent = text;
      coverage.appendChild(item);
    });
    byId("content-attribution").textContent = report.attribution;
    byId("content-status").textContent = report.status === "partial" ? "Finished with skipped online checks." : "Registry content check finished.";
  }

  function makeTransport(key, signal) {
    return async function (method, url, body) {
      if (!/^https:\/\/api[.]seer[.]cancer[.]gov\/rest\//.test(url)) throw new window.LriContent.SeerError("blocked", "Blocked non-SEER request URL.");
      var options = {
        method: method,
        headers: { "Accept": "application/json", "X-SEERAPI-Key": key },
        credentials: "omit",
        cache: "no-store",
        signal: signal
      };
      if (body) {
        options.headers["Content-Type"] = "application/json";
        options.body = JSON.stringify(body);
      }
      try {
        var response = await fetch(url, options);
        var data = await response.json();
        return { status: response.status, data: data };
      } catch (error) {
        if (signal.aborted) throw new window.LriContent.SeerError("aborted", "The registry content check was cancelled.");
        throw error;
      }
    };
  }

  async function runContentCheck() {
    clearContentError();
    var key = byId("seer-key").value.trim();
    if (!key) {
      byId("content-error").textContent = "Enter a SEER API key before running the optional online check.";
      byId("content-error").hidden = false;
      byId("content-status").textContent = "Registry content check did not start.";
      setContentState("error");
      return;
    }
    if (!window.LriContent || typeof window.LriContent.validateContent !== "function") {
      byId("content-error").textContent = "The registry content engine is not available.";
      byId("content-error").hidden = false;
      setContentState("error");
      return;
    }
    contentGeneration += 1;
    var generation = contentGeneration;
    var controller = new AbortController();
    var timedOut = false;
    contentCancelled = false;
    contentController = controller;
    currentContentReport = null;
    byId("content-report").hidden = true;
    byId("run-content").disabled = true;
    byId("cancel-content").disabled = false;
    byId("content-status").textContent = "Checking registry content with SEER…";
    setContentState("busy");
    var watchdog = window.setTimeout(function () { timedOut = true; controller.abort(); }, 60000);
    try {
      var report = await window.LriContent.validateContent(message.value, {
        transport: makeTransport(key, controller.signal),
        syntaxValid: currentReport && currentReport.valid
      });
      if (generation !== contentGeneration) return;
      renderContent(report);
      setContentState("done");
    } catch (error) {
      if (generation !== contentGeneration) return;
      var text = timedOut ? "The registry content check timed out after 60 seconds." : contentCancelled ? "The registry content check was cancelled." : (error && error.message ? error.message : String(error));
      byId("content-error").textContent = text;
      byId("content-error").hidden = false;
      byId("content-status").textContent = "Registry content check stopped.";
      setContentState("error");
    } finally {
      window.clearTimeout(watchdog);
      if (generation === contentGeneration) {
        contentController = null;
        byId("run-content").disabled = false;
        byId("cancel-content").disabled = true;
      }
    }
  }

  Object.keys(samples).sort().forEach(function (key) {
    var option = document.createElement("option");
    option.value = key;
    option.textContent = sampleLabels[key] || key;
    sample.appendChild(option);
  });

  byId("validate").addEventListener("click", function () {
    resetContent(true);
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
      resetContent(true);
      message.value = samples[sample.value];
      clearInputError();
      message.focus();
    }
  });
  fileInput.addEventListener("change", function (event) {
    resetContent(true);
    clearInputError();
    var file = event.target.files && event.target.files[0];
    if (!file) return;
    if (!/\.(hl7|er7|txt)$/i.test(file.name)) {
      failInput("Choose a .hl7, .er7, or .txt file.");
      event.target.value = "";
      return;
    }
    var reader = new FileReader();
    reader.onload = function () { resetContent(true); message.value = String(reader.result || ""); };
    reader.onerror = function () { failInput("The selected file could not be read as text."); };
    reader.readAsText(file);
  });
  message.addEventListener("input", function () { resetContent(true); });
  Array.prototype.forEach.call(document.querySelectorAll("[data-severity]"), function (input) {
    input.addEventListener("change", function () { renderFindings(); });
  });
  byId("run-content").addEventListener("click", runContentCheck);
  byId("cancel-content").addEventListener("click", function () {
    if (contentController) { contentCancelled = true; contentController.abort(); }
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
  byId("content-download").addEventListener("click", function () {
    if (!currentContentReport) return;
    var blob = new Blob([JSON.stringify(currentContentReport, null, 2) + "\n"], { type: "application/json" });
    var link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = "naaccr-lri-content-report.json";
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
