(function (root, factory) {
  const validator = root.LriValidator || (typeof module === "object" && module.exports ? require("./validator.js") : null);
  const api = factory(root.__LRI_CATALOG__ || {}, validator);
  if (typeof module === "object" && module.exports) module.exports = api;
  root.LriContent = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function (CATALOG, validator) {
  "use strict";

  const CONTENT = CATALOG.content || {};
  const RULES = CATALOG.rules || {};
  const ECP_TEMPLATE = /^\d{1,9}\.\d{9}$/;
  const SITE = /(^|[^A-Z0-9])C(\d{2})(?:[.]?(\d))?(?![A-Z0-9])/gi;
  const MORPHOLOGY = /(^|[^\d])(\d{4})(?:\s*\/\s*([0-9]))?(?!\d)/g;
  const TOKEN = /^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$/;
  const SITE_CODE = /^C\d{3}$/;
  const HIST_CODE = /^\d{4}$/;
  const BEHAVIOR_CODE = /^[0-9]$/;
  const YEAR_CODE = /^(?:19|20)\d{2}$/;
  const MORPHOLOGY_CODE = /^\d{4}\/[0-9]$/;
  const sessionCache = new Map();

  class SeerError extends Error {
    constructor(kind, message, status) { super(message); this.kind = kind; this.status = status == null ? null : status; }
  }

  function decodeHl7(value) {
    [["\\.br\\", "\n"], ["\\F\\", "|"], ["\\S\\", "^"], ["\\T\\", "&"], ["\\R\\", "~"], ["\\E\\", "\\"]]
      .forEach(entry => { value = String(value || "").split(entry[0]).join(entry[1]); });
    return value;
  }

  function siteMatches(value) {
    const matches = [];
    String(value || "").toUpperCase().replace(SITE, function (_whole, _prefix, first, third) {
      matches.push({ value: "C" + first + (third || "9"), assumed_nos: !third });
      return _whole;
    });
    const specific = matches.filter(match => !match.assumed_nos);
    const selected = specific.length ? specific : matches;
    const values = [...new Set(selected.map(match => match.value + "|" + match.assumed_nos))];
    if (values.length !== 1) return null;
    return selected[0];
  }

  function morphologyMatches(value) {
    const matches = [];
    String(value || "").replace(MORPHOLOGY, function (_whole, _prefix, histology, behavior) {
      matches.push({ histology, behavior: behavior || null });
      return _whole;
    });
    const values = [...new Set(matches.map(match => match.histology + "|" + (match.behavior || "")))];
    return values.length === 1 ? matches[0] : null;
  }

  function normalizeBehavior(value) {
    const morphology = morphologyMatches(value);
    if (morphology && morphology.behavior != null) return morphology.behavior;
    const match = String(value || "").match(/(?:behavior|behaviour)\s*(?:code)?\s*[:=-]?\s*([0-9])\b/i);
    if (match) return match[1];
    const stripped = String(value || "").trim();
    return /^[0-9]$/.test(stripped) ? stripped : null;
  }

  function normalizeLaterality(value) {
    const stripped = String(value || "").trim();
    if (/^[0-9]$/.test(stripped)) return stripped;
    const lowered = stripped.toLowerCase().replace(/\s+/g, " ");
    for (const word of Object.keys(CONTENT.laterality_words || {})) {
      if (new RegExp("\\b" + escapeRegex(word) + "\\b", "i").test(lowered)) return CONTENT.laterality_words[word];
    }
    return null;
  }

  function normalizeGrade(value) {
    const stripped = String(value || "").trim();
    if (/^[1-9A-DHLM]$/i.test(stripped)) return stripped.toUpperCase();
    const match = stripped.match(/\b(?:grade\s*)?(?:G\s*)?([1-4])\b/i);
    return match ? match[1] : null;
  }

  function escapeRegex(value) { return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"); }

  function labelField(label) {
    const normalized = String(label || "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
    for (const fieldName of Object.keys(CONTENT.labels || {})) {
      if (CONTENT.labels[fieldName].some(candidate => normalized === candidate || normalized.endsWith(" " + candidate))) return fieldName;
    }
    return null;
  }

  function append(candidates, fieldName, value, line, priority) {
    if (value != null) candidates[fieldName].push({ value, line, priority, assumed_nos: false });
  }

  function appendSite(candidates, match, line, priority) {
    if (match) candidates.site.push({ value: match.value, line, priority, assumed_nos: match.assumed_nos });
  }

  function codedCandidates(observation, candidates) {
    const label = decodeHl7(validator.component(validator.field(observation, 3), 2));
    const fieldName = labelField(label);
    const value = decodeHl7(validator.field(observation, 5));
    const triplets = [
      [validator.component(value, 1), validator.component(value, 2), validator.component(value, 3)],
      [validator.component(value, 4), validator.component(value, 5), validator.component(value, 6)]
    ];
    const aliases = new Set((CONTENT.icdo_system_aliases || []).map(alias => alias.toUpperCase()));
    triplets.forEach(triplet => {
      const identifier = triplet[0], display = triplet[1], system = triplet[2];
      if (!identifier && !display) return;
      const combined = [identifier, display].filter(Boolean).join(" ");
      if (fieldName === "site") appendSite(candidates, siteMatches(combined), observation.line, 1);
      else if (fieldName === "histology") {
        const morphology = morphologyMatches(combined);
        if (morphology) { append(candidates, "histology", morphology.histology, observation.line, 1); append(candidates, "behavior", morphology.behavior, observation.line, 1); }
      } else if (fieldName === "behavior") append(candidates, "behavior", normalizeBehavior(combined), observation.line, 1);
      else if (fieldName === "laterality") append(candidates, "laterality", (CONTENT.laterality_snomed || {})[identifier] || normalizeLaterality(combined), observation.line, 1);
      else if (fieldName === "grade") append(candidates, "grade", normalizeGrade(combined), observation.line, 1);
      if (aliases.has(String(system || "").toUpperCase())) {
        appendSite(candidates, siteMatches(identifier), observation.line, 1);
        const morphology = morphologyMatches(identifier);
        if (morphology) { append(candidates, "histology", morphology.histology, observation.line, 1); append(candidates, "behavior", morphology.behavior, observation.line, 1); }
      }
    });
  }

  function specimenSiteCandidates(specimen, candidates) {
    const aliases = new Set((CONTENT.icdo_system_aliases || []).map(alias => alias.toUpperCase()));
    [4, 8].forEach(fieldNumber => {
      const fieldValue = validator.field(specimen, fieldNumber);
      if (!fieldValue) return;
      fieldValue.split("~").forEach(repetition => {
        const triplets = [
          [validator.component(repetition, 1), validator.component(repetition, 2), validator.component(repetition, 3)],
          [validator.component(repetition, 4), validator.component(repetition, 5), validator.component(repetition, 6)]
        ];
        triplets.forEach(triplet => {
          const identifier = triplet[0], display = decodeHl7(triplet[1]), system = triplet[2];
          if (!identifier && !display) return;
          if (fieldNumber === 8 || aliases.has(String(system || "").toUpperCase())) {
            appendSite(candidates, siteMatches([identifier, display].filter(Boolean).join(" ")), specimen.line, 3);
          }
        });
      });
    });
  }

  function labeledCandidates(text, line, candidates) {
    const decoded = decodeHl7(text);
    Object.keys(CONTENT.labels || {}).forEach(fieldName => {
      const pattern = CONTENT.labels[fieldName].map(escapeRegex).join("|");
      const expression = new RegExp("(?:^|[\\n;])\\s*(?:" + pattern + ")\\s*[:=-]\\s*([^\\n;]+)", "gi");
      let match;
      while ((match = expression.exec(decoded)) !== null) {
        const value = match[1];
        if (fieldName === "site") appendSite(candidates, siteMatches(value), line, 2);
        else if (fieldName === "histology") {
          const morphology = morphologyMatches(value);
          if (morphology) { append(candidates, "histology", morphology.histology, line, 2); append(candidates, "behavior", morphology.behavior, line, 2); }
        } else if (fieldName === "behavior") append(candidates, "behavior", normalizeBehavior(value), line, 2);
        else if (fieldName === "laterality") append(candidates, "laterality", normalizeLaterality(value), line, 2);
        else if (fieldName === "grade") append(candidates, "grade", normalizeGrade(value), line, 2);
      }
    });
    const matches = [];
    decoded.replace(MORPHOLOGY, function (_whole, _prefix, histology, behavior) { matches.push([histology, behavior || ""]); return _whole; });
    if (matches.length === 1 && Number(matches[0][0]) >= Number(CONTENT.heme_histology_min)) {
      append(candidates, "histology", matches[0][0], line, 4);
      append(candidates, "behavior", matches[0][1] || null, line, 4);
    }
  }

  function select(candidates) {
    if (!candidates.length) return { value: null, line: null, conflict: false };
    if (new Set(candidates.map(candidate => candidate.value)).size !== 1) {
      return { value: null, line: Math.min(...candidates.map(candidate => candidate.line)), conflict: true };
    }
    const chosen = candidates.slice().sort((a, b) => a.priority - b.priority || a.line - b.line)[0];
    return { value: chosen.value, line: chosen.line, conflict: false, candidate: chosen };
  }

  function templateFor(observations) {
    const metadata = observations.find(item => validator.component(validator.field(item, 3), 1) === "60572-5");
    if (!metadata) return { key: null, id: null, line: null };
    const value = decodeHl7(validator.field(metadata, 5));
    const identifier = validator.component(value, 1);
    const templateId = ECP_TEMPLATE.test(identifier) ? identifier : null;
    const lowered = value.toLowerCase();
    const template = (CONTENT.templates || []).find(item => item.patterns.some(pattern => lowered.includes(pattern)));
    return { key: template ? template.key : null, id: templateId, line: metadata.line };
  }

  function groupExtraction(index, segments) {
    const candidates = { site: [], histology: [], behavior: [], laterality: [], grade: [] };
    const observations = segments.filter(segment => segment.name === "OBX");
    const specimens = segments.filter(segment => segment.name === "SPM");
    const obr = segments.find(segment => segment.name === "OBR");
    observations.forEach(observation => {
      codedCandidates(observation, candidates);
      const label = decodeHl7(validator.component(validator.field(observation, 3), 2));
      const value = decodeHl7(validator.field(observation, 5));
      if (label) labeledCandidates(label + ": " + value, observation.line, candidates);
      labeledCandidates(value, observation.line, candidates);
    });
    specimens.forEach(specimen => {
      specimenSiteCandidates(specimen, candidates);
      if (!validator.field(specimen, 9)) return;
      validator.field(specimen, 9).split("~").forEach(repetition => {
        const identifier = validator.component(repetition, 1);
        const display = decodeHl7(validator.component(repetition, 2));
        append(candidates, "laterality", (CONTENT.laterality_snomed || {})[identifier] || normalizeLaterality(display), specimen.line, 3);
      });
    });
    const selected = {};
    Object.keys(candidates).forEach(fieldName => { selected[fieldName] = select(candidates[fieldName]); });
    let year = null, yearLine = null, yearSource = null;
    for (const specimen of specimens) {
      const match = validator.component(validator.field(specimen, 17), 1).match(/^(?:19|20)\d{2}/);
      if (match) { year = match[0]; yearLine = specimen.line; yearSource = "SPM-17"; break; }
    }
    if (year == null && obr) {
      const match = validator.field(obr, 7).match(/^(?:19|20)\d{2}/);
      if (match) { year = match[0]; yearLine = obr.line; yearSource = "OBR-7"; }
    }
    const template = templateFor(observations);
    return {
      index,
      line_number: segments[0].line,
      site: selected.site.value, site_line: selected.site.line,
      site_assumed_nos: !!(selected.site.candidate && selected.site.candidate.assumed_nos),
      histology: selected.histology.value, histology_line: selected.histology.line,
      behavior: selected.behavior.value, behavior_line: selected.behavior.line,
      laterality: selected.laterality.value, laterality_line: selected.laterality.line,
      grade: selected.grade.value, grade_line: selected.grade.line,
      year, year_line: yearLine, year_source: yearSource,
      template_key: template.key, template_id: template.id, template_line: template.line,
      conflicts: Object.keys(selected).filter(fieldName => selected[fieldName].conflict).map(fieldName => [fieldName, selected[fieldName].line])
    };
  }

  function outboundCodes(group) {
    const values = { site: group.site, hist: group.histology, behavior: group.behavior, laterality: group.laterality, grade: group.grade, year: group.year };
    const result = {};
    Object.keys(values).forEach(key => { if (values[key] != null) result[key] = values[key]; });
    return result;
  }

  function fieldSummary(value, line, extra) {
    return value == null ? null : Object.assign({ value, line_number: line }, extra || {});
  }

  function extractionSummary(groups) {
    return {
      groups: groups.map(group => ({
        group: group.index,
        line_number: group.line_number,
        site: fieldSummary(group.site, group.site_line, { assumed_nos: group.site_assumed_nos }),
        histology: fieldSummary(group.histology, group.histology_line),
        behavior: fieldSummary(group.behavior, group.behavior_line),
        laterality: fieldSummary(group.laterality, group.laterality_line),
        grade: fieldSummary(group.grade, group.grade_line),
        year: fieldSummary(group.year, group.year_line, { source: group.year_source }),
        template: group.template_key || group.template_id ? { key: group.template_key, id: group.template_id, line_number: group.template_line } : null,
        conflicting_fields: group.conflicts.map(conflict => conflict[0])
      })),
      disclosure_params: groups.filter(group => Object.keys(outboundCodes(group)).length).map(group => ({
        group: group.index, line_number: group.line_number, codes: outboundCodes(group)
      }))
    };
  }

  function extractInternal(text) {
    if (!validator) throw new Error("The syntax validator is required for content extraction.");
    const segments = validator.parseSegments(validator.normalizeMessage(text));
    const starts = segments.map((segment, index) => segment.name === "ORC" ? index : -1).filter(index => index >= 0);
    return starts.map((start, index) => groupExtraction(index + 1, segments.slice(start, starts[index + 1] == null ? segments.length : starts[index + 1])));
  }

  function extractContent(text) { return extractionSummary(extractInternal(text)); }

  function valid(value, expression, name) {
    if (!expression.test(value)) throw new Error("Invalid " + name + " value.");
    return value;
  }

  function algorithmForYear(year) {
    const numeric = year && YEAR_CODE.test(year) ? Number(year) : 9999;
    const entry = (CONTENT.algorithm_by_year || []).find(item => numeric >= Number(item.from_year));
    if (!entry) throw new SeerError("bad-input", "No pinned SEER staging algorithm covers the extracted diagnosis year.");
    return [entry.algorithm, entry.version];
  }

  function sortedObject(value) {
    if (Array.isArray(value)) return value.map(sortedObject);
    if (value && typeof value === "object") {
      const result = {};
      Object.keys(value).sort().forEach(key => { result[key] = sortedObject(value[key]); });
      return result;
    }
    return value;
  }

  function canonical(value) { return JSON.stringify(sortedObject(value)); }

  class SeerClient {
    constructor(transport, options) {
      this.transport = transport;
      this.cache = options.cache || sessionCache;
      this.maxCalls = Number(options.maxCalls || CONTENT.max_api_calls);
      this.networkCalls = 0;
      this.queries = [];
      this.base = CONTENT.seer_base_url;
    }

    async request(method, path, options) {
      options = options || {};
      if (!["GET", "POST"].includes(method) || path.startsWith("/") || path.includes("..")) throw new Error("Invalid SEER request path.");
      let url = this.base + path;
      const query = options.query || null;
      if (query) url += "?" + Object.keys(query).sort().map(key => encodeURIComponent(key) + "=" + encodeURIComponent(query[key])).join("&");
      if (!url.startsWith(this.base)) throw new Error("Blocked non-SEER request URL.");
      const body = options.body || null;
      const key = canonical({ method, url, body });
      const cached = this.cache.get(key);
      const maxAge = options.mutable ? Number(CONTENT.cache_ttl_seconds) * 1000 : null;
      if (cached && (maxAge == null || Date.now() - cached.stored_at <= maxAge)) {
        this.queries.push({ method, url, body, cached: true, status: cached.status });
        return cached.data;
      }
      if (this.networkCalls >= this.maxCalls) {
        this.queries.push({ method, url, body, cached: false, status: "budget" });
        throw new SeerError("budget", "The registry-content request budget was reached.");
      }
      this.networkCalls += 1;
      let response;
      try { response = await this.transport(method, url, body); }
      catch (error) {
        this.queries.push({ method, url, body, cached: false, status: "network" });
        if (error instanceof SeerError) throw error;
        throw new SeerError("network", "The SEER API request could not be completed.");
      }
      const status = response.status;
      const data = response.data;
      this.queries.push({ method, url, body, cached: false, status });
      if (status === 401) throw new SeerError("authentication", "The SEER API rejected the API key.", status);
      if (status === 403 || status === 429) throw new SeerError("rate-limit", "The SEER API rate limit or access policy blocked the request.", status);
      if (status < 200 || status >= 300) throw new SeerError("bad-response", "The SEER API returned an error response.", status);
      this.cache.set(key, { stored_at: Date.now(), status, data });
      return data;
    }

    async schemaLookup(algorithm, version, values) {
      algorithm = valid(algorithm, TOKEN, "algorithm"); version = valid(version, TOKEN, "version");
      const body = { site: valid(values.site, SITE_CODE, "site"), hist: valid(values.histology, HIST_CODE, "histology") };
      if (values.behavior != null) body.behavior = valid(values.behavior, BEHAVIOR_CODE, "behavior");
      if (values.year != null) body.year_dx = valid(values.year, YEAR_CODE, "year");
      const data = await this.request("POST", "staging/" + algorithm + "/" + version + "/schemas/lookup", { body });
      if (!Array.isArray(data) || data.some(item => !item || typeof item !== "object")) throw new SeerError("bad-response", "The SEER schema lookup response has an unexpected shape.");
      return data;
    }

    async schema(algorithm, version, schemaId) {
      [algorithm, version, schemaId] = [algorithm, version, schemaId].map((value, index) => valid(value, TOKEN, ["algorithm", "version", "schema id"][index]));
      const data = await this.request("GET", "staging/" + algorithm + "/" + version + "/schema/" + schemaId);
      if (!data || typeof data !== "object" || !Array.isArray(data.inputs)) throw new SeerError("bad-response", "The SEER schema response has an unexpected shape.");
      return data;
    }

    async table(algorithm, version, tableId) {
      [algorithm, version, tableId] = [algorithm, version, tableId].map((value, index) => valid(value, TOKEN, ["algorithm", "version", "table id"][index]));
      const data = await this.request("GET", "staging/" + algorithm + "/" + version + "/table/" + tableId);
      if (!data || typeof data !== "object" || !Array.isArray(data.rows)) throw new SeerError("bad-response", "The SEER staging table response has an unexpected shape.");
      return data;
    }

    async naaccrItem(version, item) {
      version = valid(version, TOKEN, "NAACCR version"); item = valid(item, /^\d{1,4}$/, "NAACCR item");
      const data = await this.request("GET", "naaccr/" + version + "/" + item);
      if (!data || typeof data !== "object" || Array.isArray(data)) throw new SeerError("bad-response", "The SEER NAACCR item response has an unexpected shape.");
      return data;
    }

    async diseaseSearch(morphology) {
      morphology = valid(morphology, MORPHOLOGY_CODE, "morphology");
      const version = valid(CONTENT.disease_version, TOKEN, "disease version");
      const data = await this.request("GET", "disease/" + version, { query: { q: morphology, type: "HEMATO" }, mutable: true });
      if (!data || typeof data !== "object" || !("results" in data || "total" in data || "count" in data)) throw new SeerError("bad-response", "The SEER disease search response has an unexpected shape.");
      return data;
    }

    async disease(diseaseId) {
      const version = valid(CONTENT.disease_version, TOKEN, "disease version");
      diseaseId = valid(diseaseId, TOKEN, "disease id");
      const data = await this.request("GET", "disease/" + version + "/id/" + diseaseId, { mutable: true });
      if (!data || typeof data !== "object" || Array.isArray(data)) throw new SeerError("bad-response", "The SEER disease response has an unexpected shape.");
      return data;
    }

    async samePrimary(first, second, year1, year2) {
      const version = valid(CONTENT.disease_version, TOKEN, "disease version");
      const query = { d1: valid(first, MORPHOLOGY_CODE, "morphology"), d2: valid(second, MORPHOLOGY_CODE, "morphology"), year1: valid(year1, YEAR_CODE, "year"), year2: valid(year2, YEAR_CODE, "year") };
      const data = await this.request("GET", "disease/" + version + "/same_primary", { query, mutable: true });
      if (!data || typeof data !== "object" || !("is_same" in data)) throw new SeerError("bad-response", "The SEER same-primary response has an unexpected shape.");
      return data;
    }

    async siteRecode(site, histology, behavior) {
      const algorithm = valid(CONTENT.site_recode_algorithm, TOKEN, "site-recode algorithm");
      const query = { site: valid(site, SITE_CODE, "site"), hist: valid(histology, HIST_CODE, "histology") };
      if (behavior != null) query.behavior = valid(behavior, BEHAVIOR_CODE, "behavior");
      const data = await this.request("GET", "recode/sitegroup/" + algorithm, { query, mutable: true });
      if (!data || typeof data !== "object" || !("site_group" in data)) throw new SeerError("bad-response", "The SEER site-recode response has an unexpected shape.");
      return data;
    }

    async mph(first, second) {
      function item(values) {
        const result = { primary_site: valid(values.site, SITE_CODE, "site"), histology_icd_o3: valid(values.hist, HIST_CODE, "histology") };
        const optional = { behavior: ["behavior_icd_o3", BEHAVIOR_CODE], laterality: ["laterality", /^[0-9]$/], year: ["date_of_diagnosis_year", YEAR_CODE] };
        Object.keys(optional).forEach(source => { if (values[source] != null) result[optional[source][0]] = valid(values[source], optional[source][1], source); });
        return result;
      }
      const data = await this.request("POST", "mph", { body: { input1: item(first), input2: item(second) }, mutable: true });
      if (!data || typeof data !== "object" || !("result" in data)) throw new SeerError("bad-response", "The SEER multiple-primary response has an unexpected shape.");
      return data;
    }
  }

  function templateConfig(key) { return (CONTENT.templates || []).find(item => item.key === key) || null; }

  function tableContains(table, value) {
    if (!Array.isArray(table.rows)) return false;
    return table.rows.some(row => Array.isArray(row) && row.length && String(row[0]).split(",").some(piece => {
      const part = piece.trim();
      if (part === value) return true;
      if (part.includes("-")) {
        const range = part.split("-", 2), low = range[0], high = range[1];
        return /^\d+$/.test(low) && /^\d+$/.test(high) && /^\d+$/.test(value) && low.length === high.length && high.length === value.length && Number(low) <= Number(value) && Number(value) <= Number(high);
      }
      return false;
    }));
  }

  class Evaluation {
    constructor(groups) { this.groups = groups; this.findings = []; this.coverage = (CONTENT.coverage_notices || []).slice(); this.failureKinds = new Set(); this.skippedOnline = false; this.blockedOnline = false; }
    add(ruleId, group, line, message, location) {
      const rule = RULES[ruleId];
      this.findings.push({ severity: rule.severity, rule_id: ruleId, location: location || (group ? "ORDER_OBSERVATION[" + group.index + "]" : "message"), line_number: line == null ? null : line, message, expected_behavior: rule.expected, source_section: rule.section });
    }
    apiFailure(error, group) {
      const kind = typeof error === "string" ? error : error.kind;
      if (this.failureKinds.has(kind)) return;
      this.failureKinds.add(kind);
      if (["authentication", "rate-limit", "network", "budget"].includes(kind)) this.blockedOnline = true;
      const labels = { "no-key": "No SEER API key was available", authentication: "SEER rejected the API key", "rate-limit": "SEER rate limiting or access policy blocked a request", network: "A SEER network request failed", "bad-response": "SEER returned an unusable response", budget: "The content-check request budget was reached", "bad-input": "No pinned SEER algorithm covers the extracted year" };
      this.add("CONTENT-API-01", group, group ? group.line_number : null, (labels[kind] || "A SEER request failed") + "; affected online checks were skipped.");
    }
    async call(group, operation) {
      if (this.blockedOnline) { this.skippedOnline = true; return null; }
      try { return await operation(); }
      catch (error) {
        if (!(error instanceof SeerError)) throw error;
        if (error.kind === "aborted" || error.kind === "blocked") throw error;
        this.apiFailure(error, group); this.skippedOnline = true; return null;
      }
    }
  }

  function localChecks(evaluation) {
    evaluation.groups.forEach(group => {
      group.conflicts.forEach(conflict => evaluation.add("CONTENT-EXTRACT-01", group, conflict[1], "Conflicting " + conflict[0] + " candidates were found, so that field was not sent or checked.", "ORDER_OBSERVATION[" + group.index + "]." + conflict[0]));
      const template = templateConfig(group.template_key), prefixes = template ? template.site_prefixes : [];
      if (group.site && prefixes.length && !prefixes.some(prefix => group.site.startsWith(prefix))) evaluation.add("CONTENT-SITE-01", group, group.site_line, "The extracted primary-site code does not match the recognized template family.", "ORDER_OBSERVATION[" + group.index + "].site");
      if (group.site_assumed_nos) evaluation.coverage.push("Order group " + group.index + ": a three-character topography code was normalized to its NOS subsite.");
      if (group.template_line && !group.template_key) evaluation.coverage.push("Order group " + group.index + ": template metadata was present but did not match a configured template family; template-coherence checks were skipped.");
      if (group.year_source) evaluation.coverage.push("Order group " + group.index + ": the year used for SEER selection was inferred from " + group.year_source + "; it is not a dedicated registry diagnosis date.");
    });
  }

  async function checkSchemaFields(evaluation, client, group, algorithm, version, schema) {
    const inputs = (schema.inputs || []).filter(item => item && typeof item === "object");
    const available = { site: group.site, hist: group.histology, behavior: group.behavior, year_dx: group.year, grade_path: group.grade, grade_clin: group.grade, grade: group.grade };
    const missing = [...new Set(inputs.filter(item => item.used_for_staging === true && item.default == null && !available[String(item.key)]).map(item => String(item.key)))].sort();
    if (missing.length) evaluation.add("CONTENT-FIELD-02", group, group.line_number, "The selected schema has " + missing.length + " non-default staging input(s) that were not extracted: " + missing.join(", ") + ".");
    const checks = [
      ["CONTENT-FIELD-01", group.behavior, group.behavior_line, ["behavior"]],
      ["CONTENT-FIELD-03", group.grade, group.grade_line, ["grade_path", "grade_clin", "grade"]]
    ];
    for (const check of checks) {
      const ruleId = check[0], value = check[1], line = check[2], keys = check[3];
      if (value == null) continue;
      let definition = null;
      for (const key of keys) { definition = inputs.find(item => item.key === key && item.table); if (definition) break; }
      if (!definition) { evaluation.coverage.push("Order group " + group.index + ": the selected schema did not publish a table for the extracted " + keys[keys.length - 1] + " value."); continue; }
      const table = await evaluation.call(group, () => client.table(algorithm, version, String(definition.table)));
      if (table && !tableContains(table, value)) {
        const fieldName = ruleId === "CONTENT-FIELD-01" ? "behavior" : "grade";
        evaluation.add(ruleId, group, line, "The extracted " + fieldName + " code is not present in the selected schema's value table.", "ORDER_OBSERVATION[" + group.index + "]." + fieldName);
      }
    }
  }

  async function checkDictionary(evaluation, client, group) {
    for (const check of [["laterality", group.laterality, group.laterality_line], ["grade", group.grade, group.grade_line]]) {
      const fieldName = check[0], value = check[1], line = check[2]; if (value == null) continue;
      const itemNumber = CONTENT.naaccr_items[fieldName];
      const item = await evaluation.call(group, () => client.naaccrItem(CONTENT.naaccr_version, itemNumber));
      if (!item) continue;
      if (!Array.isArray(item.allowed_codes) || !item.allowed_codes.length) { evaluation.coverage.push("Order group " + group.index + ": NAACCR item " + itemNumber + " did not publish a discrete allowed-code list."); continue; }
      const codes = new Set(item.allowed_codes.filter(entry => entry && entry.code != null).map(entry => String(entry.code)));
      if (!codes.has(value)) evaluation.add("CONTENT-DICT-01", group, line, "The extracted " + fieldName + " code is not in NAACCR item " + itemNumber + "'s allowed-code list.", "ORDER_OBSERVATION[" + group.index + "]." + fieldName);
    }
  }

  async function checkHeme(evaluation, client, group) {
    if (group.histology == null || Number(group.histology) < Number(CONTENT.heme_histology_min)) return;
    if (group.behavior == null) { evaluation.skippedOnline = true; evaluation.coverage.push("Order group " + group.index + ": hematopoietic lookup was skipped because no behavior code was extracted."); return; }
    const morphology = group.histology + "/" + group.behavior;
    const search = await evaluation.call(group, () => client.diseaseSearch(morphology));
    if (!search) return;
    if (!Array.isArray(search.results) || !search.results.length) { evaluation.add("CONTENT-HEME-01", group, group.histology_line, "The extracted hematopoietic morphology was not found in the SEER disease database."); return; }
    let exact = null;
    for (const result of search.results.slice(0, 10)) {
      if (!result || typeof result.id !== "string") continue;
      const detail = await evaluation.call(group, () => client.disease(result.id));
      if (detail && detail.icdO3_morphology === morphology) { exact = detail; break; }
    }
    if (!exact) { if (!evaluation.failureKinds.size) evaluation.add("CONTENT-HEME-01", group, group.histology_line, "The extracted hematopoietic morphology was not found as an exact SEER disease code."); return; }
    if (group.year && exact.valid && typeof exact.valid === "object") {
      const year = Number(group.year), start = exact.valid.start, end = exact.valid.end;
      if ((Number.isInteger(start) && year < start) || (Number.isInteger(end) && year > end)) evaluation.add("CONTENT-HEME-02", group, group.year_line, "The diagnosis year is outside the SEER validity range for the extracted morphology.");
    }
  }

  async function onlineGroupChecks(evaluation, client, group) {
    if (!group.site || !group.histology) {
      evaluation.skippedOnline = true; evaluation.coverage.push("Order group " + group.index + ": site and histology are both needed for staging and site-recode checks.");
      await checkHeme(evaluation, client, group); await checkDictionary(evaluation, client, group); return;
    }
    if (group.year == null) { evaluation.skippedOnline = true; evaluation.coverage.push("Order group " + group.index + ": no year was extracted, so current EOD data were used and year-sensitive coverage is incomplete."); }
    let algorithm, version;
    try { [algorithm, version] = algorithmForYear(group.year); }
    catch (error) { evaluation.apiFailure(error, group); evaluation.skippedOnline = true; return; }
    const lookupValues = Object.assign({}, group, { behavior: ["0", "1", "2", "3"].includes(group.behavior) ? group.behavior : null });
    const schemas = await evaluation.call(group, () => client.schemaLookup(algorithm, version, lookupValues));
    if (Array.isArray(schemas)) {
      if (!schemas.length) evaluation.add("CONTENT-COMBO-01", group, group.site_line || group.histology_line, "The pinned staging algorithm returned no schema for the extracted site and histology.");
      else if (schemas.length > 1) { evaluation.add("CONTENT-COMBO-02", group, group.site_line || group.histology_line, "The pinned staging algorithm returned " + schemas.length + " schemas; schema-specific field checks were skipped."); evaluation.skippedOnline = true; }
      else {
        const schemaId = schemas[0].id;
        if (typeof schemaId !== "string") { evaluation.apiFailure(new SeerError("bad-response", "Schema id is missing."), group); evaluation.skippedOnline = true; }
        else {
          const template = templateConfig(group.template_key), expected = template ? template.expected_schema_ids : [];
          if (expected.length && !expected.includes(schemaId)) evaluation.add("CONTENT-COMBO-03", group, group.template_line || group.site_line, "The selected SEER schema does not match the recognized template family.");
          const schema = await evaluation.call(group, () => client.schema(algorithm, version, schemaId));
          if (schema) await checkSchemaFields(evaluation, client, group, algorithm, version, schema);
        }
      }
    }
    const recodeBehavior = ["0", "1", "2", "3"].includes(group.behavior) ? group.behavior : null;
    const recode = await evaluation.call(group, () => client.siteRecode(group.site, group.histology, recodeBehavior));
    if (recode) {
      const siteGroup = String(recode.site_group);
      evaluation.add("CONTENT-RECODE-01", group, group.site_line, "SEER site-recode group: " + siteGroup + ".");
      const template = templateConfig(group.template_key), expected = template ? template.expected_recode_codes : [];
      if (expected.length && !expected.includes(siteGroup)) evaluation.add("CONTENT-RECODE-02", group, group.template_line || group.site_line, "The SEER site-recode group does not match the recognized template family.");
    }
    await checkHeme(evaluation, client, group); await checkDictionary(evaluation, client, group);
  }

  async function pairChecks(evaluation, client) {
    const eligible = evaluation.groups.filter(group => group.site && group.histology);
    for (let firstIndex = 0; firstIndex < eligible.length; firstIndex += 1) {
      for (let secondIndex = firstIndex + 1; secondIndex < eligible.length; secondIndex += 1) {
        const first = eligible[firstIndex], second = eligible[secondIndex];
        if (first.behavior && second.behavior && first.year && second.year && Number(first.histology) >= Number(CONTENT.heme_histology_min) && Number(second.histology) >= Number(CONTENT.heme_histology_min)) {
          const same = await evaluation.call(first, () => client.samePrimary(first.histology + "/" + first.behavior, second.histology + "/" + second.behavior, first.year, second.year));
          if (same) evaluation.add("CONTENT-MPH-01", first, first.line_number, "SEER hematopoietic rules classify groups " + first.index + " and " + second.index + " as " + (same.is_same === true ? "the same primary" : "different primaries") + ".");
        }
        const result = await evaluation.call(first, () => client.mph(outboundCodes(first), outboundCodes(second)));
        if (result) evaluation.add("CONTENT-MPH-01", first, first.line_number, "SEER multiple-primary rules classify groups " + first.index + " and " + second.index + " as " + String(result.result || "UNKNOWN") + (result.step ? " at rule " + result.step : "") + ".");
      }
    }
  }

  async function validateContent(text, options) {
    options = options || {};
    const syntaxReport = validator.validateMessage(text);
    const syntaxOk = options.syntaxValid == null ? syntaxReport.valid : !!options.syntaxValid;
    const groups = extractInternal(text);
    const evaluation = new Evaluation(groups);
    localChecks(evaluation);
    let client = null, status;
    const hasCodes = groups.some(group => group.site || group.histology);
    if (!hasCodes) { status = "not-applicable"; evaluation.coverage.push("No registry site or histology codes were extracted, so no SEER request was needed."); }
    else if (!syntaxOk) { status = "partial"; evaluation.skippedOnline = true; evaluation.coverage.push("Online content checks were skipped because syntax validation found errors."); }
    else if (typeof options.transport !== "function") { status = "partial"; evaluation.apiFailure("no-key", null); evaluation.skippedOnline = true; }
    else {
      client = new SeerClient(options.transport, { cache: options.cache || sessionCache, maxCalls: options.maxCalls });
      for (const group of groups) await onlineGroupChecks(evaluation, client, group);
      await pairChecks(evaluation, client);
      status = evaluation.failureKinds.size || evaluation.skippedOnline ? "partial" : "complete";
    }
    evaluation.findings.sort((a, b) => (a.line_number || 0) - (b.line_number || 0) || a.rule_id.localeCompare(b.rule_id) || a.location.localeCompare(b.location));
    const counts = { error: 0, warning: 0, information: 0 }; evaluation.findings.forEach(finding => { counts[finding.severity] += 1; });
    return {
      schema_version: CONTENT.schema_version,
      content_ruleset_version: CONTENT.content_ruleset_version,
      profile: CATALOG.profile,
      based_on: { ruleset_version: syntaxReport.ruleset_version, detected_report_style: syntaxReport.detected_report_style, syntax_valid: syntaxOk },
      status,
      valid: counts.error === 0,
      counts,
      findings: evaluation.findings,
      extraction: extractionSummary(groups),
      queries: client ? client.queries : [],
      coverage_notices: [...new Set(evaluation.coverage)],
      attribution: CONTENT.attribution
    };
  }

  return { decodeHl7, extractContent, validateContent, SeerError, SeerClient, sessionCache };
});
