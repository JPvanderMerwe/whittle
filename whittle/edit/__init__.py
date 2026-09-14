"""
The edit stack. Build plan v8 section 4.

The durable artefact is a source mesh plus an ordered list of parameterised
operations - never baked geometry. Every edit stays a number that can be
dragged and a row that can be switched off.
"""

from whittle.edit.intent import (
    Proposal,
    Question,
    Reading,
    apply_to,
    diff,
    read,
    resolve,
)
from whittle.edit.ops import NOT_BUILT_YET, REGISTRY, Operation, describe_registry
from whittle.edit.params import Parameter, ParameterSpec
from whittle.edit.stack import EditError, EditOp, EditStack, Selector, StepResult

__all__ = [
    "EditError",
    "EditOp",
    "EditStack",
    "NOT_BUILT_YET",
    "Operation",
    "Parameter",
    "Proposal",
    "Question",
    "Reading",
    "ParameterSpec",
    "REGISTRY",
    "Selector",
    "StepResult",
    "apply_to",
    "describe_registry",
    "diff",
    "read",
    "resolve",
]
