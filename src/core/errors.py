"""Exception hierarchy. Stages fail closed — nothing here warns and continues."""

from __future__ import annotations


class PipelineError(Exception):
    """Base for every error raised by the pipeline."""


class ContractViolation(PipelineError):
    """A dataframe failed its pandera schema at a stage boundary."""


class SourceDataError(PipelineError):
    """A source file is missing, unreadable, or lacks a declared column."""


class StageError(PipelineError):
    """A stage raised while running."""


class UpstreamFailed(StageError):
    """A stage did not run because something it depends on failed or was skipped."""


class RegistryError(PipelineError):
    """The stage graph is malformed."""


class CycleError(RegistryError):
    """The stage graph contains a cycle, so no topological order exists."""


class CatalogueStoreError(PipelineError):
    """The catalogue database could not be reached, or a write failed to reconcile."""
