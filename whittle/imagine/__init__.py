"""
A sentence to a mesh, for the things no template was written for.

WHY THIS EXISTS AND WHAT IT IS NOT
----------------------------------
Every good part whittle makes comes from a template that knows what the
object IS - where a hook breaks, what angle a screen is readable at, that a
plug is not round. That is the product, and it is why a whittle bracket is
better than a downloaded one: it is correct, it is printable, and it can be
changed by asking.

It is also, by definition, only as broad as the templates somebody has
written. Ask for a gargoyle and there is no template, so the request falls
to composing primitives and comes back as a block. That is the honest limit,
and it is the one this module is about.

HOW THE OTHER SORT OF TOOL DOES IT. meshy.ai does not understand English. It
is a generative model trained on millions of 3D assets: text goes in, a
latent comes out, a mesh is reconstructed from it. It never fails to produce
something plausible for any prompt because it learned the shape of objects -
and the output is a MESH, not a model. It is approximate, frequently not
watertight, has no dimensions anybody chose, and cannot be asked to make the
slot 12 mm.

SO THIS IS A THIRD WAY IN, AND IT CHANGES NOTHING ABOUT THE OTHER TWO:

    sentence -> template -> spec -> mesh    (exact, editable: the product)
    photo    -> mesh -> spec                (whittle/reconstruct + imports)
    sentence -> mesh -> spec                (here, for everything else)

The second arrow in the last two is the SAME code - whittle/imports.py, the
revolve and prism fitters. A generated mesh that turns out to be a body of
revolution becomes a spec and is editable like anything else; one that does
not stays triangles and says so. That is already how an imported STL is
treated and nothing about it is new.

WHAT IT PROMISES, WHICH IS LESS THAN IT SOUNDS
-----------------------------------------------
1. NO DIMENSIONS. A generated mesh is dimensionless until somebody supplies
   a real measurement, exactly like a reconstruction from a photo. The same
   `scale_mm_per_unit` rule applies and nothing here invents one.
2. NOT PRINTABLE UNTIL CHECKED. Neural meshes are commonly open, self-
   intersecting or many-bodied. whittle's verify pass runs on it like
   anything else and is allowed to refuse it.
3. IT IS A STARTING POINT. The thing that makes it worth having is what
   happens NEXT: the fitters, the mesh edit operations, and being able to
   say "make it 40 mm wide" to something that arrived as a shape.

DEFAULT OFF, LIKE EVERY OTHER MODEL BACKEND. whittle installs and runs with
no weights, no torch and no network (rule 10), and every part in parts/ still
rebuilds from its spec. A real backend is opted into in config, and the null
one says which and why.
"""

from __future__ import annotations

from typing import Any

from whittle.imagine.base import (  # noqa: F401  (re-exported)
    Imagined,
    ImagineError,
    ImagineUnavailable,
    Imaginer,
)

#: The backends this knows how to drive.
#:
#: `null` is not a placeholder - it is the configuration this project ships
#: in, and it answers every request with what to install and why. Real ones
#: are added here against an installation that can be RUN: wiring a backend
#: from its README without ever calling it is guessing at an interface, which
#: rule 9 forbids, and a text-to-3D API that has been guessed at fails at the
#: worst possible moment - after somebody has waited for a GPU.
BACKENDS = ("null",)


def make_imaginer(cfg: Any = None, backend: str | None = None):
    """
    Build the configured text-to-mesh backend.

    An unknown name is refused BY NAME rather than falling back to null: a
    typo that silently disables a feature is worse than an error, which is
    the same rule make_reconstructor follows.
    """
    name = (backend or _configured(cfg) or "null").strip().lower()

    if name == "null":
        from whittle.imagine.null import NullImaginer

        return NullImaginer()

    raise ImagineError(
        "unknown text-to-mesh backend %r. Configured backends: %s. See "
        "[imagine] in config." % (name, ", ".join(BACKENDS))
    )


def _configured(cfg: Any) -> str | None:
    if cfg is None:
        return None
    try:
        return str((cfg.data.get("imagine") or {}).get("backend") or "") or None
    except Exception:
        return None
