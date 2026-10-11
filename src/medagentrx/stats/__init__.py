# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""Statistics core: AUROC, bootstrap, calibration, net benefit and error control.

Every function works in float64, takes explicit seeds where randomness is
involved, and raises ``StatsError`` rather than returning NaN.
"""
