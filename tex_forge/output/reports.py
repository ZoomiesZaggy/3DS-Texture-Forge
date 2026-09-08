"""Write quality_report.{json,txt} from a list of TextureRecord-shaped dicts.

Thin wrapper around tex_forge.quality.metrics.generate_quality_report --
keeps the report-writing concern in output/ where it belongs while the
metric *computation* lives in quality/.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def write_quality_report(
    records: List[Dict[str, Any]],
    *,
    output_dir: str,
    game_name: str,
    rom_file: str,
    format_distribution: Optional[Dict[str, int]] = None,
) -> Dict[str, Any]:
    """Compute quality summary, write JSON + TXT, return the dict."""
    from tex_forge.quality.metrics import generate_quality_report
    return generate_quality_report(
        records=records,
        game_name=game_name,
        rom_file=rom_file,
        output_dir=output_dir,
        format_distribution=format_distribution,
    )
