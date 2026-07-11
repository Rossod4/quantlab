"""Hand-computed parity fixtures for the M02b as-of adjustment replay
(src/quantlab/data/adjustment.py) - the binding condition recorded in
plans/state/M02/VERDICT.md carried item 1. Every expected value here is
computed by hand from the CRSP-style formula documented in adjustment.py's
module docstring, to 1e-12 (packet acceptance criterion 2).
"""

from __future__ import annotations

import pandas as pd
import pytest

from quantlab.core.requirements import DataRequirements  # noqa: F401  (see below - not used)
