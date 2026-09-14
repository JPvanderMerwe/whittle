"""
Ingest: turning somebody else's file into something we can work on.

Build plan v8 section 5. This is the front door of the product, and the order
matters:

    parse -> units -> repair -> proxy -> printability report -> analysis

WHY THIS IS A NEW PACKAGE AND NOT AN EXTENSION OF imports.py
------------------------------------------------------------
whittle/imports.py exists and does a related but deliberately different job: it
files a downloaded mesh in the library exactly as it arrived, and its own
docstring is emphatic that nothing is repaired, decimated, re-oriented or
scaled on the way in, because "quietly fixing it would mean the thing in the
library is no longer the thing that was downloaded".

That rule was right for a library of downloads and it is wrong for an editor.
v8 repositions the product around import-and-edit, and an editor that refuses
to repair hands the user a mesh they cannot work on. v8 resolves the conflict
rather than ignoring it: repair happens, every change is LOGGED, the original
file is kept untouched, and the repair itself can be undone. The thing in the
library is still the thing that was downloaded - the working copy is what gets
fixed.

So the two coexist. imports.py files things. ingest prepares them for editing.
"""

from whittle.ingest.formats import (
    FORMATS,
    FormatInfo,
    LoadedMesh,
    UnsupportedFormat,
    detect_format,
    load_mesh_file,
)
from whittle.ingest.gate import Finding, GateReport, check
from whittle.ingest.pipeline import Ingested, Proxy, ingest
from whittle.ingest.repair import RepairResult, RepairStep, repair_mesh
from whittle.ingest.units import UnitGuess, guess_units

__all__ = [
    "FORMATS",
    "Finding",
    "FormatInfo",
    "GateReport",
    "Ingested",
    "LoadedMesh",
    "Proxy",
    "RepairResult",
    "RepairStep",
    "UnitGuess",
    "UnsupportedFormat",
    "check",
    "detect_format",
    "guess_units",
    "ingest",
    "load_mesh_file",
    "repair_mesh",
]
