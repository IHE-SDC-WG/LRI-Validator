# 0001: Defer SDC-CDM adoption

Status: accepted

## Context

The validator needs stateless checks over one LRI message. SDC-CDM is a persistence model for ETL, intake, OMOP, NAACCR, and SDC data. It does not provide a validation-rule engine or a stable package boundary for a browser and CLI validator.

At review time, the project had no tagged release and was still changing its combined-model architecture. Taking a database dependency would add schema, loading, and migration work without supplying the checks needed here.

## Decision

Do not add an SDC-CDM dependency in this release. Use typed SEER API requests for public registry reference checks and keep the validator stateless apart from response caches.

## Revisit criteria

Reconsider SDC-CDM when all of the following are true:

- a stable release and compatibility policy exist;
- published mappings connect NAACCR LRI or CAP eCP content to the model;
- the model supports checks that the SEER API cannot answer; and
- adopting it does not require the single-file browser artifact to ship a database runtime.

Its NAACCR and SDC concept mappings may still be useful as reviewed source material once those conditions are met.
