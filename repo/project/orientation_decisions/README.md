# Orientation decisions

This directory stores schema-valid researcher decisions on MECAI orientation records. Each JSON record binds one `orientation_id` to one researcher outcome presented through PSQZA: `APPROVED`, `PARTIALLY_APPROVED`, `REJECTED`, or `AMENDMENT_REQUIRED`.

Only approved action identifiers may appear in a downstream research delta. Rejected decisions cannot activate BANCA or produce persistence. Amendment-required decisions return to MECAI for a superseding orientation. These records authorize scientific direction only; they do not replace later material Git authorization.
