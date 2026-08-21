# Formal Route Records

This directory stores structured, sanitized records of formal VERAS/VERSA routing when traceability or persistence is required.

Current records use `schema_version: 2.0.0` and `architecture_generation: VERAS_3`. Current route actors are PSQZA, MECAI, BANCA and the VERSA control plane. Restricted Git execution is represented as the internal VERSA capability `RESTRICTED_WRITE_EXECUTION`; it is not a persona route and requires prior BANCA write admission plus subsequent BANCA validation.

A route record may contain source and target, objective, minimum projected artifacts, frozen hashes, record identifiers, outcomes, commits, pull requests and validation results. It must not contain private model reasoning or unrecorded scratchpad content. Current records also carry an exact governance binding to the VERAS package commit/version used by the cycle.

Expected record identifiers include `orientation_id`, `orientation_decision_id`, `opinion_id`, `integrity_report_id`, `write_admission_id`, `write_execution_request_id`, execution-report identifiers and `write_validation_id`. The absence of the required identifier means the related action must not be represented as formally completed.

## Legacy traces

Records created before VERAS 3 are preserved as immutable historical provenance and explicitly marked `architecture_generation: LEGACY_PRE_VERAS_3`. They may contain roles or execution components no longer present in the current architecture. Legacy names and routes do not grant current authority and must never be copied into new route records.
