"""Quality metrics: per-texture suspicion flags and aggregate quality reports.

Public:
    compute_quality_metrics(rgba, pica_format) -> dict
    generate_quality_report(records, ...) -> dict (writes JSON + TXT)
"""

from tex_forge.quality.metrics import (
    compute_quality_metrics,
    generate_quality_report,
)

__all__ = ["compute_quality_metrics", "generate_quality_report"]
