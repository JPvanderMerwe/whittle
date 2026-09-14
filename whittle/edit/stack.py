"""
The edit stack: a source mesh plus an ordered list of parameterised operations.

Build plan v8 section 4, which calls this "the architecture decision everything
depends on". The durable artefact is never baked geometry - it is the source
and the stack, so every edit stays a number the user can drag and a row they
can switch off.

WHY THE CACHE IS HERE FROM THE FIRST LINE
------------------------------------------
The plan is blunt about it: "This caching is not an optimisation to add later
- interactive editing is the product, and a stack that recomputes from scratch
on every drag is not interactive."

So evaluation is keyed on the state of everything UPSTREAM of each step.
Dragging the wall thickness on step four leaves steps one to three untouched
and reuses their result; only four onwards recompute. Changing step one
invalidates everything, correctly, because everything downstream was computed
from it.

The key is a hash of the source plus the signature of every enabled operation
up to and including this one. Disabled operations change the key - a stack
with step two off is a different stack from one with it on - which is what
makes the non-destructive toggle in section 13.3 free.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from whittle.edit.params import Parameter, ParameterSpec


class EditError(ValueError):
    """An operation could not be applied. The message says which and why."""


@dataclass
class Selector:
    """Which part of the model an operation acts on. v8 section 4."""

    mode: str = "all"               # all | segment | feature | region | index
    segment_id: str | None = None
    feature_type: str | None = None
    filter: dict = field(default_factory=dict)
    resolved_ids: list[int] = field(default_factory=list)

    def signature(self) -> dict:
        return {"mode": self.mode, "segment": self.segment_id,
                "feature": self.feature_type, "filter": self.filter}


@dataclass
class EditOp:
    """One step: what to do, with what numbers, and whether it is switched on."""

    kind: str
    values: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    target: Selector | None = None
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])

    #: Filled in when the op is bound to a model, because bounds depend on the
    #: nozzle and the model's size. See ParameterSpec.bind.
    parameters: list[Parameter] = field(default_factory=list)

    def signature(self) -> dict:
        """
        Everything about this step that could change its result.

        The id is NOT in it. Two identical operations produce identical
        geometry, and letting a random id into the key would miss every cache
        hit for no reason.
        """
        return {
            "kind": self.kind,
            "values": {k: _plain(v) for k, v in sorted(self.values.items())},
            "enabled": self.enabled,
            "target": self.target.signature() if self.target else None,
        }

    def describe(self) -> str:
        if not self.parameters:
            inner = ", ".join("%s %s" % (k, _plain(v))
                              for k, v in sorted(self.values.items()))
        else:
            inner = ", ".join(p.describe() for p in self.parameters)
        return "%s(%s)%s" % (self.kind, inner, "" if self.enabled else " [off]")


def _plain(value: Any) -> Any:
    """Numbers that compare equal hash equal. 2 and 2.0 are the same edit."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return round(float(value), 9)
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


@dataclass
class StepResult:
    """One evaluated step, and whether it had to be computed."""

    mesh: Any
    key: str
    from_cache: bool
    op: EditOp | None = None


class EditStack:
    """
    A source mesh and the operations applied to it, evaluated with caching.

    The source is never modified. Every evaluation returns a new mesh, and the
    intermediate results are held by key so a change low in the stack does not
    disturb the work above it.
    """

    def __init__(self, source: Any, *, nozzle_mm: float = 0.4,
                 registry: dict[str, Any] | None = None,
                 max_cached: int = 24):
        self.source = source
        self.nozzle_mm = nozzle_mm
        self.ops: list[EditOp] = []
        self._cache: dict[str, Any] = {}
        self._order: list[str] = []
        self._max_cached = max_cached
        self._registry = registry
        self._source_key = _mesh_fingerprint(source)

        #: How the last evaluation went. Read by the tests and by anything
        #: that wants to prove a drag was cheap.
        self.last_run: list[StepResult] = []

    # -- building the stack ------------------------------------------------

    def add(self, kind: str, /, **values: Any) -> EditOp:
        """Put an operation on the end of the stack."""
        op = EditOp(kind=kind, values=dict(values))
        self._bind(op)
        self.ops.append(op)
        return op

    def insert(self, index: int, kind: str, /, **values: Any) -> EditOp:
        op = EditOp(kind=kind, values=dict(values))
        self._bind(op)
        self.ops.insert(index, op)
        return op

    def remove(self, op_id: str) -> None:
        self.ops = [op for op in self.ops if op.id != op_id]

    def get(self, op_id: str) -> EditOp:
        for op in self.ops:
            if op.id == op_id:
                return op
        raise EditError("no operation with id %r in this stack" % op_id)

    def set_value(self, op_id: str, name: str, value: Any) -> Parameter:
        """
        Move one slider. Returns the bound parameter, clamped.

        This is what a drag calls, and it is why bounds live on the parameter:
        the value that comes back is the value that will be used, so the UI
        can show the clamp happening rather than discovering it later.
        """
        op = self.get(op_id)
        spec = self._spec_for(op.kind, name)
        bound = spec.bind(value, nozzle_mm=self.nozzle_mm,
                          extents_mm=self._extents())
        op.values[name] = bound.value
        self._bind(op)
        return bound

    def toggle(self, op_id: str, enabled: bool | None = None) -> EditOp:
        """v8 section 13.3: "Toggle any row off and the model reverts"."""
        op = self.get(op_id)
        op.enabled = (not op.enabled) if enabled is None else bool(enabled)
        return op

    # -- evaluating --------------------------------------------------------

    def evaluate(self, upto: int | None = None) -> Any:
        """
        Run the stack and return the mesh, reusing whatever has not changed.

        `upto` evaluates only the first N operations, which is what a preview
        of one step needs.
        """
        ops = self.ops if upto is None else self.ops[:upto]
        mesh = self.source
        key = self._source_key
        run: list[StepResult] = []

        for op in ops:
            if not op.enabled:
                # A disabled step is a no-op that still changes the key, so a
                # stack with it off caches separately from one with it on.
                key = _chain(key, {"skipped": op.kind})
                continue

            key = _chain(key, op.signature())
            cached = self._cache.get(key)
            if cached is not None:
                mesh = cached
                run.append(StepResult(mesh, key, True, op))
                self._touch(key)
                continue

            mesh = self._apply(op, mesh)
            self._store(key, mesh)
            run.append(StepResult(mesh, key, False, op))

        self.last_run = run
        return mesh

    def _apply(self, op: EditOp, mesh: Any) -> Any:
        registry = self._registry
        if registry is None:
            from whittle.edit import ops as ops_module

            registry = ops_module.REGISTRY
        entry = registry.get(op.kind)
        if entry is None:
            raise EditError(
                "there is no operation called %r. This build has: %s."
                % (op.kind, ", ".join(sorted(registry))))

        bound = {p.name: p.value for p in op.parameters}
        try:
            result = entry.run(mesh, bound, op.target, nozzle_mm=self.nozzle_mm)
        except EditError:
            raise
        except Exception as exc:
            raise EditError(
                "%s failed on this model: %s"
                % (op.kind, str(exc).split("\n")[0][:200])) from exc
        if result is None:
            raise EditError("%s produced nothing" % op.kind)
        return result

    # -- internals ---------------------------------------------------------

    def _registry_or_default(self) -> dict:
        if self._registry is not None:
            return self._registry
        from whittle.edit import ops as ops_module

        return ops_module.REGISTRY

    def _spec_for(self, kind: str, name: str) -> ParameterSpec:
        entry = self._registry_or_default().get(kind)
        if entry is None:
            raise EditError("there is no operation called %r" % kind)
        for spec in entry.params:
            if spec.name == name:
                return spec
        raise EditError(
            "%s has no parameter called %r. It has: %s."
            % (kind, name, ", ".join(s.name for s in entry.params)))

    def _bind(self, op: EditOp) -> None:
        """Resolve this op's parameters against the model and the machine."""
        entry = self._registry_or_default().get(op.kind)
        if entry is None:
            raise EditError(
                "there is no operation called %r. This build has: %s."
                % (op.kind, ", ".join(sorted(self._registry_or_default()))))
        extents = self._extents()
        bound = []
        for spec in entry.params:
            value = op.values.get(spec.name)
            parameter = spec.bind(value, nozzle_mm=self.nozzle_mm,
                                  extents_mm=extents)
            op.values[spec.name] = parameter.value
            bound.append(parameter)
        op.parameters = bound

    def _extents(self) -> tuple[float, float, float]:
        try:
            span = self.source.bounds[1] - self.source.bounds[0]
            return (float(span[0]), float(span[1]), float(span[2]))
        except Exception:
            return (100.0, 100.0, 100.0)

    def _store(self, key: str, mesh: Any) -> None:
        self._cache[key] = mesh
        self._order.append(key)
        while len(self._order) > self._max_cached:
            oldest = self._order.pop(0)
            if oldest in self._cache and oldest not in self._order:
                del self._cache[oldest]

    def _touch(self, key: str) -> None:
        if key in self._order:
            self._order.remove(key)
        self._order.append(key)

    def describe(self) -> str:
        if not self.ops:
            return "no edits"
        return "\n".join("%d. %s" % (i + 1, op.describe())
                         for i, op in enumerate(self.ops))

    def to_json(self) -> list[dict]:
        """The stack as data. This is the half of the project file that matters."""
        return [{"id": op.id, "kind": op.kind, "enabled": op.enabled,
                 "values": {k: _plain(v) for k, v in sorted(op.values.items())},
                 "target": op.target.signature() if op.target else None}
                for op in self.ops]


def _chain(previous: str, signature: dict) -> str:
    """One link of the key chain: everything upstream, plus this step."""
    blob = json.dumps(signature, sort_keys=True, default=str)
    return hashlib.sha1(("%s|%s" % (previous, blob)).encode()).hexdigest()


def _mesh_fingerprint(mesh: Any) -> str:
    """
    A stable identity for the source mesh.

    From the geometry rather than from a filename, because two sessions on the
    same file must hit the same cache and a file renamed is not a different
    model. trimesh already keeps a content hash; the fallback covers anything
    that does not.
    """
    try:
        return str(mesh.identifier_hash)
    except Exception:
        pass
    try:
        import numpy as np

        return hashlib.sha1(np.ascontiguousarray(
            mesh.vertices).tobytes()).hexdigest()
    except Exception:
        return "unhashable"
