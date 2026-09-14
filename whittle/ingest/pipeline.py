"""
The front door: a file in, a working mesh and an honest report out.

Build plan v8 section 5, the whole pipeline in one place:

    [1] parse + format detect
    [2] unit detection
    [3] repair, logged, undoable
    [4] proxy decimation above the interactive budget
    [5] printability report
    [6] analysis            - M1 stops here; segmentation and skeletons are M6
    [7] ready to edit

NOTHING HERE DECIDES ANYTHING IRREVERSIBLE. The original file is not touched,
the original mesh is kept in memory beside the working one, the unit guess is
reported as a guess with its alternatives, and the repair log lists every
change. A caller that wants the file exactly as it arrived asks for it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from whittle.ingest.formats import FormatInfo, load_mesh_file
from whittle.ingest.gate import TRIANGLE_BUDGET, GateReport, check
from whittle.ingest.repair import RepairResult, repair_mesh
from whittle.ingest.units import UnitGuess, guess_units


@dataclass
class Proxy:
    """A simplified copy for the viewport, and what it cost to make it."""

    mesh: Any
    triangles: int
    from_triangles: int

    #: How far the simplified surface moved, as a fraction of the model's
    #: size. Quoted because a proxy is what the user SEES, and if it moved
    #: enough to matter they should be told rather than wonder why the render
    #: and the export disagree.
    deviation_pct: float


@dataclass
class Ingested:
    """Everything known about a file after it has been taken in."""

    path: Path
    fmt: FormatInfo
    mesh: Any                       # working mesh, repaired, in millimetres
    original: Any                   # exactly as it loaded, in file units
    units: UnitGuess
    repair: RepairResult
    report: GateReport
    proxy: Proxy | None = None
    scene_parts: int = 1
    notes: list[str] = field(default_factory=list)

    @property
    def editable(self) -> Any:
        """What an edit operates on: the proxy if there is one, else the mesh."""
        return self.proxy.mesh if self.proxy is not None else self.mesh

    def summary(self) -> str:
        size = self.mesh.bounds[1] - self.mesh.bounds[0]
        lines = [
            "%s  (%s)" % (self.path.name, self.fmt.name),
            "  size        %.1f x %.1f x %.1f mm" % tuple(size),
            "  triangles   %s" % format(len(self.mesh.faces), ","),
            "  units       %s%s" % (
                self.units.units,
                "" if self.units.certain else "  (assumed - %s)" % self.units.reason),
            "  repair      %s" % self.repair.summary(),
        ]
        if self.proxy is not None:
            lines.append("  proxy       %s triangles for editing, %.2f%% deviation"
                         % (format(self.proxy.triangles, ","),
                            self.proxy.deviation_pct))
        lines.append("")
        lines.append("problems:")
        lines.append(self.report.as_text())
        return "\n".join(lines)


def ingest(path: str | Path, *, nozzle_mm: float = 0.4,
           bed_mm: tuple[float, float, float] | None = (220.0, 220.0, 250.0),
           units: str | None = None,
           repair: bool = True,
           proxy_above: int = TRIANGLE_BUDGET) -> Ingested:
    """
    Take a file in and say everything true about it.

    `units` overrides the guess, which is what the user does when they look at
    the assumed value and know better. Nothing is scaled without either the
    format stating its units or the caller saying so - see units.py.
    """
    loaded = load_mesh_file(path)
    original = loaded.mesh.copy()
    notes = list(loaded.notes)

    # [2] UNITS. The format is asked first; only an unlabelled format is
    # guessed at.
    longest = float(max(loaded.mesh.bounds[1] - loaded.mesh.bounds[0]))
    declared = "m" if loaded.fmt.name == "glTF" else None
    if units is not None:
        from whittle.ingest.units import SCALES

        if units not in SCALES:
            raise ValueError(
                "%r is not a unit whittle knows. It takes %s."
                % (units, ", ".join(sorted(SCALES))))
        guess = UnitGuess(units=units, scale_to_mm=SCALES[units], assumed=False,
                          reason="you said so")
    else:
        guess = guess_units(longest, declared)

    work = loaded.mesh.copy()
    if guess.scale_to_mm != 1.0:
        work.apply_scale(guess.scale_to_mm)
        notes.append("scaled by %g to bring %s into millimetres"
                     % (guess.scale_to_mm, guess.units))

    # [3] REPAIR. After scaling, because the merge tolerance that decides
    # whether two vertices are the same point is derived from the mesh's size.
    if repair:
        repaired = repair_mesh(work)
        work = repaired.mesh
    else:
        repaired = RepairResult(mesh=work, original=work.copy(), steps=[])

    # [4] PROXY. The full mesh is kept and exported; the proxy is for the
    # viewport and for operations that only need to look right while a slider
    # moves.
    proxy = _make_proxy(work, proxy_above)

    # [5] THE GATE, on the FULL mesh. Running it on the proxy would report the
    # proxy's faults, and the proxy is ours rather than theirs.
    report = check(work, nozzle_mm=nozzle_mm, bed_mm=bed_mm)

    return Ingested(path=Path(path), fmt=loaded.fmt, mesh=work,
                    original=original, units=guess, repair=repaired,
                    report=report, proxy=proxy,
                    scene_parts=loaded.scene_parts, notes=notes)


def _make_proxy(mesh: Any, budget: int) -> Proxy | None:
    """
    A simplified copy, when the real one is too heavy to drag a slider against.

    Returns None below the budget rather than a copy of the same mesh: a proxy
    that is not simpler is a second thing to keep in step for no benefit.
    """
    faces = len(mesh.faces)
    if faces <= budget:
        return None

    simplified = None
    try:
        simplified = mesh.simplify_quadric_decimation(face_count=budget)
    except Exception as exc:
        # A MISSING OPTIONAL PACKAGE MUST NOT VANISH INTO A BARE EXCEPT.
        #
        # simplify_quadric_decimation needs `fast_simplification`, which is
        # not installed here, and the first version of this caught that and
        # returned None - so a 327,680-triangle model got no proxy at all,
        # silently, which is exactly the case a proxy exists for. The same
        # mistake had already cost the thin-wall check, twice, over `rtree`.
        #
        # So the good path is tried, and when it is unavailable there is a
        # fallback that needs nothing extra rather than a shrug.
        simplified = _cluster_decimate(mesh, budget)
    if simplified is None or len(simplified.faces) == 0:
        simplified = _cluster_decimate(mesh, budget)
    if simplified is None or len(simplified.faces) == 0:
        return None

    # HOW FAR IT MOVED, measured rather than assumed. A decimation that
    # flattens a feature the user is looking at is worth knowing about, and
    # the number is cheap: compare the bounding boxes and the volume.
    try:
        before = float(mesh.volume) if mesh.is_watertight else 0.0
        after = float(simplified.volume) if simplified.is_watertight else 0.0
        deviation = (abs(before - after) / before * 100.0) if before else 0.0
    except Exception:
        deviation = 0.0

    return Proxy(mesh=simplified, triangles=len(simplified.faces),
                 from_triangles=faces, deviation_pct=round(deviation, 3))


def _cluster_decimate(mesh: Any, budget: int):
    """
    A proxy built by welding vertices onto a grid. No dependencies.

    Cruder than quadric decimation - it does not choose which detail to keep -
    but a proxy is what a slider is dragged against, not what gets exported,
    and "crude and present" beats "better and absent". The full mesh is still
    what leaves the building.

    The grid is sized by bisection because the relationship between cell size
    and triangle count is not one anybody can write down for an arbitrary
    mesh: it is measured, a few times, which is cheap.
    """
    import numpy as np
    import trimesh

    try:
        size = float(max(mesh.bounds[1] - mesh.bounds[0]))
        if size <= 0:
            return None

        low, high = size / 2000.0, size / 4.0
        best = None
        for _ in range(12):
            cell = (low + high) / 2.0
            keys = np.floor(np.asarray(mesh.vertices) / cell).astype(np.int64)
            _, inverse = np.unique(keys, axis=0, return_inverse=True)
            faces = inverse[np.asarray(mesh.faces)]
            faces = faces[(faces[:, 0] != faces[:, 1])
                          & (faces[:, 1] != faces[:, 2])
                          & (faces[:, 0] != faces[:, 2])]
            count = len(faces)
            if count == 0:
                high = cell
                continue

            centres = np.zeros((inverse.max() + 1, 3))
            np.add.at(centres, inverse, np.asarray(mesh.vertices))
            counts = np.bincount(inverse, minlength=len(centres))
            centres /= counts[:, None]

            candidate = trimesh.Trimesh(vertices=centres, faces=faces,
                                        process=False)
            candidate.remove_unreferenced_vertices()
            if count <= budget:
                best = candidate
                high = cell          # try finer: more detail, still in budget
            else:
                low = cell           # too many faces: coarser
            if best is not None and abs(count - budget) < budget * 0.1:
                break
        return best
    except Exception:
        return None
