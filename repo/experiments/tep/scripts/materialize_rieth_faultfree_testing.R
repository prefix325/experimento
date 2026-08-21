args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 2) {
  stop("Usage: Rscript materialize_rieth_faultfree_testing.R <TEP_FaultFree_Testing.RData> <output_dir>")
}

source_path <- normalizePath(args[[1]], mustWork = TRUE)
output_dir <- args[[2]]

meta_cols <- c("faultNumber", "simulationRun", "sample")
x_cols <- c(paste0("xmeas_", 1:41), paste0("xmv_", 1:11))
expected_cols <- c(meta_cols, x_cols)

env <- new.env(parent = emptyenv())
loaded <- load(source_path, envir = env)
if (!identical(loaded, "fault_free_testing")) {
  stop(sprintf(
    "Expected exactly object 'fault_free_testing'; found: %s",
    paste(loaded, collapse = ", ")
  ))
}

normal <- env[["fault_free_testing"]]
if (!is.data.frame(normal)) stop("fault_free_testing is not a data.frame")
if (!identical(names(normal), expected_cols)) {
  stop("Unexpected schema; expected metadata followed by all 52 X variables")
}

normal$faultNumber <- as.integer(normal$faultNumber)
normal$simulationRun <- as.integer(normal$simulationRun)
normal$sample <- as.integer(normal$sample)

if (ncol(normal) != 55L || length(x_cols) != 52L) stop("Column-count validation failed")
if (any(normal$faultNumber != 0L)) stop("Fault-free testing contains non-zero faultNumber")
if (anyNA(normal[, x_cols])) stop("Fault-free testing contains missing X values")

runs <- sort(unique(normal$simulationRun))
if (!identical(runs, 1:500)) stop("Expected simulationRun 1..500")
counts <- table(normal$simulationRun)
if (length(counts) != 500L || any(as.integer(counts) != 960L)) {
  stop("Expected exactly 960 samples in each of 500 simulationRuns")
}

for (run_id in runs) {
  samples <- sort(normal$sample[normal$simulationRun == run_id])
  if (!identical(samples, 1:960)) {
    stop(sprintf("simulationRun %d does not contain sample 1..960 exactly", run_id))
  }
}

dir.create(output_dir, recursive = TRUE, showWarnings = FALSE)
for (start_run in seq(1L, 500L, by = 50L)) {
  end_run <- start_run + 49L
  part <- normal[
    normal$simulationRun >= start_run & normal$simulationRun <= end_run,
    c("simulationRun", "sample", x_cols)
  ]
  part <- part[order(part$simulationRun, part$sample), ]
  part$blind_run_id <- sprintf("NORMAL_HOLDOUT_%06d", part$simulationRun)
  part <- part[, c("blind_run_id", "sample", x_cols)]

  destination <- file.path(
    output_dir,
    sprintf("normal_holdout_blind_runs_%03d_%03d.csv.gz", start_run, end_run)
  )
  connection <- gzfile(destination, open = "wt", compression = 9)
  tryCatch(
    write.csv(part, connection, row.names = FALSE, quote = FALSE, na = ""),
    finally = close(connection)
  )
}

cat("object=fault_free_testing\n")
cat(sprintf("source_rows=%d\n", nrow(normal)))
cat(sprintf("source_columns=%d\n", ncol(normal)))
cat(sprintf("simulation_runs=%d\n", length(runs)))
cat("samples_per_run=960\n")
cat("sample_min=1\n")
cat("sample_max=960\n")
cat(sprintf("x_columns=%d\n", length(x_cols)))
cat("materialized_columns=blind_run_id,sample,xmeas_1..xmeas_41,xmv_1..xmv_11\n")
