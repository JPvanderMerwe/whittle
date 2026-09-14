"""
What a file is, whether we can read it, and what it costs us that it is.

Build plan v8 section 5: "Format decides capability." A STEP file carries real
topology and unlocks feature editing; an STL is triangle soup and never will.
The user is told which they have at upload, because if the model page offered
a STEP and they took the STL, saying so costs us nothing and saves them the
session.

WHAT IS ACTUALLY READABLE HERE, MEASURED RATHER THAN ASSUMED
-------------------------------------------------------------
whittle/imports.py lists `.3mf` among the formats it accepts. trimesh 5.0 cannot
read 3MF - it is not in `trimesh.available_formats()` - so that import has
never worked and fails somewhere inside the loader with whatever message the
library happens to produce. Listing a format we cannot read is worse than not
listing it: the user picks the file we told them to pick and it breaks.

So the table below is checked against the loader at import time, and a format
we cannot honour says so at the door, by name, with what to bring instead.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class UnsupportedFormat(ValueError):
    """The file is not something we can read. The message says what to do."""


@dataclass(frozen=True)
class FormatInfo:
    """One file format and what having it means for the session."""

    suffixes: tuple[str, ...]
    name: str

    #: "mesh" is triangle soup. "brep" carries real topology - faces, edges,
    #: and a feature tree we can edit properly (v8 section 9).
    topology: str

    #: Does the format itself state its units? STL does not, which is the
    #: whole reason units have to be guessed (see units.py).
    carries_units: bool

    #: Can it hold more than one body as separate objects? STL cannot - it
    #: loses the distinction, which matters for anything with moving parts.
    carries_bodies: bool

    #: What to say at upload when this is what arrived.
    advice: str = ""


FORMATS: tuple[FormatInfo, ...] = (
    FormatInfo(
        suffixes=(".stl",), name="STL", topology="mesh",
        carries_units=False, carries_bodies=False,
        advice="STL is triangles with no units and no separate bodies. If the "
               "download page offered a STEP, take that one instead - it "
               "keeps holes and faces editable.",
    ),
    FormatInfo(
        suffixes=(".glb", ".gltf"), name="glTF", topology="mesh",
        carries_units=True, carries_bodies=True,
        advice="glTF measures in metres by specification, so the numbers are "
               "scaled on the way in.",
    ),
    FormatInfo(
        suffixes=(".obj",), name="OBJ", topology="mesh",
        carries_units=False, carries_bodies=True,
    ),
    FormatInfo(
        suffixes=(".ply",), name="PLY", topology="mesh",
        carries_units=False, carries_bodies=True,
    ),
    FormatInfo(
        suffixes=(".off",), name="OFF", topology="mesh",
        carries_units=False, carries_bodies=False,
    ),
    FormatInfo(
        suffixes=(".step", ".stp"), name="STEP", topology="brep",
        carries_units=True, carries_bodies=True,
        advice="STEP carries real geometry rather than triangles, so holes, "
               "fillets and faces stay editable.",
    ),
    FormatInfo(
        suffixes=(".iges", ".igs"), name="IGES", topology="brep",
        carries_units=True, carries_bodies=True,
    ),
    FormatInfo(
        suffixes=(".brep",), name="BREP", topology="brep",
        carries_units=False, carries_bodies=True,
    ),
)

#: Formats v8 lists that this build cannot actually read, and why. Kept as data
#: rather than left out, so the refusal can name the format and suggest the way
#: round it instead of failing with a loader's internal error.
CANNOT_READ: dict[str, str] = {
    ".3mf": "3MF needs a reader this build does not have. Export the model as "
            "STL or STEP and bring that - 3MF's advantage is units and "
            "multiple bodies, and STEP carries both.",
}


def _by_suffix(suffix: str) -> FormatInfo | None:
    for info in FORMATS:
        if suffix in info.suffixes:
            return info
    return None


def detect_format(path: str | Path) -> FormatInfo:
    """
    What this file is, from its name.

    From the SUFFIX and not the contents, deliberately, and only here: this is
    the question "what did the user bring us", which is answered by what they
    called it. Whether the bytes agree is the loader's problem a moment later,
    and it says so in its own words rather than this function guessing.
    """
    suffix = Path(path).suffix.lower()
    if not suffix:
        raise UnsupportedFormat(
            "%s has no extension, so there is nothing to say what it is. "
            "Rename it with the right one - .stl, .glb, .obj, .ply or .step."
            % Path(path).name
        )

    info = _by_suffix(suffix)
    if info is not None:
        return info
    if suffix in CANNOT_READ:
        raise UnsupportedFormat(CANNOT_READ[suffix])
    raise UnsupportedFormat(
        "%s is not a format whittle reads. It takes %s."
        % (suffix, ", ".join(sorted(s for f in FORMATS for s in f.suffixes)))
    )


@dataclass
class LoadedMesh:
    """A mesh that is in memory, and everything known about how it got there."""

    mesh: Any                       # trimesh.Trimesh
    fmt: FormatInfo
    path: Path

    #: Separate objects the file held, before they were concatenated. A GLB of
    #: an articulated model arrives as several - losing that silently would
    #: throw away the one thing that says the parts move.
    scene_parts: int = 1

    notes: list[str] = field(default_factory=list)


def load_mesh_file(path: str | Path) -> LoadedMesh:
    """
    Read a file into one mesh, keeping what the container knew.

    CONCATENATED, BUT COUNTED FIRST. trimesh hands back a Scene for anything
    that held more than one object, and the usual move is to concatenate and
    carry on. That is right - the checks downstream all want one mesh - but
    the number of objects is thrown away by doing it, and for an imported
    model that number is information: several bodies is what an articulated
    or multi-part model looks like before anybody has touched it.
    """
    import trimesh

    path = Path(path)
    fmt = detect_format(path)
    if not path.is_file():
        raise UnsupportedFormat("there is no file at %s" % path)

    if fmt.topology == "brep":
        raise UnsupportedFormat(
            "%s is %s, which carries real topology and needs the B-rep path - "
            "that is milestone M7 and is not built yet. Export it as STL or "
            "GLB to work on it as a mesh today."
            % (path.name, fmt.name)
        )

    notes: list[str] = []
    try:
        loaded = trimesh.load(path, force=None)
    except Exception as exc:
        raise UnsupportedFormat(
            "%s is named %s but could not be read as one: %s"
            % (path.name, fmt.name, str(exc).split("\n")[0][:200])
        ) from exc

    parts = 1
    if isinstance(loaded, trimesh.Scene):
        geometries = list(loaded.geometry.values())
        if not geometries:
            raise UnsupportedFormat(
                "%s holds no geometry at all - it may be a scene with only "
                "cameras or lights in it." % path.name
            )
        parts = len(geometries)
        if parts > 1:
            notes.append(
                "the file held %d separate objects, joined into one to work "
                "on" % parts
            )
        loaded = trimesh.util.concatenate(geometries)

    if not hasattr(loaded, "faces") or len(loaded.faces) == 0:
        raise UnsupportedFormat(
            "%s loaded but has no triangles in it. A point cloud or a curve "
            "cannot be printed or edited here." % path.name
        )

    return LoadedMesh(mesh=loaded, fmt=fmt, path=path, scene_parts=parts,
                      notes=notes)
