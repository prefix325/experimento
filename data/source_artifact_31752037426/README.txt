CSV materialization of Rieth et al. TEP data for the focal IDV(13) experiment.
Each data file contains: simulationRun, sample, y, then all 52 process variables.
X = xmeas_1..xmeas_41 + xmv_1..xmv_11 (52 columns, no feature selection).
y = 0 for all normal-reference rows; for IDV(13), y = 0 when sample < 160 and y = 1 when sample >= 160.
faultNumber is used only to filter IDV(13) and is intentionally omitted from the materialized detector datasets.
simulationRun and sample are metadata and are not detector features.
Normal reference: 500 runs x 500 samples = 250000 rows.
IDV(13) test: 500 runs x 960 samples = 480000 rows.
No rows are downsampled and no X variable is removed.
