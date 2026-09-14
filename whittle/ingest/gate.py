"""
The printability gate: everything wrong with this file, before anyone edits it.

Build plan v8 section 10, run at ingest (section 5 step 5). The plan calls it
"the first impression and it is free value" - tell the user this has three
non-manifold edges, a 0.6 mm wall that will not print on their nozzle, no flat
base and is 40 mm too tall for their bed, before they have changed anything.

EVERY FINDING NAMES THE RULE, THE MEASURED VALUE AND THE WAY OUT
-----------------------------------------------------------------
"Wall thickness 0.62 mm is below the 0.80 mm minimum for a 0.40 mm nozzle" is
a finding. "Thin walls detected" is a complaint. The plan is explicit about
which of those to write, and the copy rule everywhere else in this repo
already says the same thing.

WHAT IS REUSED RATHER THAN REWRITTEN
-------------------------------------
whittle/verify already checks meshes, beds, overhangs and feature sizes, against
the same config, and CLAUDE.md 30 says to port and generalise rather than
rewrite. So mesh integrity comes from verify.mesh, the bed from verify.bed and
overhangs from verify.overhang. What is added here is what those do not cover
because they were written for parts whittle BUILT, where the question never
arises: debris shells, a flat base, a triangle budget, and wall thickness
measured by inscribed spheres, because an imported mesh has no spec to read
it from.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: A shell smaller than this fraction of the biggest one is debris rather than
#: a part of the model. Generated meshes are full of them - stray triangles
#: left behind by the generator that print as specks glued to the object.
#: Calibrated on a 0.4 mm speck beside a 60 mm body, which is 0.7% and was
#: missed at the first threshold of 0.5%.
DEBRIS_FRACTION = 0.02

#: Above this the viewport stops being interactive and every operation gets
#: slow. v8 section 5 step 4 puts the proxy threshold at about here.
TRIANGLE_BUDGET = 300_000

#: How flat, and how much of the footprint, counts as a base it can stand on.
BASE_FLATNESS_MM = 0.2
BASE_MIN_FRACTION = 0.02


@dataclass
class Finding:
    """One thing wrong, or worth knowing, about the model."""

    #: "fail" stops a good print. "warn" is worth knowing and sometimes fine -
    #: needing support is the example, plenty of good models do.
    severity: str
    rule: str                       # what was checked
    detail: str                     # measured value and why it matters
    fix: str = ""                   # the operation that resolves it
    value: float | None = None

    def __str__(self) -> str:
        out = "%s: %s" % (self.rule, self.detail)
        return out + ("  -> %s" % self.fix if self.fix else "")


@dataclass
class GateReport:
    """Everything the gate found, and the measurements behind it."""

    findings: list[Finding] = field(default_factory=list)
    measurements: dict[str, Any] = field(default_factory=dict)

    @property
    def failures(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "fail"]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "warn"]

    @property
    def printable(self) -> bool:
        return not self.failures

    def add(self, severity: str, rule: str, detail: str, fix: str = "",
            value: float | None = None) -> None:
        self.findings.append(Finding(severity, rule, detail, fix, value))

    def as_text(self) -> str:
        if not self.findings:
            return "no problems found"
        lines = []
        for finding in self.failures + self.warnings:
            lines.append("  [%s] %s" % (finding.severity.upper(), finding))
        return "\n".join(lines)


def check(mesh: Any, *, nozzle_mm: float, bed_mm: tuple[float, float, float] | None,
          print_axis: str = "z") -> GateReport:
    """
    Run the gate over a mesh that is already in millimetres.

    `nozzle_mm` and `bed_mm` come from the machine's config. They are passed in
    rather than read here because the gate has to be runnable against a bed the
    user typed into the web app as much as against the one in config.
    """
    import numpy as np

    report = GateReport()
    extents = tuple(float(v) for v in (mesh.bounds[1] - mesh.bounds[0]))
    report.measurements.update({
        "extents_mm": extents,
        "triangles": int(len(mesh.faces)),
        "watertight": bool(mesh.is_watertight),
    })

    _check_integrity(mesh, report)
    _check_debris(mesh, report)
    _check_size(mesh, extents, bed_mm, report)
    _check_base(mesh, print_axis, report)
    _check_overhang(mesh, print_axis, report)
    _check_walls(mesh, nozzle_mm, report)
    _check_budget(mesh, report)
    return report


def _check_integrity(mesh, report: GateReport) -> None:
    """Manifold, watertight, wound the same way, no dead triangles."""
    from whittle.verify.mesh import report_for

    mesh_report = report_for(mesh)
    report.measurements["bodies"] = int(mesh_report.body_count)

    if not mesh_report.watertight:
        report.add(
            "fail", "watertight",
            "the surface has gaps in it, so the model has no inside. Wall "
            "thickness and hollowing cannot be computed from it and most "
            "slicers will guess.",
            fix="repair - this is usually duplicate vertices rather than real "
                "holes")
    elif not mesh_report.is_volume:
        report.add(
            "fail", "solid",
            "sealed but the surface crosses itself, so it encloses no "
            "well-defined solid. Slicers resolve this differently and some "
            "produce a mess.",
            fix="no automatic fix - the overlap has to be resolved by hand or "
                "by re-exporting from the source")

    if not mesh_report.winding_consistent:
        report.add(
            "fail", "face direction",
            "faces disagree about which side is outside, which some slicers "
            "print inside out and others do not",
            fix="repair")

    if mesh_report.degenerate_faces:
        report.add(
            "warn", "dead triangles",
            "%d triangles have no area. They describe nothing and leave the "
            "mesh looking open." % mesh_report.degenerate_faces,
            fix="repair", value=float(mesh_report.degenerate_faces))


def _check_debris(mesh, report: GateReport) -> None:
    """
    Disconnected specks, which generated meshes are full of.

    v8 section 6 singles this out: invisible until the print fails, or until
    a speck of plastic turns up welded to the model. A shell that is a
    thousandth of the volume of the main one is not part of the design.
    """
    try:
        shells = mesh.split(only_watertight=False)
    except Exception:
        return
    if len(shells) <= 1:
        report.measurements["shells"] = len(shells)
        return

    sizes = []
    for shell in shells:
        try:
            extent = float(max(shell.bounds[1] - shell.bounds[0]))
        except Exception:
            extent = 0.0
        sizes.append(extent)
    biggest = max(sizes) if sizes else 0.0
    debris = [s for s in sizes if biggest > 0 and s / biggest < DEBRIS_FRACTION]

    report.measurements["shells"] = len(shells)
    report.measurements["debris_shells"] = len(debris)

    if debris:
        report.add(
            "warn", "loose fragments",
            "%d disconnected pieces are under %.1f%% the size of the model - "
            "the largest is %.2f mm across. These print as specks stuck to "
            "the object." % (len(debris), DEBRIS_FRACTION * 100,
                             max(debris) if debris else 0.0),
            fix="remove_floaters", value=float(len(debris)))
    elif len(shells) > 1:
        report.add(
            "warn", "separate bodies",
            "%d separate pieces, none of them small enough to be debris. If "
            "this is meant to be one object something is not joined; if it "
            "moves, that is what it should look like." % len(shells),
            value=float(len(shells)))


def _check_size(mesh, extents, bed_mm, report: GateReport) -> None:
    """
    Does it fit the bed, and if not by how much.

    THE PIECES ARE PASSED IN, and that is the difference between "impossible"
    and "print it in two goes". check_bed says so in its own docstring and
    takes `body_sizes` for exactly this - and this call was not giving them,
    so a model that had just been CUT to fit the bed still failed the bed
    check on its overall bounding box. Two 150 mm halves of a 300 mm model sit
    where they were cut, so the box around both is still 300.
    """
    if not bed_mm:
        return
    from whittle.verify.bed import check_bed

    sizes = []
    try:
        for piece in mesh.split(only_watertight=False):
            span = piece.bounds[1] - piece.bounds[0]
            sizes.append((float(span[0]), float(span[1]), float(span[2])))
    except Exception:
        sizes = []

    bed = check_bed(tuple(extents), tuple(bed_mm),
                    body_sizes=sizes if len(sizes) > 1 else None)
    report.measurements["bed_mm"] = tuple(float(v) for v in bed_mm)
    for problem in getattr(bed, "problems", []):
        report.add("fail", "bed size", problem,
                   fix="cut_plane to split it, or scale_uniform to shrink it")
    for warning in getattr(bed, "warnings", []):
        report.add("warn", "bed size", warning)


def _check_base(mesh, print_axis: str, report: GateReport) -> None:
    """
    Is there a flat face to stand it on?

    A generated model almost never has one - it was made to be looked at, not
    printed - and without it the first layer is a few points of contact and
    the print comes off the bed.
    """
    import numpy as np

    axis = {"x": 0, "y": 1, "z": 2}.get(print_axis, 2)
    try:
        floor = float(mesh.bounds[0][axis])
        # Triangles whose lowest point is at the floor and which lie flat.
        normals = mesh.face_normals
        down = normals[:, axis] < -0.99
        lowest = mesh.triangles[:, :, axis].max(axis=1)
        flat_on_floor = down & (lowest <= floor + BASE_FLATNESS_MM)
        area = float(mesh.area_faces[flat_on_floor].sum())
        footprint = 1.0
        span = mesh.bounds[1] - mesh.bounds[0]
        others = [i for i in range(3) if i != axis]
        footprint = float(span[others[0]] * span[others[1]]) or 1.0
        fraction = area / footprint
    except Exception:
        return

    report.measurements["base_area_mm2"] = round(area, 2)
    report.measurements["base_fraction"] = round(fraction, 4)

    if fraction < BASE_MIN_FRACTION:
        report.add(
            "warn", "flat base",
            "only %.1f mm2 of the bottom is flat, %.1f%% of the footprint. "
            "There is almost nothing holding it to the bed."
            % (area, fraction * 100),
            fix="flatten_base to cut one, or auto_orient to find a better "
                "side to stand it on",
            value=round(fraction, 4))


def _check_overhang(mesh, print_axis: str, report: GateReport) -> None:
    """Flagged, never blocked - v8 section 10. Plenty of good models need support."""
    from whittle.verify.overhang import overhang_report

    try:
        over = overhang_report(mesh, print_axis=print_axis)
    except Exception:
        return

    report.measurements["worst_overhang_deg"] = round(
        float(over.worst_overhang_deg), 1)
    report.measurements["unsupported_mm2"] = round(
        float(over.unsupported_area_mm2), 1)

    if over.supports_needed:
        report.add(
            "warn", "overhangs",
            "%.0f mm2 of the underside falls away steeper than %.0f degrees "
            "with nothing under it, worst %.1f degrees. It will need support."
            % (over.unsupported_area_mm2, over.max_deg,
               over.worst_overhang_deg),
            fix="auto_orient may find a side that needs less",
            value=round(float(over.unsupported_area_mm2), 1))


#: TWO BANDS, BECAUSE A SMALL INSCRIBED SPHERE NEAR A CONVEX EDGE IS TRUE.
#:
#: Approach the edge of a solid cube and the largest sphere that touches the
#: surface there really does shrink to nothing - that is what the medial axis
#: of a cube looks like, not a defect in the measurement. So a solid object
#: always reads a few percent "thin" and no filtering removes it: discarding
#: probes whose neighbours disagree about the normal moved a cube from 7.08%
#: to 7.06%.
#:
#: Measured on controls whose answer is known. Solid: sphere 0.0%, cylinder
#: 4.0%, cone 6.7%, cube 7.1%. Thin: a 0.6 mm slab 99%, a sphere with a 0.6 mm
#: fin 13.7%. So anything under a tenth is indistinguishable from a solid
#: object, and past four tenths the model is mostly thinner than the nozzle.
THIN_SURFACE_WARN = 0.10
THIN_SURFACE_FAIL = 0.40


def measure_thickness(mesh: Any, samples: int = 40000, probes: int = 6000,
                      iterations: int = 30):
    """
    How thick the model is at a few thousand points on its surface.

    THE SHRINKING BALL. At each sample point, grow the largest sphere that
    touches the surface there and contains no other part of the surface. For a
    slab that sphere is exactly half the thickness, so twice its radius IS the
    wall. Validated against solids whose answer is known: a 0.6 mm slab
    measures 0.63, a 2.0 mm slab measures 2.01.

    WHY NOT RAY CASTING, WHICH IS THE OBVIOUS WAY. trimesh's ray engine and its
    proximity queries both need `rtree`, which is not installed here, and the
    first version of this check caught the ImportError in a bare `except` and
    silently measured nothing at all - the gate reported no wall thickness and
    looked like it had passed. This needs only scipy's KD-tree, which is
    already a dependency.

    Returns an array of thicknesses in mm, one per probe.
    """
    import numpy as np
    import trimesh
    from scipy.spatial import cKDTree

    points, face_ids = trimesh.sample.sample_surface(mesh, samples)
    tree = cKDTree(points)

    # A FIXED SEED. The same file has to give the same answer twice, or a
    # number on screen changes when the user did nothing.
    rng = np.random.default_rng(0)
    pick = rng.choice(len(points), min(probes, len(points)), replace=False)
    origin = points[pick]
    normal = mesh.face_normals[face_ids[pick]]

    scale = float(max(mesh.bounds[1] - mesh.bounds[0]))
    too_close = scale * 0.005
    radius = np.full(len(origin), scale / 2.0)

    for _ in range(iterations):
        centre = origin - normal * radius[:, None]
        # workers=-1 SPREADS THE QUERY OVER THE CORES, and it is the whole
        # cost of this function: thirty queries measured 9.637s on one core
        # and 2.008s on all of them. Everything else here - sampling the
        # surface, building the tree - is eight milliseconds.
        distance, index = tree.query(centre, k=4, workers=-1)
        neighbour = points[index]

        # Only a point STRICTLY INSIDE the current ball can shrink it. Without
        # this guard the ball collapses onto the sample's own neighbours and
        # every convex solid reads as thin.
        inside = distance < (radius[:, None] - 1e-9)
        far_enough = np.linalg.norm(
            neighbour - origin[:, None, :], axis=2) > too_close

        span = neighbour - origin[:, None, :]
        denominator = -2.0 * np.einsum('ijk,ik->ij', span, normal)
        with np.errstate(divide='ignore', invalid='ignore'):
            candidate = np.einsum('ijk,ijk->ij', span, span) / denominator
        candidate = np.where(
            inside & far_enough & np.isfinite(candidate) & (candidate > 1e-6),
            candidate, np.inf)

        shrunk = candidate.min(axis=1)
        moved = shrunk < radius - 1e-9
        if not moved.any():
            break
        radius = np.where(moved, shrunk, radius)

    return 2.0 * radius


def _check_walls(mesh, nozzle_mm: float, report: GateReport) -> None:
    """
    The thinnest part of the model, measured rather than guessed.

    THIS IS THE ONE NOBODY ELSE TELLS THEM. A 0.6 mm fin on a 0.4 mm nozzle
    does not print - it comes out as a smear or as nothing - and it is
    invisible on screen until the print fails eight hours in. v8 section 6
    says solving this well is the clearest proof the product knows what it is
    doing.

    JUDGED ON HOW MUCH OF THE SURFACE IS THIN, not on the single thinnest
    reading. Every mesh has sharp edges, and a probe that lands on one
    measures a tiny inscribed ball truthfully and meaninglessly: a solid 12 mm
    cylinder reads 0.31 mm at its first percentile, purely from its rim. Using
    that figure would tell somebody their solid cylinder has sub-nozzle walls.

    KNOWN LIMIT, WORTH STATING: a thin feature covering less than about a
    tenth of the surface cannot be told apart from the few percent every solid
    object reads, so it is not flagged. Separating a small thin patch from the
    edges needs the thin readings to be CLUSTERED rather than counted - a
    patch is connected, edges are scattered - which is where
    `thicken_thin_walls` goes in M2.
    """
    import numpy as np

    minimum = 2.0 * nozzle_mm
    if not mesh.is_watertight:
        # An open mesh has no inside, so there is no thickness to measure. The
        # watertight failure is already reported and says as much.
        return
    try:
        thickness = measure_thickness(mesh)
    except Exception as exc:
        report.add(
            "warn", "wall thickness",
            "could not be measured on this mesh (%s), so nothing is claimed "
            "about it either way" % str(exc).split("\n")[0][:90])
        return

    if len(thickness) == 0:
        return
    fraction = float((thickness < minimum).mean())
    p5 = float(np.percentile(thickness, 5))

    report.measurements["thin_surface_fraction"] = round(fraction, 4)
    report.measurements["thickness_p5_mm"] = round(p5, 3)
    report.measurements["thickness_median_mm"] = round(
        float(np.median(thickness)), 3)

    if fraction >= THIN_SURFACE_FAIL:
        report.add(
            "fail", "wall thickness",
            "%.0f%% of the surface is thinner than the %.2f mm minimum for a "
            "%.2f mm nozzle - the thin regions measure about %.2f mm. Most of "
            "this model is thinner than the nozzle can lay down, so it prints "
            "as a smear or not at all."
            % (fraction * 100, minimum, nozzle_mm, p5),
            fix="scale_uniform to make the whole thing bigger, or "
                "thicken_thin_walls",
            value=round(p5, 3))
    elif fraction >= THIN_SURFACE_WARN:
        report.add(
            "warn", "wall thickness",
            "%.0f%% of the surface measures under the %.2f mm minimum for a "
            "%.2f mm nozzle, around %.2f mm in the thin places. Some of that "
            "is the edges of any solid shape; the rest is wall that will not "
            "print." % (fraction * 100, minimum, nozzle_mm, p5),
            fix="thicken_thin_walls", value=round(p5, 3))


def _check_budget(mesh, report: GateReport) -> None:
    """Too many triangles to work on interactively."""
    faces = len(mesh.faces)
    if faces > TRIANGLE_BUDGET:
        report.add(
            "warn", "triangle count",
            "%s triangles. Above about %s the viewport stops keeping up with "
            "a slider, so editing happens on a simplified copy and the full "
            "mesh is kept for export."
            % (format(faces, ","), format(TRIANGLE_BUDGET, ",")),
            fix="a proxy is made automatically",
            value=float(faces))
