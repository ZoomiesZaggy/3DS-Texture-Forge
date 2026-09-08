"""Output writers: PNG, manifest, contact sheet, pack builder, reports.

Splits v1's `output.py` (mixed concerns), `contact_sheet.py`, `pack_builder.py`
into single-purpose modules. The pipeline imports each as needed.

Public surface:
    save_png(rgba, path, *, alpha_aware=True) -> bool
    write_manifest(path, manifest_dict) -> None
    write_failures(path, failures) -> None
    write_summary(path, summary) -> None
    generate_contact_sheet(records, output_dir) -> str
    build_pack(output_dir, title_id, records, mode) -> str
"""

from tex_forge.output.png_writer import save_png            # noqa: F401
from tex_forge.output.manifest import (                     # noqa: F401
    write_manifest, write_failures, write_summary,
    write_unknowns, make_record,
)
from tex_forge.output.contact_sheet import generate_contact_sheet  # noqa: F401
from tex_forge.output.pack_builder import build_pack        # noqa: F401
from tex_forge.output.filenames import (                    # noqa: F401
    generate_filename, build_output_path, sanitise_subdir,
)
from tex_forge.output.reports import write_quality_report   # noqa: F401

__all__ = [
    "save_png",
    "write_manifest", "write_failures", "write_summary", "write_unknowns",
    "make_record",
    "generate_contact_sheet",
    "build_pack",
    "generate_filename", "build_output_path", "sanitise_subdir",
    "write_quality_report",
]
