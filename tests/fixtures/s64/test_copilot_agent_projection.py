#!/usr/bin/env python3
"""Focused regression tests for S64 copilot_agent semantic compression and reversibility."""

from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "python_scripts"))

import derive_layers  # noqa: E402


def make_item(
    item_id: str,
    title: str,
    role: str,
    summary: str,
    *,
    tags: list[str] | None = None,
    source_primary: str = "data/out/local/tiddlers_1.jsonl",
    line: int = 1,
    relations: list[dict] | None = None,
    ai_relations: list[dict] | None = None,
    text: str | None = None,
) -> dict:
    canon_rec = {
        "title": title,
        "relations": relations or [],
        "text": text or "",
        "content_type": "application/json" if text and text.strip().startswith("{") else "text/plain",
    }
    return {
        "id": item_id,
        "title": title,
        "type": role,
        "summary": summary,
        "authority_level": "derived_non_authoritative_agent_projection",
        "source_primary": source_primary,
        "canon_ref": {"path": source_primary, "line": line},
        "source_refs": {"canon": {"path": source_primary, "line": line}},
        "tags": tags or [],
        "related_ids": [rel.get("target_id") or rel.get("target") for rel in (relations or []) if rel.get("target_id") or rel.get("target")],
        "taxonomy_path": [],
        "_canon_rec": canon_rec,
        "_ai_rec": {"relation_targets": ai_relations or []},
        "confidence": "0.9",
    }


class CopilotAgentProjectionTests(unittest.TestCase):
    def build_sample_items(self) -> list[dict]:
        session61_text = json.dumps(
            {
                "content": {
                    "plain": "S61 materializa microsoft_copilot como proyeccion JSON CSV TXT y deja trazabilidad hacia canon, enriched y ai."
                },
                "decisiones_documentadas": [
                    "Mantener microsoft_copilot como capa derivada y no autoritativa.",
                    "Usar JSON CSV TXT como superficie final del paquete.",
                ],
            },
            ensure_ascii=False,
        )
        hypothesis61_text = json.dumps(
            {
                "hipotesis": "Si microsoft_copilot expone JSON CSV TXT con trazabilidad, entonces agentes externos leen mejor sin romper canon."
            },
            ensure_ascii=False,
        )
        provenance61_text = json.dumps(
            {
                "origen": "S61 nace de contratos S58-S60, README, data/README y la necesidad de cerrar la ruta real de proyeccion."
            },
            ensure_ascii=False,
        )
        contract61_text = json.dumps(
            {
                "summary": "Contrato importable de S61 para microsoft_copilot JSON CSV TXT."
            },
            ensure_ascii=False,
        )
        session63_text = json.dumps(
            {
                "content": {
                    "plain": "S63 integra copilot_agent al pipeline real y fija la ruta oficial dentro de microsoft_copilot."
                }
            },
            ensure_ascii=False,
        )
        contract63_text = json.dumps(
            {
                "summary": "Contrato importable de S63 que integra copilot_agent al pipeline."
            },
            ensure_ascii=False,
        )

        items = [
            make_item(
                "readme",
                "README.md",
                "readme",
                "Describe el layout local-first, la autoridad del canon y el entrypoint de derive_layers.",
                tags=["repo:readme"],
                relations=[{"type": "informs", "target": "## 🗂🧱 Principios de Gestion"}],
            ),
            make_item(
                "principios",
                "## 🗂🧱 Principios de Gestion",
                "policy",
                "Fija reglas transversales de coherencia, trazabilidad y simplicidad para todo el sistema.",
                tags=["## 🗂🧱 principios de gestion"],
                relations=[{"type": "governs", "target": "## 🎯🧱 Detalles del tema"}],
            ),
            make_item(
                "protocolo",
                "## 🧭🧱 Protocolo de Sesión",
                "protocol",
                "Ordena leer situado, actuar sobre archivos reales, validar y cerrar con artefactos.",
                tags=["## 🧭🧱 protocolo de sesion"],
                relations=[{"type": "informs", "target": "## 🌀🧱 Desarrollo y Evolución"}],
            ),
            make_item(
                "detalles",
                "## 🎯🧱 Detalles del tema",
                "config",
                "Delimita objetivos, arquitectura, componentes y alcance sustantivo del proyecto.",
                tags=["## 🎯🧱 detalles del tema"],
            ),
            make_item(
                "canon-policy",
                "contratos/policy/canon_policy_bundle.json",
                "config",
                "Reglas ejecutables para corpus_state, identidad derivada y compuertas de validacion.",
                source_primary="contratos/policy/canon_policy_bundle.json",
            ),
            make_item(
                "registry",
                "contratos/projections/derived_layers_registry.json",
                "config",
                "Mapa de autoridad y linaje entre canon, enriched, ai y microsoft_copilot.",
                source_primary="contratos/projections/derived_layers_registry.json",
            ),
            make_item(
                "derive-script",
                "python_scripts/derive_layers.py",
                "code_source",
                "Entrypoint real del pipeline que genera enriched, ai, microsoft_copilot y copilot_agent.",
                source_primary="python_scripts/derive_layers.py",
            ),
            make_item(
                "identity-go",
                "go/canon/identity.go",
                "code_source",
                "Define id, canonical_slug y version_id como identidad estructural deterministica del canon.",
                source_primary="go/canon/identity.go",
            ),
            make_item(
                "normalizer-go",
                "go/canon/normalizer.go",
                "code_source",
                "Recalcula derivados, normaliza JSON embebido y garantiza salidas canonicas deterministicas.",
                source_primary="go/canon/normalizer.go",
            ),
            make_item(
                "session-61",
                "#### 🌀 Sesión 61 = microsoft-copilot-json-csv-txt-projection-mvp-v0",
                "session",
                "Sesion que materializa microsoft_copilot como capa derivada JSON CSV TXT.",
                tags=["session:m03-s61", "topic:microsoft-copilot"],
                relations=[
                    {"type": "define", "target": "#### 🌀🧪 Hipótesis de sesión 61 = microsoft-copilot-json-csv-txt-projection-mvp-v0"},
                    {"type": "define", "target": "#### 🌀🧾 Procedencia de sesión 61 = microsoft-copilot-json-csv-txt-projection-mvp-v0"},
                    {"type": "usa", "target": "contratos/m03-s61-microsoft-copilot-json-csv-txt-projection-mvp-v0.md.json"},
                ],
                text=session61_text,
            ),
            make_item(
                "hyp-61",
                "#### 🌀🧪 Hipótesis de sesión 61 = microsoft-copilot-json-csv-txt-projection-mvp-v0",
                "hypothesis",
                "Hipotesis de S61 sobre legibilidad para agentes externos.",
                tags=["session:m03-s61", "topic:microsoft-copilot"],
                relations=[{"type": "pertenece_a", "target": "#### 🌀 Sesión 61 = microsoft-copilot-json-csv-txt-projection-mvp-v0"}],
                text=hypothesis61_text,
            ),
            make_item(
                "prov-61",
                "#### 🌀🧾 Procedencia de sesión 61 = microsoft-copilot-json-csv-txt-projection-mvp-v0",
                "provenance",
                "Procedencia de S61 con contratos, README y ruta oficial como base.",
                tags=["session:m03-s61", "topic:microsoft-copilot"],
                relations=[{"type": "pertenece_a", "target": "#### 🌀 Sesión 61 = microsoft-copilot-json-csv-txt-projection-mvp-v0"}],
                text=provenance61_text,
            ),
            make_item(
                "contract-61",
                "contratos/m03-s61-microsoft-copilot-json-csv-txt-projection-mvp-v0.md.json",
                "config",
                "Contrato versionado de S61 para la proyeccion microsoft_copilot.",
                tags=["session:m03-s61", "topic:microsoft-copilot"],
                source_primary="contratos/m03-s61-microsoft-copilot-json-csv-txt-projection-mvp-v0.md.json",
                text=contract61_text,
            ),
            make_item(
                "session-63",
                "#### 🌀 Sesión 63 = copilot-agent-generator-integration-and-canonicalization-v0",
                "session",
                "Sesion que integra copilot_agent al pipeline real en la ruta oficial.",
                tags=["session:m03-s63", "topic:copilot-agent"],
                relations=[{"type": "usa", "target": "contratos/m03-s63-copilot-agent-generator-integration-and-canonicalization-v0.md.json"}],
                text=session63_text,
            ),
            make_item(
                "contract-63",
                "contratos/m03-s63-copilot-agent-generator-integration-and-canonicalization-v0.md.json",
                "config",
                "Contrato versionado de S63 para la integracion real de copilot_agent.",
                tags=["session:m03-s63", "topic:copilot-agent"],
                source_primary="contratos/m03-s63-copilot-agent-generator-integration-and-canonicalization-v0.md.json",
                text=contract63_text,
            ),
        ]

        for idx in range(12):
            items.append(
                make_item(
                    f"old-session-{idx}",
                    f"#### 🌀 Sesión {idx + 1:02d} = historica-{idx}",
                    "session",
                    "Sesion historica de baja prioridad para probar caps de seleccion.",
                    tags=[f"session:m01-s{idx + 1:02d}"],
                )
            )
        return items

    def test_select_copilot_agent_entities_balances_families(self) -> None:
        selected = derive_layers.select_copilot_agent_entities(self.build_sample_items())
        self.assertEqual(sum(1 for item in selected if item.get("synthetic")), 5)
        self.assertTrue(any(item.get("semantic_family") == "copilot_projection" for item in selected))
        self.assertTrue(any(item.get("semantic_family") == "strict_reversibility" for item in selected))
        self.assertTrue(any(item.get("entity_type") == "contract" for item in selected))
        session_count = sum(1 for item in selected if item.get("entity_type") == "session")
        self.assertLessEqual(session_count, derive_layers.COPILOT_AGENT_TYPE_CAPS["session"])

    def test_build_copilot_agent_relations_adds_session_and_layer_edges(self) -> None:
        selected = derive_layers.assign_copilot_agent_anchors(
            derive_layers.select_copilot_agent_entities(self.build_sample_items())
        )
        relations = derive_layers.build_copilot_agent_relations(selected)
        relation_set = {
            (row["source_id"], row["target_id"], row["relation_type"])
            for row in relations
        }
        self.assertIn(("session-61", "contract-61", "session_closes_contract"), relation_set)
        self.assertIn(("session-61", "layer:microsoft_copilot", "session_generates_layer"), relation_set)
        self.assertIn(("layer:copilot_agent", "layer:microsoft_copilot", "layer_derives_from"), relation_set)

    def test_write_copilot_agent_artifacts_curates_exact_three_files(self) -> None:
        items = self.build_sample_items()
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            (output_dir / "legacy.md").write_text("stale", encoding="utf-8")
            written = derive_layers.write_copilot_agent_artifacts(
                items,
                output_dir,
                "2026-04-23T12:00:00Z",
            )
            self.assertEqual(sorted(path.name for path in written), ["corpus.txt", "entities.json", "relations.csv"])
            self.assertEqual(sorted(path.name for path in output_dir.iterdir()), ["corpus.txt", "entities.json", "relations.csv"])

            corpus_text = (output_dir / "corpus.txt").read_text(encoding="utf-8")
            self.assertIn("SECTION_ID: integration_flow", corpus_text)
            self.assertIn("SECTION_ID: strict_reversibility", corpus_text)
            self.assertIn("DOC_ID:", corpus_text)
            self.assertNotIn("TRUNCATED_DECLARED", corpus_text)
            self.assertNotIn("--- TITLE:", corpus_text)

            entities_payload = json.loads((output_dir / "entities.json").read_text(encoding="utf-8"))
            self.assertLessEqual(len(entities_payload["entities"]), derive_layers.COPILOT_AGENT_ENTITY_LIMIT)
            self.assertTrue(all(entity.get("txt_anchor") for entity in entities_payload["entities"]))
            self.assertIn("by_family", entities_payload["entity_counts"])

            with open(output_dir / "relations.csv", "r", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertGreaterEqual(len(rows), 8)

    def test_repository_artifacts_keep_balance_and_density(self) -> None:
        artifact_dir = REPO_ROOT / "data/out/local/microsoft_copilot/copilot_agent"
        entities_path = artifact_dir / "entities.json"
        corpus_path = artifact_dir / "corpus.txt"
        relations_path = artifact_dir / "relations.csv"
        if not entities_path.exists() or not corpus_path.exists() or not relations_path.exists():
            self.skipTest("copilot_agent artifacts are not present in the repository workspace")

        entities_payload = json.loads(entities_path.read_text(encoding="utf-8"))
        self.assertEqual(len(entities_payload["entities"]), derive_layers.COPILOT_AGENT_ENTITY_LIMIT)
        session_count = sum(1 for entity in entities_payload["entities"] if entity.get("type") == "session")
        self.assertLessEqual(session_count, 12)
        self.assertIn("integration_flow", entities_payload["entity_counts"]["by_family"])
        self.assertIn("strict_reversibility", entities_payload["entity_counts"]["by_family"])

        corpus_text = corpus_path.read_text(encoding="utf-8")
        for section_id in derive_layers.COPILOT_AGENT_FAMILY_ORDER:
            self.assertIn(f"SECTION_ID: {section_id}", corpus_text)
        self.assertNotIn("TRUNCATED_DECLARED", corpus_text)
        self.assertNotIn('{"id":', corpus_text)

        with open(relations_path, "r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertGreaterEqual(len(rows), 25)


if __name__ == "__main__":
    unittest.main()
