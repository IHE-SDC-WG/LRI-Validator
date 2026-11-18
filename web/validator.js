(function (root, factory) {
  const api = factory(root.__LRI_CATALOG__ || {});
  if (typeof module === "object" && module.exports) module.exports = api;
  root.LriValidator = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function (CATALOG) {
  "use strict";

  const C = CATALOG.constants || {};
  const RULES = CATALOG.rules || {};
  const REQUIRED = {
    MSH: [1, 2, 4, 7, 9, 10, 11, 12, 15, 16, 21], PID: [1, 3, 5, 8], PV1: [1, 2],
    ORC: [1, 3, 12, 21], OBR: [1, 3, 4, 7, 16, 21, 22, 25, 32], OBX: [1, 2, 3, 5, 11],
    SPM: [1, 2, 4, 17, 18], NTE: [1, 3]
  };
  const EXPECTED = {
    MSH: [3, 5, 6, 13, 14, 17, 19], PID: [7, 10, 11, 13, 14, 15, 16, 17, 18, 22, 30, 31, 32, 39],
    PV1: [7, 8, 9, 17], ORC: [2, 4, 22, 23, 24, 28], OBR: [2, 10, 11, 13, 17, 29, 31, 44, 47, 49, 50],
    OBX: [7, 8, 14, 16, 17, 19], SPM: [3, 5, 7, 8, 9, 11, 21, 24, 30, 31], NTE: [2, 4]
  };
  const MAX = {
    "PID-3": 8, "PID-5": 8, "PID-11": 4, "PID-13": 8, "PID-14": 4, "PID-15": 1,
    "PID-16": 1, "PID-17": 1, "PID-18": 1, "PID-29": 1, "PID-30": 1, "PID-31": 1,
    "PID-32": 3, "PID-39": 5, "PV1-7": 2, "PV1-8": 2, "PV1-9": 2, "PV1-17": 2,
    "ORC-21": 1, "ORC-22": 4, "ORC-23": 4, "ORC-24": 4, "ORC-28": 1, "OBR-10": 4,
    "OBR-16": 4, "OBR-17": 4, "OBR-21": 1, "OBR-28": 999, "OBR-29": 1, "OBR-31": 20,
    "OBR-32": 1, "OBR-44": 1, "OBR-50": 1, "OBX-5": 1, "OBX-14": 1, "OBX-15": 1,
    "OBX-16": 5, "OBX-17": 6, "OBX-19": 1, "SPM-2": 1, "SPM-4": 1, "SPM-7": 1,
    "SPM-8": 1, "SPM-11": 1, "SPM-17": 1, "SPM-18": 1, "SPM-24": 5, "SPM-30": 1,
    "SPM-31": 1, "NTE-2": 1, "NTE-3": 1, "NTE-4": 1
  };
  const OID = /^(?:(?:0|1)\.(?:0|[1-9]|[1-3][0-9])|2\.(?:0|[1-9]\d*))(?:\.(?:0|[1-9]\d*))*$/;
  const MD = /^[A-Za-z]{2,4}[_-].+$/;
  const DT = /^(?:0000|\d{4}(?:\d{2}(?:\d{2}(?:\d{2}(?:\d{2}(?:\d{2}(?:\.\d{1,4})?)?)?)?)?)?)(?:[+-]\d{4})?$/;
  const ECP = /^(\d{1,9}\.\d{9})(?:__([1-9]\d*))?$/;
  const HD04_TYPES = ["CLIA", "NPI", "MD", "ISO"];
  const XCN03_FIELDS = { PV1: [7, 8, 9, 17], ORC: [12], OBR: [10, 16, 28], OBX: [16] };
  const XON04_FIELDS = { ORC: [21], OBX: [23] };
  const XCN03_EXCLUDED = [[7, "degree"], [17, "name validity range"]];
  const NPI_EXAMPLE = ["1234567893", "NPI"];
  const OID_EXAMPLE = ["2.16.840.1.113883.19.5", "ISO"];
  const TYPED_LABELS = { NPI: "a valid NPI", MD: "a license number with a 2-4 letter state/province prefix", ISO: "an ISO OID" };

  function normalizeMessage(text) {
    let value = String(text).replace(/^\ufeff/, "").trim();
    if (value.startsWith("\x0b")) {
      value = value.slice(1);
      if (value.endsWith("\x1c\r")) value = value.slice(0, -2);
      else if (value.endsWith("\x1c")) value = value.slice(0, -1);
      else throw new Error("MLLP start framing was found without a valid end frame.");
    } else if (value.includes("\x0b") || value.includes("\x1c")) {
      throw new Error("Partial or embedded MLLP framing is not supported.");
    }
    const lines = value.replace(/\r\n/g, "\n").replace(/\r/g, "\n").split("\n").filter(line => line.trim());
    if (!lines.length) throw new Error("No HL7 message was provided.");
    if (["FHS", "BHS"].includes(lines[0].slice(0, 3))) throw new Error("FHS/BHS batch wrappers are not supported; provide one ORU_R01 message.");
    if (lines.filter(line => line.startsWith("MSH")).length !== 1) throw new Error("Exactly one HL7 message is supported per validation.");
    return lines.join("\r") + "\r";
  }

  function parseSegments(normalized) {
    return normalized.replace(/\r$/, "").split("\r").map((raw, index) => ({ name: raw.slice(0, 3), parts: raw.split("|"), line: index + 1 }));
  }
  function field(segment, number) {
    if (segment.name === "MSH" && number === 1) return "|";
    const index = segment.name === "MSH" ? number - 1 : number;
    return segment.parts[index] || "";
  }
  function component(value, number, separator) { return (value || "").split(separator || "^")[number - 1] || ""; }
  function validNpi(value) {
    if (!/^\d{10}$/.test(value)) return false;
    const digits = ("80840" + value.slice(0, 9)).split("").map(Number).reverse();
    let total = 0;
    digits.forEach((digit, index) => { const n = index % 2 === 0 ? digit * 2 : digit; total += Math.floor(n / 10) + n % 10; });
    return (10 - total % 10) % 10 === Number(value[9]);
  }
  function parseDate(value) {
    value = component(value, 1);
    if (!value || value === "0000" || !DT.test(value)) return null;
    const core = value.replace(/[+-]\d{4}$/, "").split(".")[0];
    if (core.length < 8) return null;
    const padded = (core + "000000").slice(0, 14);
    const y = +padded.slice(0, 4), m = +padded.slice(4, 6), d = +padded.slice(6, 8);
    const hh = +padded.slice(8, 10), mm = +padded.slice(10, 12), ss = +padded.slice(12, 14);
    const date = new Date(Date.UTC(y, m - 1, d, hh, mm, ss));
    if (date.getUTCFullYear() !== y || date.getUTCMonth() !== m - 1 || date.getUTCDate() !== d) return null;
    return date.getTime();
  }

  function classifyReportStyle(obx) {
    if (!obx.length) return "not detected";
    const first = obx[0], firstCode = component(field(first, 3), 1), declaration = field(first, 5);
    if (firstCode === "60573-3") {
      if (C.document_styles[declaration]) return C.document_styles[declaration];
      if (declaration.endsWith(" Synoptic Summary") && !declaration.startsWith("CAP ")) return "synoptic summary";
      if (declaration.endsWith(" Synoptic Segmented") && !declaration.startsWith("CAP ")) return "synoptic segmented";
      return "unknown synoptic";
    }
    const codes = new Set(obx.map(segment => component(field(segment, 3), 1)));
    return obx.length > 1 && [...codes].every(code => C.narrative_obx3_loincs.includes(code)) ? "structured narrative" : "unstructured narrative";
  }

  function validateMessage(text) {
    const segments = parseSegments(normalizeMessage(text));
    const findings = [], styles = [];
    const all = name => segments.filter(segment => segment.name === name);
    const one = name => segments.find(segment => segment.name === name);
    function add(ruleId, location, lineNumber, message) {
      const rule = RULES[ruleId];
      findings.push({ severity: rule.severity, rule_id: ruleId, location, line_number: lineNumber == null ? null : lineNumber,
        message, expected_behavior: rule.expected, source_section: rule.section });
    }

    const malformed = segments.find(s => !/^[A-Z0-9]{3}$/.test(s.name));
    if (malformed) add("ER7-001", malformed.name || "message", malformed.line, "A segment identifier is malformed.");
    const msh = one("MSH");
    if (!msh) add("STRUCTURE-001", "MSH", null, "MSH is missing.");
    else {
      if (msh.parts[0] !== "MSH" || field(msh, 1) !== "|") add("LRI-13", "MSH-1", msh.line, "The field separator is not |.");
      if (!["^~\\&", "^~\\&#"].includes(field(msh, 2))) add("LRI-14", "MSH-2", msh.line, "The encoding characters are invalid.");
      if (field(msh, 9).split("^").slice(0, 3).join("^") !== "ORU^R01^ORU_R01") add("LRI-15", "MSH-9", msh.line, "The message identity is invalid.");
      if (component(field(msh, 12), 1) !== "2.5.1") add("LRI-16", "MSH-12.1", msh.line, "The version is invalid.");
    }
    if (segments.length && segments[0].name !== "MSH") add("STRUCTURE-001", segments[0].name, segments[0].line, "MSH must be first.");
    [["MSH", 1, 1], ["PID", 1, 1], ["PV1", 1, 1], ["ORC", 1, 999], ["OBR", 1, 999], ["OBX", 1, 999], ["SPM", 1, 999]].forEach(([name, min, max]) => {
      const count = all(name).length;
      if (count < min || count > max) add("STRUCTURE-001", name, null, "Segment cardinality is invalid.");
    });
    all("DSC").forEach(s => add("DSC-001", "DSC", s.line, "DSC is prohibited."));
    const rank = { MSH: 0, SFT: 1, PID: 2, PD1: 3, NTE: 99, NK1: 4, PV1: 5, PV2: 6, ORC: 7, OBR: 8, TQ1: 9, TQ2: 10, OBX: 11, PRT: 12, SPM: 13 };
    let last = -1, inOrders = false;
    segments.forEach(s => {
      if (s.name === "NTE") return;
      if (s.name === "ORC") { inOrders = true; last = rank.ORC; return; }
      const current = rank[s.name]; if (current == null || s.name === "DSC") return;
      if (inOrders && ["OBX", "PRT", "SPM"].includes(s.name)) return;
      if (inOrders && s.name === "OBR") last = current;
      else if (current < last) add("STRUCTURE-001", s.name, s.line, "Segment is out of profile order.");
      else last = current;
    });
    segments.forEach(s => {
      (REQUIRED[s.name] || []).forEach(n => { if (!field(s, n)) add("FIELD-R", `${s.name}-${n}`, s.line, "A required field is empty."); });
      (EXPECTED[s.name] || []).forEach(n => { if (!field(s, n)) add("FIELD-RE", `${s.name}-${n}`, s.line, "An expected-when-known field is empty."); });
      Object.keys(MAX).forEach(key => {
        const [name, n] = key.split("-");
        if (s.name === name && field(s, +n) && field(s, +n).split("~").length > MAX[key]) add("CARDINALITY-001", key, s.line, "Field repetition maximum is exceeded.");
      });
    });
    all("PID").forEach(s => { if (field(s, 30) === "Y" && !field(s, 29)) add("FIELD-R", "PID-29", s.line, "PID-29 is required by PID-30."); });

    if (msh) {
      const ids = field(msh, 21).split("~").map(rep => {
        const id = component(rep, 3);
        if (id && !OID.test(id)) add("LRI-2", "MSH-21.3", msh.line, "A profile identifier in MSH-21.3 is not an ISO OID.");
        if (id && component(rep, 4) !== "ISO") add("LRI-3", "MSH-21.4", msh.line, "A profile identifier type in MSH-21.4 is not ISO.");
        return id;
      });
      const o = C.profile_oids;
      if (!ids.includes(o.naaccr)) add("LRI-NAACCR-PROFILE", "MSH-21", msh.line, "The NAACCR component OID is missing.");
      if (ids.includes(o.conflicting_table_ng_fru)) {
        add("LRI-11", "MSH-21", msh.line, "The conflicting table OID does not satisfy LRI-11.");
        add("DRAFT-CONFLICT-01", "MSH-21", msh.line, "The conflicting table OID is present.");
      } else if (!(ids.includes(o.legacy_ng_fru) || [o.common, o.ng, o.fru].every(id => ids.includes(id)))) add("LRI-11", "MSH-21", msh.line, "NG-FRU identifiers are incomplete.");
    }
    all("OBR").forEach((s, i) => { if (field(s, 1) !== String(i + 1)) add("LRI-34", "OBR-1", s.line, "OBR set ID is out of sequence."); });
    ["PID", "PV1"].forEach(name => all(name).forEach(s => { if (field(s, 1) !== "1") add("SETID-001", `${name}-1`, s.line, "Set ID must be 1."); }));

    function typed(uid, kind, location, line, hd) {
      if (kind === "NPI" && !validNpi(uid)) add(hd ? "LRI-NAACCR-06" : "LRI-NAACCR-03", location, line, "The universal identifier is not a valid NPI.");
      else if (kind === "MD" && !MD.test(uid)) add(hd ? "LRI-NAACCR-07" : "LRI-NAACCR-04", location, line, "The universal identifier lacks the required state/province prefix.");
      else if (kind === "ISO" && !OID.test(uid)) add(hd ? "LRI-NAACCR-08" : "LRI-NAACCR-05", location, line, "The universal identifier is not an ISO OID.");
    }
    function checkHd04(value, separator, location, line, example) {
      if (!value) return;
      const namespace = component(value, 1, separator), uid = component(value, 2, separator), kind = component(value, 3, separator);
      const missing = [["universal ID", uid], ["type", kind]].filter(([, part]) => !part).map(([label]) => label);
      if (missing.length) {
        const sample = [namespace || "LOCAL", ...example].join(separator);
        const message = `${location} is "${value}" with no ${missing.join(" or ")}; HD_04 needs namespace${separator}ID${separator}type, e.g. ${sample}.`;
        [[2, uid], [3, kind]].forEach(([number, part]) => { if (!part) add("COMPONENT-R", `${location}.${number}`, line, message); });
      }
      if (kind && !HD04_TYPES.includes(kind)) add("HD04-001", `${location}.3`, line, `${location}.3 is "${kind}"; HD_04 allows CLIA, NPI, MD, or ISO.`);
      else if (uid && kind) typed(uid, kind, `${location}.2`, line, true);
    }
    if (msh) [3, 4, 5, 6].forEach(n => checkHd04(field(msh, n), "^", `MSH-${n}`, msh.line, OID_EXAMPLE));
    [["ORC", [2, 3, 4]], ["OBR", [2, 3]]].forEach(([name, fields]) => all(name).forEach(s => fields.forEach(n => { const v = field(s, n); if (v) typed(component(v, 3), component(v, 4), `${name}-${n}`, s.line, false); })));
    segments.forEach(s => {
      (XCN03_FIELDS[s.name] || []).forEach(n => {
        const location = `${s.name}-${n}`;
        field(s, n).split("~").forEach(rep => {
          if (!rep) return;
          if (!component(rep, 2)) add("COMPONENT-R", `${location}.2`, s.line, `${location}.2 (family name) is empty; XCN_03 requires it.`);
          XCN03_EXCLUDED.forEach(([c, label]) => { if (component(rep, c)) add("COMPONENT-X", `${location}.${c}`, s.line, `${location}.${c} (${label}) is valued; XCN_03 excludes it.`); });
          [9, 14].forEach(c => checkHd04(component(rep, c), "&", `${location}.${c}`, s.line, NPI_EXAMPLE));
        });
      });
      (XON04_FIELDS[s.name] || []).forEach(n => field(s, n).split("~").forEach(rep => checkHd04(component(rep, 6), "&", `${s.name}-${n}.6`, s.line, OID_EXAMPLE)));
    });
    all("OBR").forEach(s => {
      const ndl = field(s, 32), cnn = component(ndl, 1); if (!cnn) return;
      const namespace = component(cnn, 9, "&"), uid = component(cnn, 10, "&"), kind = component(cnn, 11, "&");
      const hints = [];
      if ([2, 3].some(n => component(ndl, n) && !DT.test(component(ndl, n)))) hints.push("OBR-32.2/OBR-32.3 hold non-timestamp text: the interpreter's parts must be &-separated inside OBR-32.1; ^ starts the next OBR-32 component.");
      if (namespace && !uid && !kind) hints.push(`CNN.9 is "${namespace}": the identifier type belongs in CNN.11 and the ID in CNN.10, e.g. CMS&2.16.840.1.113883.4.6&ISO.`);
      const found = [];
      if (!uid) found.push(["LRI-NAACCR-01", "OBR-32.1.10", "CNN.10 (assigning authority universal ID) is empty."]);
      if (!["NPI", "MD", "ISO"].includes(kind)) found.push(["LRI-NAACCR-02", "OBR-32.1.11", `CNN.11 (assigning authority universal ID type) ${kind ? `is "${kind}"` : "is empty"}; it must be NPI, MD, or ISO.`]);
      else if (uid) {
        const valid = kind === "NPI" ? validNpi(uid) : kind === "MD" ? MD.test(uid) : OID.test(uid);
        if (!valid) found.push(["LRI-NAACCR-01", "OBR-32.1.10", `CNN.10 is not ${TYPED_LABELS[kind]} as CNN.11 ${kind} requires.`]);
      }
      found.forEach(([ruleId, location, message], index) => add(ruleId, location, s.line, hints.length && index === found.length - 1 ? [message, ...hints].join(" ") : message));
    });

    const starts = segments.map((s, i) => s.name === "ORC" ? i : -1).filter(i => i >= 0), fillers = new Set();
    starts.forEach((start, groupIndex) => {
      const group = segments.slice(start, starts[groupIndex + 1] == null ? segments.length : starts[groupIndex + 1]);
      const orc = group[0], obrs = group.filter(s => s.name === "OBR");
      if (obrs.length !== 1) { add("STRUCTURE-001", "ORDER_OBSERVATION", orc.line, "Order group OBR cardinality is invalid."); return; }
      const obr = obrs[0], obx = group.filter(s => s.name === "OBX"), spm = group.filter(s => s.name === "SPM");
      if (field(obr, 25) !== "X" && !obx.length) add("STRUCTURE-001", "OBX", obr.line, "Result OBX is missing.");
      if (!spm.length) add("STRUCTURE-001", "SPM", obr.line, "Specimen information is missing.");
      const firstSpm = spm.length ? Math.min(...spm.map(s => s.line)) : 1e9;
      if (obx.some(s => s.line > firstSpm)) add("STRUCTURE-001", "OBX/SPM", firstSpm, "OBX follows SPM.");
      obx.forEach((s, i) => { if (field(s, 1) !== String(i + 1)) add("SETID-001", "OBX-1", s.line, "OBX set ID is out of sequence."); });
      spm.forEach((s, i) => { if (field(s, 1) !== String(i + 1)) add("SETID-001", "SPM-1", s.line, "SPM set ID is out of sequence."); });
      [["LRI-23", 2, 2], ["LRI-24", 3, 3], ["LRI-25", 12, 16]].forEach(([rule, a, b]) => { if (field(orc, a) && field(orc, a) !== field(obr, b)) add(rule, `ORC-${a}/OBR-${b}`, obr.line, "Paired ORC and OBR values differ."); });
      if (fillers.has(field(orc, 3))) add("LRI-28", "ORC-3", orc.line, "Filler order number repeats."); fillers.add(field(orc, 3));
      dates(obr, obx, spm); status(obr, obx); style(obr, obx); spmTerms(spm);
    });

    function dates(obr, obx, spm) {
      let dated = [[obr, 7], [obr, 8], [obr, 22]];
      obx.forEach(s => { dated.push([s, 14], [s, 19]); }); spm.forEach(s => { dated.push([s, 17], [s, 18]); });
      dated.forEach(([s, n]) => { if (field(s, n)) field(s, n).split("^").forEach(v => { if (v && (!DT.test(v) || (v !== "0000" && v.replace(/[+-]\d{4}$/, "").split(".")[0].length >= 8 && parseDate(v) == null))) add("DATE-001", `${s.name}-${n}`, s.line, "Date/time is invalid."); }); });
      const d7 = parseDate(field(obr, 7)), d8 = parseDate(field(obr, 8)), d22 = parseDate(field(obr, 22));
      if (d7 != null && d8 != null && d8 < d7) add("LRI-33", "OBR-8", obr.line, "OBR-8 precedes OBR-7.");
      if (d7 != null && d22 != null && d22 < d7) add("DATE-001", "OBR-22", obr.line, "Report date precedes collection.");
      spm.forEach(s => { const start = parseDate(component(field(s, 17), 1)), parsedFinish = parseDate(component(field(s, 17), 2)), finish = parsedFinish == null ? start : parsedFinish, received = parseDate(field(s, 18));
        if (start != null && d7 != null && start !== d7) add("DATE-001", "SPM-17.1/OBR-7", s.line, "Collection dates differ.");
        if (start != null && received != null && received < start) add("DATE-001", "SPM-18", s.line, "Receipt precedes collection.");
        obx.forEach(o => { const observed = parseDate(field(o, 14)); if (observed != null && start != null && finish != null && (observed < start || observed > finish)) add("DATE-001", "OBX-14", o.line, "Observation is outside the specimen range."); });
      });
    }
    function status(obr, obx) {
      const values = obx.map(s => field(s, 11)).filter(Boolean); if (!values.length) return;
      let expected;
      if (values.every(v => ["N", "X", "D"].includes(v))) expected = "X";
      else if (values.some(v => ["C", "A", "B", "W"].includes(v))) expected = values.some(v => ["I", "P"].includes(v)) ? "M" : "C";
      else if (values.includes("P")) expected = "P"; else if (values.includes("I")) expected = values.includes("F") ? "A" : "I"; else expected = "F";
      if (field(obr, 25) !== expected) add("STATUS-001", "OBR-25", obr.line, "OBR-25 does not match OBX-11 values.");
    }
    function style(obr, obx) {
      if (!obx.length) return;
      const first = obx[0], reportStyle = classifyReportStyle(obx);
      if (reportStyle === "unknown synoptic") add("STYLE-001", "OBX-5", first.line, "Report style declaration is invalid.");
      styles.push(reportStyle); const code = component(field(obr, 4), 1);
      if (C.deprecated_loincs.includes(code)) add("DEPRECATED-001", "OBR-4", obr.line, "A deprecated report LOINC is used.");
      else if (!C.obr4_loincs.includes(code)) add("OBR4-001", "OBR-4", obr.line, "The report code is not completely enumerated in the draft table.");
      if (["synoptic summary", "synoptic segmented", "CAP eCP"].includes(reportStyle) && !C.synoptic_obr4_loincs.includes(code)) add("STYLE-001", "OBR-4", obr.line, "Synoptic style has a non-synoptic OBR-4.");
      if (["synoptic summary", "synoptic segmented", "CAP eCP"].includes(reportStyle)) metadata(obx, reportStyle);
      if (reportStyle === "unstructured narrative" && obx.length !== 1) add("NARRATIVE-001", "OBX", first.line, "Unstructured narrative has multiple OBXs.");
      if (reportStyle === "structured narrative") obx.forEach(s => { if (!C.narrative_obx3_loincs.includes(component(field(s, 3), 1))) add("NARRATIVE-001", "OBX-3", s.line, "Section code is outside Table 7.14."); });
      obx4(obx, reportStyle); if (reportStyle === "CAP eCP") ecp(obx.slice(3));
    }
    function metadata(obx, reportStyle) {
      if (obx.length < 4) { add("STYLE-002", "OBX", obx[0].line, "Synoptic metadata/content is incomplete."); return; }
      const types = reportStyle === "CAP eCP" ? ["ST", "CWE", "ST"] : ["TX", "TX", "TX"];
      for (let i = 0; i < 3; i++) if (field(obx[i], 1) !== String(i + 1) || field(obx[i], 2) !== types[i] || component(field(obx[i], 3), 1) !== C.metadata_loincs[i] || component(field(obx[i], 3), 3) !== "LN") add("STYLE-002", `OBX[${i + 1}]`, obx[i].line, "Metadata OBX is invalid.");
      if (reportStyle === "CAP eCP" && (!ECP.test(component(field(obx[1], 5), 1)) || component(field(obx[1], 5), 3) !== "CAPECP")) add("ECP-001", "OBX[2]-5", obx[1].line, "Template identifier is invalid.");
    }
    function obx4(obx, reportStyle) {
      const seen = {};
      obx.forEach(s => { const code = component(field(s, 3), 1), key = code + "|" + component(field(s, 3), 3); if (code) seen[key] = (seen[key] || 0) + 1; });
      obx.forEach(s => { const code = component(field(s, 3), 1), key = code + "|" + component(field(s, 3), 3);
        if (code && seen[key] > 1 && !field(s, 4) && !C.metadata_loincs.includes(code)) add("OBX4-001", "OBX-4", s.line, "Repeated identifier lacks OBX-4.");
        if (field(s, 4) && reportStyle !== "CAP eCP" && !/^\d+(?:\.\d+)*$/.test(field(s, 4))) add("OBX4-001", "OBX-4", s.line, "OBX-4 dot notation is invalid.");
      });
    }
    function ecp(content) {
      const repeats = {}, priorAnswers = new Set();
      content.forEach(s => { const q = component(field(s, 3), 1), qm = q.match(ECP);
        if (!qm) add("ECP-001", "OBX-3.1", s.line, "Question Ckey is invalid.");
        else if (qm[2]) { if (!repeats[qm[1]]) repeats[qm[1]] = new Set(); repeats[qm[1]].add(+qm[2]); if (component(field(s, 3), 3) !== "CAPECP.RPT" || component(field(s, 3), 7) !== qm[1] || component(field(s, 3), 9) !== "CAPECP") add("ECP-002", "OBX-3", s.line, "Repeated question metadata is invalid."); }
        else if (component(field(s, 3), 3) !== "CAPECP") add("ECP-001", "OBX-3.3", s.line, "Question coding system is invalid.");
        if (field(s, 2) === "CWE") { const a = component(field(s, 5), 1), am = a.match(ECP);
          if (!am) add("ECP-001", "OBX-5.1", s.line, "Answer Ckey is invalid.");
          else { if (am[2] && (component(field(s, 5), 3) !== "CAPECP.RPT" || component(field(s, 5), 7) !== am[1] || component(field(s, 5), 9) !== "CAPECP")) add("ECP-002", "OBX-5", s.line, "Repeated answer metadata is invalid.");
            else if (!am[2] && component(field(s, 5), 3) !== "CAPECP") add("ECP-001", "OBX-5.3", s.line, "Answer coding system is invalid."); priorAnswers.add(a); }
        }
        const link = field(s, 4); if (link) { const bare = link.startsWith("+") ? link.slice(1) : link;
          if (!ECP.test(bare)) add("ECP-003", "OBX-4", s.line, "Link syntax is invalid."); else if (!link.startsWith("+") && !priorAnswers.has(bare)) add("ECP-003", "OBX-4", s.line, "Bare LIR link has no prior answer."); }
      });
      Object.values(repeats).forEach(numbers => { const max = Math.max(...numbers); if (numbers.size !== max || [...Array(max)].some((_, i) => !numbers.has(i + 1))) add("ECP-002", "OBX-3.1", content.length ? content[0].line : null, "Repeat suffixes are not contiguous."); });
    }
    function spmTerms(spm) { spm.forEach(s => { if (field(s, 9)) field(s, 9).split("~").forEach(rep => { if (component(rep, 3) === "SCT" && !C.spm9_laterality.includes(component(rep, 1))) add("SPM9-001", "SPM-9", s.line, "Laterality is outside the enumerated set."); }); }); }

    findings.sort((a, b) => (a.line_number || 0) - (b.line_number || 0) || a.rule_id.localeCompare(b.rule_id) || a.location.localeCompare(b.location));
    const counts = { error: 0, warning: 0, information: 0 }; findings.forEach(f => counts[f.severity]++);
    const uniqueStyles = [...new Set(styles)];
    return { schema_version: CATALOG.schema_version, ruleset_version: CATALOG.ruleset_version, profile: CATALOG.profile,
      detected_report_style: uniqueStyles.length === 1 ? uniqueStyles[0] : uniqueStyles.length ? "mixed: " + uniqueStyles.join(", ") : "not detected",
      valid: counts.error === 0, counts, findings, coverage_notices: CATALOG.coverage_notices.slice() };
  }

  return { normalizeMessage, parseSegments, field, component, classifyReportStyle, validateMessage };
});
