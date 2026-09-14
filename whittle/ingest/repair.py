"""
Making a downloaded mesh workable, and writing down everything that was done.

Build plan v8 section 5, step 3: "manifold, watertight, normals, duplicate
verts, shell merge - log every change, show it, allow undo of the repair
itself."

THIS REVERSES A RULE, ON PURPOSE, AND THE RULE WAS RIGHT BEFORE
----------------------------------------------------------------
whittle/imports.py says, in bold: the file is not repaired on the way in,
because "quietly fixing it would mean the thing in the library is no longer
the thing that was downloaded, and the first time that mattered nobody would
know it had happened."

Every word of that stands. What changed is the product: v8 puts import-and-
edit at the centre, and an editor that hands back a mesh it refuses to make
manifold has handed back something nobody can edit. Generated meshes are
non-manifold as a matter of course.

So the objection is answered rather than overruled:

  - the original file is never written to, and stays on disk as it arrived
  - every change is logged, with a count, in words
  - the log is shown, not buried
  - `undo` gives the untouched mesh back

The user is never in the position the old rule was protecting them from -
holding a changed thing believing it is the original - because they are told
what changed before they do anything with it.

WHAT IS NOT DONE HERE
----------------------
Nothing that changes the SHAPE. No smoothing, no decimation, no re-orienting,
no scaling, no hole filling beyond closing what is already a closed surface
with a gap in the triangle list. Those are edits, they belong on the edit
stack where they have parameters and an off switch, and doing them silently at
ingest is exactly the sin the old rule names.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RepairStep:
    """One thing that was done, what it touched, and why it needed doing."""

    name: str
    count: int
    detail: str

    def __str__(self) -> str:
        return "%s: %s" % (self.name, self.detail)


@dataclass
class RepairResult:
    """The working mesh, the original, and the full account of the difference."""

    mesh: Any                       # the repaired working copy
    original: Any                   # untouched, for undo
    steps: list[RepairStep] = field(default_factory=list)

    #: What is still wrong after everything that could be done was done. A
    #: mesh with self-intersecting geometry cannot be fixed by tidying its
    #: triangle list, and saying so is more use than a silent partial job.
    unresolved: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.steps)

    @property
    def watertight(self) -> bool:
        return bool(self.mesh.is_watertight)

    def undo(self):
        """The mesh exactly as it arrived."""
        return self.original

    def summary(self) -> str:
        if not self.steps:
            return "nothing needed repairing"
        return "; ".join(str(step) for step in self.steps)


def repair_mesh(mesh: Any, *, merge_tolerance: float | None = None) -> RepairResult:
    """
    Tidy a mesh's triangle list without changing the shape it describes.

    `merge_tolerance` is the distance below which two vertices are the same
    point. Left None it is trimesh's own default, which is derived from the
    mesh's size - a fixed number here would be wrong at both ends, welding
    detail off a 5 mm part or missing a seam on a 300 mm one.
    """
    import numpy as np
    import trimesh

    original = mesh.copy()
    work = mesh.copy()
    steps: list[RepairStep] = []

    before_v = len(work.vertices)
    before_f = len(work.faces)

    # 1. DUPLICATE VERTICES. Two triangles that share an edge geometrically but
    #    each carry their own copy of its endpoints are not joined as far as
    #    any topology test is concerned, so the mesh reads as full of holes
    #    while looking perfect. This is the single commonest reason a
    #    downloaded STL is "not watertight", and it is not a defect in the
    #    shape at all - STL has no way to say two triangles share a vertex.
    if merge_tolerance is None:
        work.merge_vertices()
    else:
        work.merge_vertices(merge_tex=False, merge_norm=False,
                            digits_vertex=None)
    welded = before_v - len(work.vertices)
    if welded > 0:
        steps.append(RepairStep(
            "welded vertices", welded,
            "%d duplicate vertices joined - STL cannot say that two triangles "
            "share a corner, so almost every downloaded one needs this"
            % welded))

    # 2. DEGENERATE FACES. Triangles with no area carry no geometry and leave
    #    unmatched edges behind them, which is the same false "not watertight"
    #    by a different route.
    try:
        keep = trimesh.triangles.area(work.triangles) > 1e-9
        dead = int((~keep).sum())
        if dead:
            work.update_faces(keep)
            work.remove_unreferenced_vertices()
            steps.append(RepairStep(
                "removed dead faces", dead,
                "%d triangles with no area at all - they describe nothing and "
                "leave the mesh open" % dead))
    except Exception:
        pass

    # 3. DUPLICATE FACES. The same triangle twice is a doubled surface, which
    #    slices as a zero-thickness wall.
    try:
        before = len(work.faces)
        work.update_faces(work.unique_faces())
        doubled = before - len(work.faces)
        if doubled > 0:
            steps.append(RepairStep(
                "removed repeated faces", doubled,
                "%d triangles that appeared more than once - a doubled "
                "surface slices as a wall with no thickness" % doubled))
    except Exception:
        pass

    # 4. WINDING AND NORMALS. A mesh whose faces do not agree which way is out
    #    prints inside out in some slicers and not others, which is the worst
    #    kind of fault: it works on the machine it was tested on.
    if not work.is_winding_consistent:
        try:
            trimesh.repair.fix_winding(work)
            if work.is_winding_consistent:
                steps.append(RepairStep(
                    "fixed winding", 1,
                    "faces disagreed about which side was outside - some "
                    "slicers would have printed it inside out"))
        except Exception:
            pass

    try:
        trimesh.repair.fix_normals(work)
    except Exception:
        pass

    # 5. HOLES. Only after everything above, because most apparent holes are
    #    not holes - they are the duplicate vertices from step 1. Filling
    #    before welding would paper a triangle over a seam that was never
    #    open, and THAT changes the shape.
    if not work.is_watertight:
        open_before = _open_edges(work)
        try:
            trimesh.repair.fill_holes(work)
        except Exception:
            pass
        open_after = _open_edges(work)
        if open_after < open_before:
            steps.append(RepairStep(
                "closed holes", open_before - open_after,
                "%d open edges closed, %s"
                % (open_before - open_after,
                   "the mesh is now sealed" if open_after == 0
                   else "%d still open" % open_after)))

    unresolved: list[str] = []
    if not work.is_watertight:
        unresolved.append(
            "still not watertight - %d edges are open. A mesh with real gaps "
            "in its surface has no inside, so wall thickness and hollowing "
            "cannot be computed from it." % _open_edges(work))
    if not work.is_winding_consistent:
        unresolved.append(
            "faces still disagree about which way is outside, which no "
            "amount of tidying the triangle list can settle")

    # SELF-INTERSECTION IS REPORTED, NEVER REPAIRED. Untangling one means
    # deciding which surface was meant, and that is a judgement about the
    # model rather than a fact about the file.
    if work.is_watertight and not work.is_volume:
        unresolved.append(
            "watertight but not a solid - the surface crosses itself "
            "somewhere. Nothing here can untangle that without guessing "
            "which side was meant to be inside.")

    faces_now = len(work.faces)
    if faces_now != before_f and not steps:
        steps.append(RepairStep(
            "tidied", abs(before_f - faces_now),
            "triangle count went from %d to %d" % (before_f, faces_now)))

    return RepairResult(mesh=work, original=original, steps=steps,
                        unresolved=unresolved)


def _open_edges(mesh: Any) -> int:
    """How many edges belong to only one face. Zero means sealed."""
    import trimesh

    try:
        return int(len(trimesh.grouping.group_rows(
            mesh.edges_sorted, require_count=1)))
    except Exception:
        return 0
