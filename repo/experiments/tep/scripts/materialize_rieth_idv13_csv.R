args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 3) {
  stop("Usage: Rscript materialize_rieth_idv13_csv.R <fault_free_training.RData> <faulty_testing.RData> <output_dir>")
}

fault_free_path <- args[[1]]
faulty_path <- args[[2]]
out_dir <- args[[3]]

meta_cols <- c("faultNumber", "simulationRun", "sample")
x_cols <- c(paste0("xmeas_", 1:41), paste0("xmv_", 1:11))
expected_cols <- c(meta_cols, x_cols)

load_named_object <- function(path, object_name) {
  env <- new.env(parent = emptyenv())
  loaded <- load(path, envir = env)
  if (!(object_name %in% loaded)) {
    stop(sprintf("Expected object '%s' not found in %s. Found: %s", object_name, path, paste(loaded, collapse = ", ")))
  }
  df <- env[[object_name]]
  if (!is.data.frame(df)) stop(sprintf("Object '%s' is not a data.frame", object_name))
  if (!identical(names(df), expected_cols)) {
    stop(sprintf("Unexpected schema in %s. Expected exactly 55 columns: metadata + all 52 X variables.", path))
  }
  df
}

validate_runs <- function(df, expected_runs, expected_rows_per_run, label) {
  runs <- sort(unique(as.integer(df$simulationRun)))
  if (!identical(runs, seq_len(expected_runs))) {
    stop(sprintf("%s: expected simulationRun 1..%d", label, expected_runs))
  }
  counts <- table(as.integer(df$simulationRun))
  if (length(counts) != expected_runs || any(as.integer(counts) != expected_rows_per_run)) {
    stop(sprintf("%s: expected %d rows per run", label, expected_rows_per_run))
  }
}

write_parts <- function(df, cohort, runs_per_file, output_root) {
  dir_path <- file.path(output_root, cohort)
  dir.create(dir_path, recursive = TRUE, showWarnings = FALSE)

  run_ids <- sort(unique(as.integer(df$simulationRun)))
  starts <- seq(min(run_ids), max(run_ids), by = runs_per_file)
  manifest <- data.frame()

  for (start_run in starts) {
    end_run <- min(start_run + runs_per_file - 1, max(run_ids))
    part <- df[df$simulationRun >= start_run & df$simulationRun <= end_run, c("simulationRun", "sample", "y", x_cols)]
    part <- part[order(part$simulationRun, part$sample), ]
    file_name <- sprintf("%s_runs_%03d_%03d.csv", cohort, start_run, end_run)
    file_path <- file.path(dir_path, file_name)
    write.csv(part, file_path, row.names = FALSE, quote = FALSE, na = "")

    manifest <- rbind(manifest, data.frame(
      cohort = cohort,
      file = file.path(cohort, file_name),
      run_start = start_run,
      run_end = end_run,
      rows = nrow(part),
      x_columns = length(x_cols),
      y_columns = 1,
      stringsAsFactors = FALSE
    ))
  }

  manifest
}

dir.create(out_dir, recursive = TRUE, showWarnings = FALSE)

message("Loading fault-free training data...")
normal <- load_named_object(fault_free_path, "fault_free_training")
normal$faultNumber <- as.integer(normal$faultNumber)
normal$simulationRun <- as.integer(normal$simulationRun)
normal$sample <- as.integer(normal$sample)
if (any(normal$faultNumber != 0L)) stop("Fault-free training data contains non-zero faultNumber values")
validate_runs(normal, expected_runs = 500L, expected_rows_per_run = 500L, label = "fault_free_training")
normal$y <- 0L
normal <- normal[, c(meta_cols, "y", x_cols)]

message("Loading faulty testing data...")
faulty_env <- new.env(parent = emptyenv())
loaded <- load(faulty_path, envir = faulty_env)
if (!("faulty_testing" %in% loaded)) {
  stop(sprintf("Expected object 'faulty_testing' not found. Found: %s", paste(loaded, collapse = ", ")))
}
faulty <- faulty_env[["faulty_testing"]]
if (!is.data.frame(faulty) || !identical(names(faulty), expected_cols)) {
  stop("Unexpected faulty_testing schema; expected metadata + all 52 X variables")
}

faulty$faultNumber <- as.integer(faulty$faultNumber)
faulty$simulationRun <- as.integer(faulty$simulationRun)
faulty$sample <- as.integer(faulty$sample)

message("Filtering IDV(13)...")
idv13 <- faulty[faulty$faultNumber == 13L, ]
rm(faulty, faulty_env)
gc()

if (nrow(idv13) == 0L) stop("No rows found for faultNumber = 13")
validate_runs(idv13, expected_runs = 500L, expected_rows_per_run = 960L, label = "IDV13 testing")

# Ground-truth evaluation label only. It is never part of detector X.
# Methodological correction approved for pre-formal materialization:
# the previous rule used sample >= 160 and was off by one for a 1-based
# sample index with 160 normal samples. Samples 1..160 are normal and the
# first post-fault sample is 161.
idv13$y <- as.integer(idv13$sample >= 161L)
idv13 <- idv13[, c(meta_cols, "y", x_cols)]

message("Writing CSV parts...")
normal_manifest <- write_parts(normal, "normal_reference", runs_per_file = 50L, output_root = out_dir)
rm(normal)
gc()
idv13_manifest <- write_parts(idv13, "idv13_test", runs_per_file = 50L, output_root = out_dir)
rm(idv13)
gc()

manifest <- rbind(normal_manifest, idv13_manifest)
write.csv(manifest, file.path(out_dir, "manifest.csv"), row.names = FALSE, quote = FALSE)

schema <- c(
  "CSV materialization of Rieth et al. TEP data for the focal IDV(13) experiment.",
  "Each data file contains: simulationRun, sample, y, then all 52 process variables.",
  "X = xmeas_1..xmeas_41 + xmv_1..xmv_11 (52 columns, no feature selection).",
  "y = 0 for all normal-reference rows; for IDV(13), y = 0 for sample 1..160 and y = 1 for sample 161..960.",
  "Temporal correction: the previous materializer used sample >= 160; this was an off-by-one for the approved 1-based convention and was changed to sample >= 161.",
  "faultNumber is used only to filter IDV(13) and is intentionally omitted from the materialized detector datasets.",
  "simulationRun and sample are metadata and are not detector features.",
  "Normal reference: 500 runs x 500 samples = 250000 rows.",
  "IDV(13) test: 500 runs x 960 samples = 480000 rows.",
  "No rows are downsampled and no X variable is removed."
)
writeLines(schema, file.path(out_dir, "README.txt"))

cat(sprintf("normal_rows=%d\n", sum(normal_manifest$rows)))
cat(sprintf("idv13_rows=%d\n", sum(idv13_manifest$rows)))
cat(sprintf("x_columns=%d\n", length(x_cols)))
cat("y_columns=1\n")
