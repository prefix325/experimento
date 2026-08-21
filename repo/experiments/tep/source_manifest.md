# Source manifest — TEP IDV(13)

Status: `PROVISIONAL`.

Provider: University of Washington / N. Lawrence Ricker.

Archive: `https://depts.washington.edu/control/LARRY/TE/IDVs/idv13.zip`

Format documentation: `https://depts.washington.edu/control/LARRY/TE/IDVs/format.txt`

Focal disturbance: IDV(13), described in the source archive as a slow drift in reaction kinetics.

Binary audit status: `PENDING`.

Expected data files discussed for intake are `y.dat`, `u.dat` and `r.dat`, but their presence, dimensions, column order and hashes are not considered frozen until the ZIP is directly inspected.

The raw archive must remain immutable after ingestion. Any CSV or analytical table created later must be treated as a deterministic derivative, not as the source of truth.
