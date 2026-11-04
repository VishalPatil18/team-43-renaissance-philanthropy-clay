"""The task library: templates × AOIs → task instances and their references (F13, arch §14).

Layout under the library root (default ``tasks/``)::

    templates/<id>.yaml           TaskTemplate
    aois.yaml                     {aois: [AOI, ...]}
    process_rubrics/<id>.md       rubric text for the LLM process evaluator
    builders/<name>.py            reference builders, each with build(template, aoi, instance)
    references/<id>/<aoi>/<version>.json

Instance IDs are ``<template>@<aoi>`` (DD-043). Parameters come from the template's
``defaults`` overlaid with the AOI's ``template_params[<template>]``.
"""

from __future__ import annotations

import hashlib
import importlib.util
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

import yaml
from pydantic import ValidationError

from claysandbox.contracts.errors import ConfigError
from claysandbox.contracts.task import (
    AOI,
    INSTANCE_ID,
    TaskInstance,
    TaskReference,
    TaskTemplate,
    WorkflowSpec,
)
from claysandbox.tasks.references import BuildResult, ReferenceStore, content_hash
from claysandbox.tasks.render import namespace, render_text, render_value

_AOI_CHECKS = ("bbox_intersects_aoi", "point_within_aoi")

Builder = Callable[[TaskTemplate, AOI, TaskInstance], BuildResult]


def default_root() -> Path:
    """``tasks/`` at the repository root (two levels above this package)."""
    return Path(__file__).resolve().parents[2] / "tasks"


def _read_yaml(path: Path) -> Any:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"cannot read {path}: {exc}") from exc


class FileTaskLibrary:
    """``TaskLibrary`` over the files in one directory."""

    def __init__(self, root: Path | str | None = None) -> None:
        self.root = Path(root) if root is not None else default_root()
        self.references = ReferenceStore(self.root / "references")
        self._templates = self._load_templates()
        self._aois = self._load_aois()

    # -- loading -------------------------------------------------------------------------

    def _load_templates(self) -> dict[str, TaskTemplate]:
        out: dict[str, TaskTemplate] = {}
        for path in sorted((self.root / "templates").glob("*.yaml")):
            try:
                template = TaskTemplate.model_validate(_read_yaml(path))
            except ValidationError as exc:
                raise ConfigError(
                    f"invalid template {path}: {exc}", kind="invalid_template"
                ) from exc
            if template.id != path.stem:
                raise ConfigError(f"{path}: id {template.id!r} must match the file name")
            out[template.id] = template
        return out

    def _load_aois(self) -> dict[str, AOI]:
        path = self.root / "aois.yaml"
        if not path.exists():
            return {}
        data = _read_yaml(path) or {}
        try:
            aois = [AOI.model_validate(a) for a in data.get("aois", [])]
        except ValidationError as exc:
            raise ConfigError(f"invalid AOI in {path}: {exc}", kind="invalid_aoi") from exc
        ids = [a.id for a in aois]
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        if dupes:
            raise ConfigError(f"{path}: duplicate AOI ids {dupes}")
        return {a.id: a for a in aois}

    # -- TaskLibrary ---------------------------------------------------------------------

    def list_templates(self) -> list[TaskTemplate]:
        return [self._templates[k] for k in sorted(self._templates, key=_template_order)]

    def list_aois(self) -> list[AOI]:
        return list(self._aois.values())

    def template(self, template_id: str) -> TaskTemplate:
        try:
            return self._templates[template_id]
        except KeyError:
            raise ConfigError(
                f"unknown template {template_id!r}; known: {sorted(self._templates)}",
                kind="unknown_template",
            ) from None

    def aoi(self, aoi_id: str) -> AOI:
        try:
            return self._aois[aoi_id]
        except KeyError:
            raise ConfigError(
                f"unknown AOI {aoi_id!r}; known: {sorted(self._aois)}", kind="unknown_aoi"
            ) from None

    def instances(
        self, templates: list[str] | None = None, aois: list[str] | str | None = None
    ) -> list[TaskInstance]:
        template_ids = list(self._templates) if templates in (None, "all") else list(templates)
        aoi_ids = list(self._aois) if aois in (None, "all") else list(aois)  # type: ignore[arg-type]
        template_ids.sort(key=_template_order)
        return [
            self.instance(self.template(t), self.aoi(a)) for t in template_ids for a in aoi_ids
        ]

    def get_instance(self, instance_id: str) -> TaskInstance:
        template_id, aoi_id = _split(instance_id)
        return self.instance(self.template(template_id), self.aoi(aoi_id))

    def get_reference(self, instance_id: str, version: str | None = None) -> TaskReference:
        template_id, aoi_id = _split(instance_id)
        if version is None:
            return self.references.latest(template_id, aoi_id)
        return self.references.get(template_id, aoi_id, version)

    def build_references(self, template: str, aoi: str | None = None) -> list[TaskReference]:
        tpl = self.template(template)
        targets = [self.aoi(aoi)] if aoi is not None else self.list_aois()
        builder, builder_sha = self._builder(tpl)
        return [self._build_one(tpl, a, builder, builder_sha) for a in targets]

    # -- instantiation -------------------------------------------------------------------

    def params(self, template: TaskTemplate, aoi: AOI) -> dict[str, Any]:
        params = dict(template.defaults)
        params.update(aoi.template_params.get(template.id, {}))
        missing = [p for p in template.parameters if p != "aoi" and p not in params]
        if missing:
            raise ConfigError(
                f"{template.id}@{aoi.id}: no value for parameters {missing} "
                f"(set them in the template defaults or aois.yaml template_params)"
            )
        return params

    def instance(self, template: TaskTemplate, aoi: AOI) -> TaskInstance:
        params = self.params(template, aoi)
        ns = namespace(aoi, params)
        return TaskInstance(
            id=f"{template.id}@{aoi.id}",
            template=template.id,
            aoi=aoi.id,
            title=render_text(template.title, ns),
            prompt=render_text(template.prompt, ns),
            system_prompt=render_text(template.system_prompt, ns),
            params=params,
            output_schema=template.output_schema,
        )

    def resolve_workflow(self, template: TaskTemplate, aoi: AOI) -> WorkflowSpec:
        """The template's workflow spec with AOI and parameter values filled in."""
        ns = namespace(aoi, self.params(template, aoi))
        resolved = WorkflowSpec.model_validate(render_value(template.workflow.model_dump(), ns))
        for constraint in resolved.argument_constraints:
            if constraint.check in _AOI_CHECKS and constraint.value is None:
                constraint.value = aoi.geometry
        return resolved

    def process_rubric(self, template: TaskTemplate) -> str:
        rel = template.process_rubric or f"process_rubrics/{template.id}.md"
        path = self.root / rel
        return path.read_text(encoding="utf-8") if path.exists() else ""

    # -- building ------------------------------------------------------------------------

    def _builder(self, template: TaskTemplate) -> tuple[Builder, str]:
        path = (self.root / template.output.builder).resolve()
        if not path.is_file() or self.root.resolve() not in path.parents:
            raise ConfigError(f"{template.id}: builder {template.output.builder} not found in "
                              f"{self.root}")
        module = _load_module(path)
        build = getattr(module, "build", None)
        if not callable(build):
            raise ConfigError(f"{path} has no build(template, aoi, instance) function")
        return build, hashlib.sha256(path.read_bytes()).hexdigest()

    def _build_one(
        self, template: TaskTemplate, aoi: AOI, builder: Builder, builder_sha: str
    ) -> TaskReference:
        instance = self.instance(template, aoi)
        result = builder(template, aoi, instance)
        if not isinstance(result, BuildResult):
            raise ConfigError(f"{template.output.builder} must return a BuildResult")
        workflow = self.resolve_workflow(template, aoi)
        digest = content_hash(workflow.model_dump(mode="json"), result.output_reference,
                              template.weights)
        version, existing = self.references.next_version(template.id, aoi.id, digest)
        if existing is not None:
            return existing
        ref = TaskReference(
            template=template.id,
            aoi=aoi.id,
            instance_id=instance.id,
            version=version,
            method=result.method,
            builder=template.output.builder,
            builder_sha256=builder_sha,
            inputs=result.inputs,
            built_at=datetime.now(UTC),
            notes=result.notes,
            workflow=workflow,
            output_reference=result.output_reference,
            weights=template.weights,
            output_schema=template.output_schema,
            process_rubric=self.process_rubric(template),
            aoi_snapshot=aoi,
        )
        self.references.save(ref)
        return ref


def _split(instance_id: str) -> tuple[str, str]:
    match = INSTANCE_ID.match(instance_id)
    if not match:
        raise ConfigError(f"not a task instance id: {instance_id!r} (expected T1@us-ca-kern)")
    return match.group(1), match.group(2)


def _template_order(template_id: str) -> int:
    return int(template_id[1:])


def _load_module(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"clay_builder_{path.stem}", path)
    if spec is None or spec.loader is None:
        raise ConfigError(f"cannot load builder {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
