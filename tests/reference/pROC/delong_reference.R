# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
#
# Reference DeLong values from pROC for the datasets in this folder.
# Run from the repository root:
#   Rscript tests/reference/pROC/delong_reference.R
# Writes tests/reference/pROC/expected.json.

suppressPackageStartupMessages({
  library(pROC)
  library(jsonlite)
})

here <- "tests/reference/pROC"
names <- c("small", "prevalence12", "ties", "strong")
out <- list(pROC_version = as.character(packageVersion("pROC")), datasets = list())

for (name in names) {
  d <- read.csv(file.path(here, paste0(name, ".csv")))
  r1 <- roc(d$y, d$s1, levels = c(0, 1), direction = "<", quiet = TRUE)
  r2 <- roc(d$y, d$s2, levels = c(0, 1), direction = "<", quiet = TRUE)
  test <- roc.test(r1, r2, method = "delong", paired = TRUE)
  out$datasets[[name]] <- list(
    auc1 = as.numeric(auc(r1)),
    auc2 = as.numeric(auc(r2)),
    se1 = sqrt(var(r1, method = "delong")),
    se2 = sqrt(var(r2, method = "delong")),
    cov12 = cov(r1, r2, method = "delong"),
    z = unname(test$statistic)
  )
}

writeLines(toJSON(out, digits = NA, auto_unbox = TRUE, pretty = TRUE),
           file.path(here, "expected.json"))
