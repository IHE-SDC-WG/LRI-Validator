# 0002: Use user-started SEER lookups with local caches

Status: accepted

## Context

Three delivery models were considered for registry reference data:

1. bundle SEER staging data in the single-file HTML;
2. download data when the page opens; or
3. query the SEER API only after the user reviews the outbound codes and starts the check.

The public staging repositories contain far more data than this small HTML artifact needs. A useful offline pack would require a maintained distillation process, and server-side disease, site-recode, and multiple-primary logic would still need separate implementations or would remain unavailable.

Downloading on page open would create network traffic before consent, transfer mostly unused data, and still require a key for API-only checks.

## Decision

Use user-started live requests to the SEER API. Cache pinned staging and NAACCR responses locally. Apply a seven-day expiry to mutable disease, site-recode, and multiple-primary responses. Keep syntax validation entirely offline.

The browser must list extracted codes before enabling a run. It keeps the key and cache in tab memory only. The CLI uses a private on-disk cache unless `--no-cache` is passed.

## Consequences

- Repeated checks of the same codes normally avoid network calls.
- Air-gapped use remains limited to syntax and local template/site checks.
- API availability and contract drift are visible as partial reports, not uncaught failures.
- The distributed HTML remains small and directly reviewable.

## Future offline pack

Reconsider a distilled offline pack when air-gapped demand justifies a versioned build pipeline, or when SEER publishes a compact artifact covering staging selection plus the server-side checks used here. The pack must preserve source attribution, deterministic builds, and explicit data-version reporting.
