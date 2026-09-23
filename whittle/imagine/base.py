"""
The seam between a sentence and a mesh, and what it is allowed to claim.

Deliberately the same shape as whittle/reconstruct/base.py, because it is
the same kind of thing arriving from the same kind of place: a neural
network's guess at an object, dimensionless, unverified, and useful only
once the geometry side of the house has had a look at it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable


class ImagineError(RuntimeError):
    """A sentence could not be turned into a mesh. The message says why."""


class ImagineUnavailable(ImagineError):
    """
    No backend is installed or configured.

    ITS OWN CLASS, so a caller can tell "you have not set this up" from "it
    tried and failed". The first is a setting; the second is a bad night.
    """


@dataclass
class Imagined:
    """
    What came out of a sentence, and how much to trust it.

    EVERY FIELD IS HONEST ABOUT THE UNITS. A generated mesh is dimensionless
    until somebody supplies a real measurement - there is no camera, no
    reference object and no scale in a sentence - so `scale_mm_per_unit`
    stays None and `extent` is in whatever the network produced. Nothing here
    invents a millimetre.
    """

    mesh_path: Path
    prompt: str
    backend: str
    model: str = ""
    seconds: float = 0.0

    triangles: int = 0
    watertight: bool | None = None
    bodies: int = 0

    extent: tuple[float, float, float] = (0.0, 0.0, 0.0)
    scale_mm_per_unit: float | None = None
    scale_source: str = ""

    # SET ONLY BY THE GEOMETRY SIDE, never by a backend. A network cannot
    # tell you whether its own output prints.
    printable: bool = False
    problems: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def has_scale(self) -> bool:
        return self.scale_mm_per_unit is not None

    def extent_mm(self) -> tuple[float, float, float] | None:
        """The size in millimetres, or None while the scale is unknown."""
        if self.scale_mm_per_unit is None:
            return None
        k = self.scale_mm_per_unit
        return (self.extent[0] * k, self.extent[1] * k, self.extent[2] * k)


@runtime_checkable
class Imaginer(Protocol):
    """
    What every text-to-mesh backend must do.

    ONE METHOD, and it writes a file rather than returning geometry: the
    meshes involved are large, the next stage reads them off disk anyway
    (whittle/imports.py takes a path), and a backend that streams vertices
    into memory is one that cannot be swapped for a subprocess.
    """

    name: str

    def imagine(self, prompt: str, out_dir: Path, *,
                seed: int | None = None) -> Imagined:
        """Turn a sentence into a mesh on disk, or raise ImagineError."""
        ...
