"""
Editing sessions over HTTP. Build plan v8 milestone M4.

A project is one imported mesh plus its edit stack, held on the server while
somebody works on it. The browser sends slider moves and gets back geometry.

WHY THE STACK LIVES HERE AND NOT IN THE BROWSER
------------------------------------------------
The operations are trimesh and numpy. Porting them to JavaScript would be a
second implementation of the geometry, and this repo has a rule about that
which has already been paid for twice - the command parser and the design
tokens both live in Python precisely so two clients cannot disagree.

So the browser holds the UI and the server holds the model. What that costs is
a round trip per slider move, and what makes it affordable is the cache in
whittle/edit/stack.py: moving the last slider recomputes only the last step.

THE VIEWPORT GETS THE PROXY, THE EXPORT GETS THE MESH
------------------------------------------------------
Section 13.3 wants a slider drag to re-render live. A 300 000-triangle GLB is
not a live round trip at any sensible connection, so the preview is built from
the proxy and the full mesh is only ever touched on export. The report is run
on the full mesh, because the proxy's faults are ours rather than theirs.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from whittle.edit import EditStack, apply_to, read, resolve
from whittle.ingest import Ingested, ingest
from whittle.ingest.gate import check

#: How long an idle project is kept. Long enough that somebody can go and make
#: tea in the middle of an edit, short enough that a day's uploads do not sit
#: in memory for ever.
IDLE_SECONDS = 60 * 60

#: Above this the preview is built from the proxy. Below it the working mesh
#: is already light enough to send whole.
PREVIEW_TRIANGLES = 150_000


@dataclass
class Project:
    """One mesh somebody is working on, and everything done to it so far."""

    id: str
    source: Ingested
    stack: EditStack
    nozzle_mm: float
    bed_mm: tuple[float, float, float] | None
    touched: float = field(default_factory=time.time)

    #: The gate's verdict on the CURRENT geometry, recomputed when the stack
    #: changes and something that affects printing moved.
    report: Any = None

    def touch(self) -> None:
        self.touched = time.time()

    def evaluate(self):
        return self.stack.evaluate()

    def refresh_report(self) -> None:
        self.report = check(self.evaluate(), nozzle_mm=self.nozzle_mm,
                            bed_mm=self.bed_mm)

    def payload(self) -> dict:
        """Everything the rail needs to draw itself."""
        mesh = self.evaluate()
        span = mesh.bounds[1] - mesh.bounds[0]
        report = self.report or check(mesh, nozzle_mm=self.nozzle_mm,
                                      bed_mm=self.bed_mm)
        return {
            "id": self.id,
            "name": self.source.path.name,
            "format": self.source.fmt.name,
            "units": {
                "units": self.source.units.units,
                "assumed": self.source.units.assumed,
                "reason": self.source.units.reason,
                "alternatives": [
                    {"units": u, "size_mm": round(s, 2)}
                    for u, s in self.source.units.alternatives],
            },
            "repair": {
                "changed": self.source.repair.changed,
                "steps": [str(step) for step in self.source.repair.steps],
                "unresolved": list(self.source.repair.unresolved),
            },
            "size_mm": [round(float(v), 2) for v in span],
            "triangles": int(len(mesh.faces)),
            "bodies": int(len(mesh.split(only_watertight=False))),
            "edits": self._edits(),
            "report": _report_json(report),
        }

    def _edits(self) -> list[dict]:
        rows = []
        for op in self.stack.ops:
            rows.append({
                "id": op.id,
                "kind": op.kind,
                "enabled": op.enabled,
                "summary": _summary_of(op.kind),
                "parameters": [
                    {
                        "name": p.name,
                        "value": p.value,
                        "kind": p.kind,
                        "units": p.units,
                        "low": p.low,
                        "high": p.high,
                        "choices": list(p.choices),
                        "slidable": p.slidable,
                        "description": p.description,
                    }
                    for p in op.parameters
                ],
            })
        return rows


def _summary_of(kind: str) -> str:
    from whittle.edit import REGISTRY

    entry = REGISTRY.get(kind)
    return entry.summary if entry else ""


def _report_json(report) -> dict:
    return {
        "printable": report.printable,
        "findings": [
            {"severity": f.severity, "rule": f.rule, "detail": f.detail,
             "fix": f.fix, "value": f.value}
            for f in report.failures + report.warnings
        ],
        "measurements": {
            k: (list(v) if isinstance(v, tuple) else v)
            for k, v in report.measurements.items()
        },
    }


class Projects:
    """
    Every open editing session, keyed by id.

    Locked, because ThreadingHTTPServer serves each request on its own thread
    and two slider moves arriving together on one project would otherwise
    evaluate the same stack at the same time.
    """

    def __init__(self) -> None:
        self._by_id: dict[str, Project] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    def open(self, path: Path, *, nozzle_mm: float,
             bed_mm: tuple[float, float, float] | None,
             units: str | None = None) -> Project:
        taken = ingest(path, nozzle_mm=nozzle_mm, bed_mm=bed_mm, units=units)
        project = Project(
            id=uuid.uuid4().hex[:12],
            source=taken,
            stack=EditStack(taken.mesh, nozzle_mm=nozzle_mm),
            nozzle_mm=nozzle_mm,
            bed_mm=bed_mm,
            report=taken.report,
        )
        with self._guard:
            self._by_id[project.id] = project
            self._locks[project.id] = threading.Lock()
            self._sweep()
        return project

    def get(self, project_id: str) -> Project:
        with self._guard:
            project = self._by_id.get(project_id)
        if project is None:
            raise KeyError(
                "no open project called %r - it may have timed out, in which "
                "case the file needs uploading again" % project_id)
        project.touch()
        return project

    def lock(self, project_id: str) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault(project_id, threading.Lock())

    def close(self, project_id: str) -> None:
        with self._guard:
            self._by_id.pop(project_id, None)
            self._locks.pop(project_id, None)

    def _sweep(self) -> None:
        """Drop what nobody has touched in an hour. Called under the guard."""
        cutoff = time.time() - IDLE_SECONDS
        for stale in [i for i, p in self._by_id.items() if p.touched < cutoff]:
            self._by_id.pop(stale, None)
            self._locks.pop(stale, None)

    def __len__(self) -> int:
        with self._guard:
            return len(self._by_id)


PROJECTS = Projects()


# ---------------------------------------------------------------------------
# what the routes do
# ---------------------------------------------------------------------------


def open_part(path: Path, *, nozzle_mm: float,
              bed_mm: tuple[float, float, float] | None) -> Project:
    """
    Put an editing session on a part this machine built.

    WHY THE TWO HALVES HAVE TO MEET. Whittle has two ways in - describe a part
    and it gets built, or bring a mesh and get sliders - and until this existed
    they were separate products that happened to share a process. You could
    describe a bracket, watch it build, look at it, and then have nothing to
    turn. The parametric spec is behind it, but section 4 is explicit that the
    durable artefact is a source plus an ordered stack of operations, and a
    built part had no stack.

    So a part opens exactly as an import does: same ingest, same gate, same
    nine operations. It is read off disk rather than sent up and back down
    again, which for a 40 MB STL is the difference between instant and a
    minute of somebody's morning through the phone.

    THIS DOES NOT TOUCH THE PART. The session works on a copy in memory and the
    exports come out of the session; parts/<name>/out is left exactly as the
    build wrote it, because a part on disk is the record of a verified build
    and an edit session is not a re-verification of it.
    """
    if not path.is_file():
        raise FileNotFoundError(
            "that part has no mesh on disk to edit - it may have been built "
            "before its STL was written, in which case build it again")

    return PROJECTS.open(path, nozzle_mm=nozzle_mm, bed_mm=bed_mm,
                         units="mm")


def catalogue() -> dict:
    """
    Every operation a client may offer, and the ones it must not.

    WHY THIS IS A ROUTE AND NOT A LIST IN THE CLIENT. The registry is the only
    statement of what whittle can do to a mesh, and a client with its own copy
    of that list offers an operation the server has never heard of - or, worse,
    quietly stops offering one that was added. The same argument the design
    tokens won: one source, exported, never retyped.

    The bounds here are the SCHEMA's, not a model's. `wall_mm`'s floor is two
    nozzle widths and its ceiling is a third of the smallest extent, neither of
    which exists until there is a mesh - so a parameter whose bounds depend on
    the model says so with `dynamic: true` and the real numbers arrive with the
    operation once it has been added.

    `not_built_yet` is published deliberately. Those names are in the plan and
    absent from the registry, and a client that knows which is which can say
    "not yet" instead of a 404.
    """
    from whittle.edit import NOT_BUILT_YET, REGISTRY

    operations = []
    for kind in sorted(REGISTRY):
        entry = REGISTRY[kind]
        operations.append({
            "kind": kind,
            "summary": entry.summary,
            "affects_print": entry.affects_print,
            "parameters": [
                {
                    "name": spec.name,
                    "default": spec.default,
                    "kind": spec.kind,
                    "units": spec.units,
                    "low": spec.low,
                    "high": spec.high,
                    "choices": list(spec.choices),
                    "description": spec.description,
                    "affects_print": spec.affects_print,
                    "dynamic": spec.dynamic_bounds is not None,
                }
                for spec in entry.params
            ],
        })

    return {"operations": operations, "not_built_yet": list(NOT_BUILT_YET)}


def preview_mesh(project: Project):
    """
    The geometry the viewport draws.

    THE PROXY, WHEN THERE IS ONE. A live slider drag cannot carry a
    300 000-triangle mesh over the wire each frame, and the proxy exists for
    exactly this. It is the preview only - the export is always the real one.
    """
    mesh = project.evaluate()
    if len(mesh.faces) <= PREVIEW_TRIANGLES:
        return mesh, False

    from whittle.ingest.pipeline import _make_proxy

    proxy = _make_proxy(mesh, PREVIEW_TRIANGLES)
    if proxy is None:
        return mesh, False
    return proxy.mesh, True


def to_glb(mesh) -> bytes:
    """The mesh as a GLB, which is what a browser viewer wants."""
    import trimesh

    scene = trimesh.Scene(mesh)
    return scene.export(file_type="glb")


def add_edit(project: Project, kind: str, values: dict) -> dict:
    op = project.stack.add(kind, **(values or {}))
    project.refresh_report()
    return {"added": op.id, "project": project.payload()}


def set_value(project: Project, op_id: str, name: str, value: Any,
              final: bool = False) -> dict:
    """
    Move one slider.

    THE REPORT DOES NOT RUN WHILE THE THUMB IS DOWN, and that is the whole of
    M4's acceptance. Section 13.3 asks for a live re-render with no spinner;
    section 10 asks for the gate on every change that affects printing. Doing
    both literally, on every frame of a drag, measured 1.6 seconds a move -
    and 1.5 of that is the thickness measurement, which is a constant cost
    regardless of how far the slider went.
    
    So the geometry updates on every move and the verdict catches up when the
    thumb lifts. `final` is what the client sends on pointer-up. Between the
    two the report is marked stale rather than silently shown out of date,
    because a green tick describing the previous value is worse than no tick.

    A parameter that cannot change whether the model prints - a rotation about
    the print axis - never triggers a refresh at all.
    """
    bound = project.stack.set_value(op_id, name, value)

    affects = True
    for op in project.stack.ops:
        if op.id == op_id:
            for parameter in op.parameters:
                if parameter.name == name:
                    affects = parameter.affects_print

    stale = False
    if affects:
        if final:
            project.refresh_report()
        else:
            stale = True

    payload = project.payload()
    payload["report"]["stale"] = stale
    return {"clamped": bound.value, "project": payload}


def toggle(project: Project, op_id: str, enabled: bool | None) -> dict:
    project.stack.toggle(op_id, enabled)
    project.refresh_report()
    return {"project": project.payload()}


def remove(project: Project, op_id: str) -> dict:
    project.stack.remove(op_id)
    project.refresh_report()
    return {"project": project.payload()}


def say(project: Project, sentence: str) -> dict:
    """
    A sentence from the command line at the bottom of the layout.

    READ, THEN RETURN WHAT IT MEANS - and only apply when the caller asks.
    Section 12: "Show the selection before applying it." So this reports the
    proposals and applies them in the same call only because the UI has
    already shown the echo; a future confirmation step slots in here without
    the parser changing.
    """
    mesh = project.evaluate()
    reading = resolve(read(sentence), bounds_mm=mesh.bounds,
                      bed_mm=project.bed_mm, nozzle_mm=project.nozzle_mm)

    added = apply_to(reading, project.stack)
    if added:
        project.refresh_report()

    return {
        "echo": reading.echo(),
        "unmapped": list(reading.unmapped),
        "questions": [
            {"about": q.about, "prompt": q.prompt, "options": list(q.options)}
            for q in reading.questions
        ],
        "applied": [
            {"id": op.id, "kind": op.kind,
             "derived": next((p.derived for p in reading.proposals
                              if p.operation == op.kind), {})}
            for op in added
        ],
        "project": project.payload(),
    }
