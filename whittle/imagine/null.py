"""
The backend that is configured, and what to do about it.

NOT A STUB. This is what whittle ships with, and the only useful thing it
can do is say exactly what is missing and what turning it on would cost -
because the alternative, silently falling back to composing primitives, is
how somebody ends up with a block and no idea why.
"""

from __future__ import annotations

from pathlib import Path

from whittle.imagine.base import Imagined, ImagineUnavailable


class NullImaginer:
    """Refuses, with instructions."""

    name = "null"

    def imagine(self, prompt: str, out_dir: Path, *,
                seed: int | None = None) -> Imagined:
        raise ImagineUnavailable(
            "whittle has no text-to-mesh backend configured, so %r can only "
            "be built if a template covers it or the operations can compose "
            "it.\n"
            "\n"
            "WHAT THIS WOULD ADD: a mesh for anything at all, the way "
            "meshy.ai does - approximate, dimensionless, and a starting "
            "point rather than a finished part. whittle would then run its "
            "own fitters over it, and a shape that turns out to be turned or "
            "extruded becomes an editable spec like any other part.\n"
            "\n"
            "WHAT IT COSTS: an open text-to-3D model and its weights, and a "
            "GPU to run them in less than several minutes. Set [imagine] "
            "backend in config once one is installed.\n"
            "\n"
            "WHAT IS BETTER WITHOUT IT: anything a template covers. A "
            "generated mesh has no dimensions anybody chose and cannot be "
            "asked to make the slot 12 mm." % prompt
        )
