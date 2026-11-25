"""Shared paths for the wre trial scripts.

Run any script from the repo root or from wre/; outputs always land in
wre/results/. The 61 MB wred sidecar lives in the Python package, not here.
"""

import os

HERE = os.path.dirname(os.path.abspath(__file__))       # wre/scripts
ROOT = os.path.dirname(HERE)                            # wre
RESULTS = os.path.join(ROOT, "results")
DATASET = os.path.join(ROOT, os.pardir, "datasets", "akamai_customers", "sites.csv")
VISUAL_DATA = os.path.join(ROOT, "report_data.js")
NULL = "NUL" if os.name == "nt" else "/dev/null"
