#!/usr/bin/env python3
"""Deterministic structural classifier for the TDC base template.

The classifier implements the S0171 partial function
``T_base -> {R, A, C, N, D, Q}`` as metadata only.  In particular, this
module does not inspect navigation tags, infer graph edges, or emit canonical
relations.  The relation vocabulary returned by the classifier is only a
reference describing the formal model in which the template participates.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


CLASSIFIER_VERSION = "template-set-classifier/v1"
FORMAL_TEMPLATE_MODEL = "T=R∪A∪C∪N∪D∪Q"

TEMPLATE_SET_VALUES = (
    "root",
    "startup",
    "core_mother",
    "normative_transversal",
    "thematic_deployment",
    "situated_material",
)

FORMAL_RELATION_VOCAB = (
    "part_of",
    "defines",
    "requires",
    "uses",
    "replaces",
    "alternative_to",
    "do_not_combine_with",
)


def _spec(
    template_set: str,
    template_node: str,
    structural_role: str,
    *governance_axis: str,
) -> tuple[str, str, str, tuple[str, ...]]:
    return template_set, template_node, structural_role, governance_axis


# Exact current canon titles.  Values are tuples so callers cannot mutate the
# classifier registry through a returned result.
_CURRENT_TITLE_SPECS = {
    # R: root/orchestrator.  The generic template root and its current TDC
    # specialization share the same structural identity in the live corpus.
    "# 1_objeto_de_estudio_trazabilidad_y_desarrollo": _spec(
        "root", "study_orchestrator", "orchestrator"
    ),
    "# 1_tiddly-data-converter": _spec(
        "root", "tiddly_data_converter", "orchestrator"
    ),
    # A: startup of the study.
    "# 2_🧾 Procedencia inicial": _spec(
        "startup", "initial_provenance", "initial_provenance"
    ),
    "# 3_🧪 Hipótesis inicial": _spec(
        "startup", "initial_hypothesis", "initial_hypothesis"
    ),
    # C: the nine mother cores.
    "## 🌀🧱 Desarrollo y Evolución": _spec(
        "core_mother", "development_and_evolution", "continuity_core"
    ),
    "## 🎯🧱 Detalles del tema": _spec(
        "core_mother", "topic_details", "topic_bridge"
    ),
    "## 📚🧱 Glosario y Convenciones": _spec(
        "core_mother", "glossary_and_conventions", "glossary_core"
    ),
    "## 📦🧱 Dependencias y superficie externa": _spec(
        "core_mother", "dependencies_and_external_surface", "external_surface_core"
    ),
    "## 🧠🧱 Política de Memoria Activa": _spec(
        "core_mother", "active_memory_policy", "active_memory_core"
    ),
    "## 🧪🧱 Hipótesis": _spec(
        "core_mother", "hypotheses", "hypothesis_core"
    ),
    "## 🧭🧱 Protocolo de Sesión": _spec(
        "core_mother", "session_protocol", "session_governance_core"
    ),
    "## 🧰🧱 Elementos específicos": _spec(
        "core_mother", "specific_elements", "specific_materials_core"
    ),
    "## 🧾🧱 Procedencia epistemológica": _spec(
        "core_mother",
        "epistemological_provenance",
        "epistemological_provenance_core",
    ),
    # N: the parent management-principles node plus its twelve current
    # Spanish normative criteria.
    "## 🗂🧱 Arquitectura (del desarrollo)": _spec(
        "normative_transversal",
        "development_architecture",
        "normative_criterion",
        "architecture_governance",
    ),
    "## 🗂🧱 Buen gusto": _spec(
        "normative_transversal",
        "good_taste",
        "normative_criterion",
        "quality_judgment",
    ),
    "## 🗂🧱 Calidad de referencias": _spec(
        "normative_transversal",
        "reference_quality",
        "normative_criterion",
        "reference_quality",
    ),
    "## 🗂🧱 Complejidad Esencial vs Accidental": _spec(
        "normative_transversal",
        "essential_vs_accidental_complexity",
        "normative_criterion",
        "complexity_control",
    ),
    "## 🗂🧱 Diseño": _spec(
        "normative_transversal",
        "design",
        "normative_criterion",
        "design_governance",
    ),
    "## 🗂🧱 Epigenética Computacional": _spec(
        "normative_transversal",
        "computational_epigenetics",
        "normative_criterion",
        "evolution_model",
    ),
    "## 🗂🧱 Estilo Mosston y Ashworth": _spec(
        "normative_transversal",
        "mosston_and_ashworth_style",
        "normative_criterion",
        "decision_distribution",
    ),
    "## 🗂🧱 Estructura de trazabilidad": _spec(
        "normative_transversal",
        "traceability_structure",
        "normative_criterion",
        "traceability",
    ),
    "## 🗂🧱 Evolución Semántica": _spec(
        "normative_transversal",
        "semantic_evolution",
        "normative_criterion",
        "semantic_evolution",
    ),
    "## 🗂🧱 Modularidad y Estado": _spec(
        "normative_transversal",
        "modularity_and_state",
        "normative_criterion",
        "modularity_state",
    ),
    "## 🗂🧱 Principios de Gestion": _spec(
        "normative_transversal",
        "management_principles",
        "normative_criterion",
        "governance",
    ),
    "## 🗂🧱 Reglas de relaciones": _spec(
        "normative_transversal",
        "relationship_rules",
        "normative_criterion",
        "relation_governance",
    ),
    "## 🗂🧱 Usabilidad y Robustez": _spec(
        "normative_transversal",
        "usability_and_robustness",
        "normative_criterion",
        "usability_robustness",
    ),
    # D: the eight thematic deployment nodes.
    "### 🎯 1. Objetivos 🧱": _spec(
        "thematic_deployment", "thematic_objectives", "thematic_requirement"
    ),
    "### 🎯 2. Requisitos 🧱": _spec(
        "thematic_deployment", "thematic_requirements", "thematic_requirement"
    ),
    "### 🎯 3. DOFA 🧱": _spec(
        "thematic_deployment", "thematic_dofa", "thematic_requirement"
    ),
    "### 🎯 4. Flujo de interaccion 🧱": _spec(
        "thematic_deployment", "thematic_interaction_flow", "thematic_requirement"
    ),
    "### 🎯 5. Arquitectura 🌀": _spec(
        "thematic_deployment", "thematic_architecture", "thematic_architecture"
    ),
    "### 🎯 6. Componentes 🌀": _spec(
        "thematic_deployment", "thematic_components", "thematic_component"
    ),
    "### 🎯 7. Algoritmos y matematicas 🌀": _spec(
        "thematic_deployment",
        "thematic_algorithms_and_mathematics",
        "thematic_algorithmic_formalization",
    ),
    "### 🎯 8. Ingeniería asistida por IA 🌀": _spec(
        "thematic_deployment",
        "ai_assisted_engineering",
        "ai_assisted_contractual_support",
    ),
    # Q: situated references/materials.
    "#### referencias especificas 🌀": _spec(
        "situated_material", "specific_references", "situated_reference"
    ),
}


# S0171 uses some English labels in its normative examples.  Supporting only
# these declared aliases keeps matching exact and reviewable; no fuzzy title or
# tag inference is performed.
_DECLARED_ALIASES = {
    "## 🗂🧱 Management Principles": "## 🗂🧱 Principios de Gestion",
    "Management Principles": "## 🗂🧱 Principios de Gestion",
    "## 🧭🧱 Session Protocol": "## 🧭🧱 Protocolo de Sesión",
    "Session Protocol": "## 🧭🧱 Protocolo de Sesión",
    "## 🧠🧱 Active Memory Policy": "## 🧠🧱 Política de Memoria Activa",
    "Active Memory Policy": "## 🧠🧱 Política de Memoria Activa",
    "## 🎯🧱 Topic Details": "## 🎯🧱 Detalles del tema",
    "Topic Details": "## 🎯🧱 Detalles del tema",
    "## 🧾🧱 Epistemological Provenance": "## 🧾🧱 Procedencia epistemológica",
    "Epistemological Provenance": "## 🧾🧱 Procedencia epistemológica",
    "### 🎯 5. Architecture 🌀": "### 🎯 5. Arquitectura 🌀",
    "Architecture": "### 🎯 5. Arquitectura 🌀",
    "### 🎯 6. Components 🌀": "### 🎯 6. Componentes 🌀",
    "Components": "### 🎯 6. Componentes 🌀",
    "### 🎯 7. Algorithms and mathematics 🌀": (
        "### 🎯 7. Algoritmos y matematicas 🌀"
    ),
    "Algorithms and mathematics": "### 🎯 7. Algoritmos y matematicas 🌀",
    "### 🎯 8. AI-assisted engineering 🌀": (
        "### 🎯 8. Ingeniería asistida por IA 🌀"
    ),
    "AI-assisted engineering": "### 🎯 8. Ingeniería asistida por IA 🌀",
    # Orthographic variants present in prose/policies but not in the current
    # canon title fields.
    "## 🗂🧱 Principios de Gestión": "## 🗂🧱 Principios de Gestion",
    "### 🎯 4. Flujo de interacción 🧱": "### 🎯 4. Flujo de interaccion 🧱",
    "### 🎯 7. Algoritmos y matemáticas 🌀": (
        "### 🎯 7. Algoritmos y matematicas 🌀"
    ),
    "#### referencias específicas 🌀": "#### referencias especificas 🌀",
}


def _record_title(record: Mapping[str, Any]) -> str | None:
    for field in ("title", "key"):
        value = record.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def classify_template_record(record: Mapping[str, Any]) -> dict[str, Any] | None:
    """Return S0171 structural metadata for an exact base-template title.

    The input record is not mutated.  Tags and pre-existing relation fields are
    deliberately ignored: navigation membership is not sufficient evidence to
    classify an arbitrary tiddler as a base-template node.
    """

    if not isinstance(record, Mapping):
        return None

    title = _record_title(record)
    if title is None:
        return None

    canonical_title = _DECLARED_ALIASES.get(title, title)
    spec = _CURRENT_TITLE_SPECS.get(canonical_title)
    if spec is None:
        return None

    template_set, template_node, structural_role, governance_axis = spec
    metadata: dict[str, Any] = {
        "template_set": template_set,
        "template_node": template_node,
        "structural_role": structural_role,
        "formal_relation_vocab": list(FORMAL_RELATION_VOCAB),
    }
    if governance_axis:
        metadata["governance_axis"] = list(governance_axis)
    return metadata


def template_mapping_report(records: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Build a deterministic, read-only coverage report for template records."""

    counts = {value: 0 for value in TEMPLATE_SET_VALUES}
    classifications: list[dict[str, Any]] = []
    unclassified_titles: list[str] = []
    records_seen = 0

    for record in records:
        records_seen += 1
        title = _record_title(record) if isinstance(record, Mapping) else None
        metadata = classify_template_record(record)
        if metadata is None:
            if title is not None:
                unclassified_titles.append(title)
            continue

        counts[metadata["template_set"]] += 1
        classifications.append(
            {
                "title": title,
                "metadata": metadata,
            }
        )

    return {
        "classifier_version": CLASSIFIER_VERSION,
        "formal_template_model": FORMAL_TEMPLATE_MODEL,
        "formal_relation_handling": "metadata_reference_only",
        "records_seen": records_seen,
        "classified_count": len(classifications),
        "unclassified_count": records_seen - len(classifications),
        "template_set_counts": counts,
        "classifications": classifications,
        "unclassified_titles": unclassified_titles,
    }


__all__ = [
    "CLASSIFIER_VERSION",
    "FORMAL_RELATION_VOCAB",
    "FORMAL_TEMPLATE_MODEL",
    "TEMPLATE_SET_VALUES",
    "classify_template_record",
    "template_mapping_report",
]
