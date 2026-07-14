from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src" / "python_scripts"))

from template_set_classifier import (  # noqa: E402
    FORMAL_RELATION_VOCAB,
    classify_template_record,
    template_mapping_report,
)
from build_metadata_promotion_candidates import build_candidates  # noqa: E402
from build_rag_filter_preview import (  # noqa: E402
    build_preview_records,
    build_promoted_metadata_index,
)
from metadata_promotion_policy import (  # noqa: E402
    DEFAULT_POLICY,
    classify_promotion,
    write_default_policy,
)
from semantic_text_builder import build_semantic_text_outputs  # noqa: E402
from tag_sanitation_policy import write_default_policy as write_tag_policy  # noqa: E402


BASE_TEMPLATE_CASES = [
    ("# 1_tiddly-data-converter", "root", "tiddly_data_converter", "orchestrator"),
    ("# 2_🧾 Procedencia inicial", "startup", "initial_provenance", "initial_provenance"),
    ("# 3_🧪 Hipótesis inicial", "startup", "initial_hypothesis", "initial_hypothesis"),
    ("## 🌀🧱 Desarrollo y Evolución", "core_mother", "development_and_evolution", "continuity_core"),
    ("## 🎯🧱 Detalles del tema", "core_mother", "topic_details", "topic_bridge"),
    ("## 📚🧱 Glosario y Convenciones", "core_mother", "glossary_and_conventions", "glossary_core"),
    ("## 📦🧱 Dependencias y superficie externa", "core_mother", "dependencies_and_external_surface", "external_surface_core"),
    ("## 🧠🧱 Política de Memoria Activa", "core_mother", "active_memory_policy", "active_memory_core"),
    ("## 🧪🧱 Hipótesis", "core_mother", "hypotheses", "hypothesis_core"),
    ("## 🧭🧱 Protocolo de Sesión", "core_mother", "session_protocol", "session_governance_core"),
    ("## 🧰🧱 Elementos específicos", "core_mother", "specific_elements", "specific_materials_core"),
    ("## 🧾🧱 Procedencia epistemológica", "core_mother", "epistemological_provenance", "epistemological_provenance_core"),
    ("## 🗂🧱 Arquitectura (del desarrollo)", "normative_transversal", "development_architecture", "normative_criterion"),
    ("## 🗂🧱 Buen gusto", "normative_transversal", "good_taste", "normative_criterion"),
    ("## 🗂🧱 Calidad de referencias", "normative_transversal", "reference_quality", "normative_criterion"),
    ("## 🗂🧱 Complejidad Esencial vs Accidental", "normative_transversal", "essential_vs_accidental_complexity", "normative_criterion"),
    ("## 🗂🧱 Diseño", "normative_transversal", "design", "normative_criterion"),
    ("## 🗂🧱 Epigenética Computacional", "normative_transversal", "computational_epigenetics", "normative_criterion"),
    ("## 🗂🧱 Estilo Mosston y Ashworth", "normative_transversal", "mosston_and_ashworth_style", "normative_criterion"),
    ("## 🗂🧱 Estructura de trazabilidad", "normative_transversal", "traceability_structure", "normative_criterion"),
    ("## 🗂🧱 Evolución Semántica", "normative_transversal", "semantic_evolution", "normative_criterion"),
    ("## 🗂🧱 Modularidad y Estado", "normative_transversal", "modularity_and_state", "normative_criterion"),
    ("## 🗂🧱 Principios de Gestion", "normative_transversal", "management_principles", "normative_criterion"),
    ("## 🗂🧱 Reglas de relaciones", "normative_transversal", "relationship_rules", "normative_criterion"),
    ("## 🗂🧱 Usabilidad y Robustez", "normative_transversal", "usability_and_robustness", "normative_criterion"),
    ("### 🎯 1. Objetivos 🧱", "thematic_deployment", "thematic_objectives", "thematic_requirement"),
    ("### 🎯 2. Requisitos 🧱", "thematic_deployment", "thematic_requirements", "thematic_requirement"),
    ("### 🎯 3. DOFA 🧱", "thematic_deployment", "thematic_dofa", "thematic_requirement"),
    ("### 🎯 4. Flujo de interaccion 🧱", "thematic_deployment", "thematic_interaction_flow", "thematic_requirement"),
    ("### 🎯 5. Arquitectura 🌀", "thematic_deployment", "thematic_architecture", "thematic_architecture"),
    ("### 🎯 6. Componentes 🌀", "thematic_deployment", "thematic_components", "thematic_component"),
    ("### 🎯 7. Algoritmos y matematicas 🌀", "thematic_deployment", "thematic_algorithms_and_mathematics", "thematic_algorithmic_formalization"),
    ("### 🎯 8. Ingeniería asistida por IA 🌀", "thematic_deployment", "ai_assisted_engineering", "ai_assisted_contractual_support"),
    ("#### referencias especificas 🌀", "situated_material", "specific_references", "situated_reference"),
]


def test_template_set_classifier_maps_current_base_nodes_exactly() -> None:
    for title, template_set, template_node, structural_role in BASE_TEMPLATE_CASES:
        result = classify_template_record({"title": title})

        assert result is not None
        assert result["template_set"] == template_set
        assert result["template_node"] == template_node
        assert result["structural_role"] == structural_role
        assert "topics" not in result


def test_normative_nodes_map_to_declared_governance_axes() -> None:
    expected = {
        "## 🗂🧱 Principios de Gestion": "governance",
        "## 🗂🧱 Arquitectura (del desarrollo)": "architecture_governance",
        "## 🗂🧱 Epigenética Computacional": "evolution_model",
        "## 🗂🧱 Diseño": "design_governance",
        "## 🗂🧱 Complejidad Esencial vs Accidental": "complexity_control",
        "## 🗂🧱 Buen gusto": "quality_judgment",
        "## 🗂🧱 Modularidad y Estado": "modularity_state",
        "## 🗂🧱 Estilo Mosston y Ashworth": "decision_distribution",
        "## 🗂🧱 Calidad de referencias": "reference_quality",
        "## 🗂🧱 Reglas de relaciones": "relation_governance",
        "## 🗂🧱 Evolución Semántica": "semantic_evolution",
        "## 🗂🧱 Estructura de trazabilidad": "traceability",
        "## 🗂🧱 Usabilidad y Robustez": "usability_robustness",
    }

    for title, axis in expected.items():
        result = classify_template_record({"title": title})
        assert result is not None
        assert result["governance_axis"] == [axis]


def test_classifier_is_exact_and_ignores_navigation_tags() -> None:
    record = {
        "title": "A session record that merely links the template",
        "tags": ["## 🧭🧱 Protocolo de Sesión"],
        "relations": [{"type": "part_of", "target": "template"}],
    }
    before = {"title": record["title"], "tags": list(record["tags"]), "relations": list(record["relations"])}

    assert classify_template_record(record) is None
    assert record == before


def test_formal_relation_vocab_is_metadata_reference_not_edges() -> None:
    result = classify_template_record({"title": "## 🧭🧱 Protocolo de Sesión"})

    assert result is not None
    assert result["formal_relation_vocab"] == list(FORMAL_RELATION_VOCAB)
    assert "relations" not in result
    assert "edges" not in result
    assert "canonical_relation" not in result


def test_template_mapping_report_counts_all_six_sets_deterministically() -> None:
    records = [{"title": case[0]} for case in BASE_TEMPLATE_CASES]
    records.append({"title": "ordinary situated content"})

    first = template_mapping_report(records)
    second = template_mapping_report(records)

    assert first == second
    assert first["formal_relation_handling"] == "metadata_reference_only"
    assert first["classified_count"] == len(BASE_TEMPLATE_CASES)
    assert first["unclassified_count"] == 1
    assert first["template_set_counts"] == {
        "root": 1,
        "startup": 2,
        "core_mother": 9,
        "normative_transversal": 13,
        "thematic_deployment": 8,
        "situated_material": 1,
    }


def test_declared_english_examples_are_explicit_aliases_not_topics() -> None:
    management = classify_template_record({"title": "Management Principles"})
    ai_support = classify_template_record({"title": "AI-assisted engineering"})

    assert management is not None
    assert management["template_node"] == "management_principles"
    assert management["template_set"] == "normative_transversal"
    assert ai_support is not None
    assert ai_support["template_node"] == "ai_assisted_engineering"
    assert ai_support["template_set"] == "thematic_deployment"
    assert "topics" not in management
    assert "topics" not in ai_support


def test_p1_topic_tags_promote_to_normalized_topics() -> None:
    decision = classify_promotion("topic:relation-governance", upstream_rag_class="p1_metadata_only")

    assert decision is not None
    assert decision["target_field"] == "topics"
    assert decision["proposed_value"] == "relation_governance"
    assert decision["promotion_status"] == "candidate"


def test_operational_p1_fields_do_not_promote_to_topics() -> None:
    expected = {
        "session:m04-s0170": ("session_id", "S0170"),
        "status:local_admitted": ("status", "local_admitted"),
        "layer:session": ("layer", "session"),
        "artifact:diagnostico_de_sesion": ("artifact_family", "session_diagnosis"),
    }
    for tag, (field, value) in expected.items():
        decision = classify_promotion(tag, upstream_rag_class="p1_metadata_only")
        assert decision is not None
        assert decision["target_field"] == field
        assert decision["proposed_value"] == value
        assert decision["target_field"] != "topics"


def test_noncanonical_session_and_generic_topic_require_review() -> None:
    session = classify_promotion(
        "session:diagnostico-tematico-063",
        upstream_rag_class="p1_metadata_only",
    )
    topic = classify_promotion("topic:TEMA", upstream_rag_class="p1_metadata_only")

    assert session is not None and session["block_reason"] == "noncanonical_session_id"
    assert topic is not None and topic["block_reason"] == "generic_value"
    assert session["requires_human_review"] is True
    assert topic["promotion_status"] == "blocked"


def test_curated_tech_stack_override_discloses_upstream_unknown() -> None:
    decision = classify_promotion("⚙️ Python", upstream_rag_class="unknown_review")

    assert decision is not None
    assert decision["target_field"] == "tech_stack"
    assert decision["proposed_value"] == "python"
    assert decision["classification_override"] == {
        "upstream": "unknown_review",
        "effective": "p1_metadata_only",
        "basis": "operator_supplied_mapping_in_S0171",
    }


def test_path_like_values_do_not_promote_to_tech_stack() -> None:
    policy = json.loads(json.dumps(DEFAULT_POLICY, ensure_ascii=False))
    policy["prefix_mappings"]["stack:"] = "tech_stack"

    decision = classify_promotion(
        "stack:src/python_scripts/example.py",
        upstream_rag_class="p1_metadata_only",
        policy=policy,
    )

    assert decision is not None
    assert decision["promotion_status"] == "blocked"
    assert decision["block_reason"] == "path_like_value"


def test_candidate_generation_and_rag_filters_are_dry_run_and_normalized(tmp_path: Path) -> None:
    tag_policy = write_tag_policy(tmp_path / "tag_policy.json")
    promotion_policy = write_default_policy(tmp_path / "promotion_policy.json")
    records = [
        {
            "id": "r1",
            "title": "Ordinary record",
            "tags": ["topic:rag-safe", "session:m04-s0170", "⚙️ Python", "needs-review"],
        }
    ]
    original = json.dumps(records, ensure_ascii=False, sort_keys=True)

    candidates, observations = build_candidates(
        records,
        tag_policy=tag_policy,
        promotion_policy=promotion_policy,
    )
    promoted = build_promoted_metadata_index(
        candidates,
        allowed_fields=set(promotion_policy["allowed_fields"]),
    )
    preview = build_preview_records(records, promoted_metadata=promoted, tag_policy=tag_policy)

    assert observations["p1_tags_seen"] == 2
    assert observations["curated_exact_override_occurrences"] == 1
    assert all(row["authority_level"] == "proposed" for row in candidates)
    assert all(row["canon_modified"] is False for row in candidates)
    assert promoted["r1"]["topics"] == ["rag_safe"]
    assert promoted["r1"]["session_id"] == "S0170"
    assert promoted["r1"]["tech_stack"] == ["python"]
    serialized = json.dumps(preview, ensure_ascii=False)
    assert "topic:rag-safe" not in serialized
    assert "session:m04-s0170" not in serialized
    assert "needs-review" not in serialized
    assert json.dumps(records, ensure_ascii=False, sort_keys=True) == original


def test_semantic_builder_promoted_mode_redacts_raw_p1_everywhere(tmp_path: Path) -> None:
    canon = tmp_path / "canon" / "tiddlers_1.jsonl"
    canon.parent.mkdir(parents=True)
    record = {
        "id": "r1",
        "key": "Record",
        "title": "Record",
        "tags": ["topic:rag-safe", "status:local_admitted"],
        "source_tags": ["topic:rag-safe", "status:local_admitted"],
        "source_fields": {"artifact_family": "diagnosis"},
        "relations": [],
        "text": "Embedded tag topic:rag-safe must not leak.",
    }
    canon.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")
    before = hashlib.sha256(canon.read_bytes()).hexdigest()
    tag_policy = tmp_path / "tag_policy.json"
    write_tag_policy(tag_policy)

    result = build_semantic_text_outputs(
        canon_glob=str(canon.parent / "tiddlers_*.jsonl"),
        out_dir=tmp_path / "preview",
        session="s0171",
        tag_policy=tag_policy,
        type_policy=tmp_path / "missing_relation_policy.json",
        promoted_metadata_by_id={
            "r1": {"topics": ["rag_safe"], "status": "local_admitted"}
        },
    )
    output = Path(result["paths"]["records"]).read_text(encoding="utf-8")

    assert "topic:rag-safe" not in output
    assert "status:local_admitted" not in output
    assert "topic: rag_safe" in output
    assert "normalized_promoted_metadata_only" in output
    assert hashlib.sha256(canon.read_bytes()).hexdigest() == before
