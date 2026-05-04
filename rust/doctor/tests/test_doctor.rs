//! Tests de contrato del Doctor / Auditoría mínima.
//!
//! Estos tests validan los comportamientos exigidos por
//! `contratos/m01-s04-doctor-contract.md`.
//!
//! Activados en m01-s10 con la implementación real de `audit()`.
//! Cada test incluye el criterio de aceptación que valida (§10 del contrato).
//!
//! Ref: contratos/m01-s04-doctor-contract.md §10

use std::path::{Path, PathBuf};
use tdc_doctor::{
    audit, audit_canonical_lines, audit_perimeter, audit_reconstruction_plan,
    audit_reconstruction_plan_with_artifacts, audit_reconstruction_rollback,
    canonical_canon_tree_hash, inspect_deep_nodes, CanonicalLineVerdict, DoctorError,
    DoctorVerdict, PerimeterVerdict, ReconstructionMode, ReconstructionPlanVerdict,
    ReconstructionRollbackVerdict, ReconstructionSourceRole,
};

/// Ruta base a los fixtures compartidos del repositorio.
fn fixtures_dir() -> std::path::PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../../tests/fixtures")
}

fn temp_repo_root(name: &str) -> PathBuf {
    let mut root = std::env::temp_dir();
    root.push(format!("tdc_doctor_{}_{}", name, std::process::id()));
    if root.exists() {
        std::fs::remove_dir_all(&root).expect("cleanup temp repo root");
    }
    root
}

fn write_file(path: &Path, content: &str) {
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).expect("create parent dir");
    }
    std::fs::write(path, content).expect("write fixture file");
}

fn minimal_policy_bundle() -> &'static str {
    r#"{
      "local_output_root": "data/out/local",
      "session_semantic_close_default": "data_sessions_staging",
      "reverse_html_root": "data/out/local/reverse_html",
      "direct_canon_write_default": "prohibited_by_default_requires_local_admission",
      "role_primary_contract": {
        "schema_version": "s79-role-primary-contract-v0",
        "field": "role_primary",
        "canonical_roles": ["concept", "procedure", "evidence", "definition", "glossary", "policy", "log", "asset", "config", "code", "narrative", "note", "warning", "unclassified"],
        "aliases_allowed": {"concepto": "concept"},
        "legacy_accepted_transitional": {"session": {"canonical_role": "log"}, "hypothesis": {"canonical_role": null}},
        "ambiguous_roles": {"hypothesis": ["evidence", "procedure"]},
        "invalid_policy": {"default_verdict": "role_invalid"}
      }
    }"#
}

fn write_minimal_role_contract(root: &Path) {
    write_file(
        &root.join("data/out/sessions/00_contratos/policy/canon_policy_bundle.json"),
        minimal_policy_bundle(),
    );
}

fn write_minimal_perimeter_fixture(root: &Path) {
    write_file(
        &root.join("data/in/objeto_de_estudio_trazabilidad_y_desarrollo.html"),
        "<html>seed</html>",
    );
    write_file(&root.join("data/in/empty-store.html"), "<html>empty</html>");
    write_file(
        &root.join("data/in/tiddly-data-converter (Saved).html"),
        "<html>saved</html>",
    );
    std::fs::create_dir_all(root.join("data/out/sessions")).expect("sessions dir");
    std::fs::create_dir_all(root.join("data/tmp")).expect("tmp dir");
    std::fs::create_dir_all(root.join("data/out/local/reverse_html")).expect("reverse dir");
    write_file(&root.join("data/out/local/tiddlers_1.jsonl"), "{}\n");
    write_file(&root.join("shell_scripts/tdc.sh"), "#!/usr/bin/env bash\n");
    write_file(
        &root.join("README.md"),
        "# tdc\n\n```bash\nshell_scripts/tdc.sh\n```\n",
    );
    write_minimal_role_contract(root);
    write_file(
        &root.join("data/out/sessions/00_contratos/projections/derived_layers_registry.json"),
        r#"{
          "source_of_truth_layer": "canon",
          "layer_classes": {
            "canon": {"is_canonical": true},
            "session_staging": {"is_canonical": false},
            "derived": {"is_canonical": false},
            "reverse_projection": {"is_canonical": false}
          }
        }"#,
    );
}

fn write_export_manifest(
    root: &Path,
    source: &Path,
    jsonl: &Path,
    source_hash: &str,
    jsonl_hash: &str,
) {
    let manifest = jsonl.with_file_name("tiddlers.export.manifest.json");
    write_file(
        &manifest,
        &format!(
            r#"{{
              "run_id": "export-test",
              "schema_version": "v0",
              "artifact_role": "canon_export",
              "source_html_path": "{}",
              "source_html_sha256": "{}",
              "sha256": "{}",
              "output_path": "{}"
            }}"#,
            source.strip_prefix(root).unwrap_or(source).display(),
            source_hash,
            jsonl_hash,
            jsonl.strip_prefix(root).unwrap_or(jsonl).display(),
        ),
    );
}

fn complete_canon_line(title: &str, family: &str, order: usize) -> String {
    let source_folder = match family {
        "contrato_de_sesion" => "00_contratos",
        "procedencia_de_sesion" => "01_procedencia",
        "detalles_de_sesion" => "02_detalles_de_sesion",
        "hipotesis_de_sesion" => "03_hipotesis",
        "balance_de_sesion" => "04_balance_de_sesion",
        "propuesta_de_sesion" => "05_propuesta_de_sesion",
        "diagnostico_de_sesion" => "06_diagnoses/sesion",
        _ => "02_detalles_de_sesion",
    };
    let source_path = format!("data/out/sessions/{source_folder}/test.md.json");
    serde_json::json!({
        "schema_version": "v0",
        "id": format!("123e4567-e89b-12d3-a456-426614174{order:03}"),
        "key": title,
        "title": title,
        "canonical_slug": format!("session-{order}"),
        "version_id": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "content_type": "text/markdown",
        "modality": "text",
        "encoding": "utf-8",
        "is_binary": false,
        "is_reference_only": false,
        "role_primary": "note",
        "tags": ["session:test", "milestone:m99", format!("artifact:{family}"), "status:candidate", "layer:session"],
        "taxonomy_path": ["session"],
        "semantic_text": null,
        "content": {"plain": "Contenido"},
        "raw_payload_ref": format!("node:123e4567-e89b-12d3-a456-426614174{order:03}"),
        "mime_type": "text/markdown",
        "document_id": "doc-test",
        "section_path": ["session"],
        "order_in_document": order,
        "relations": [],
        "source_tags": ["session:test", "milestone:m99", format!("artifact:{family}"), "status:candidate", "layer:session"],
        "normalized_tags": ["session:test", "milestone:m99", format!("artifact:{family}"), "status:candidate", "layer:session"],
        "source_fields": {
            "session_origin": "m99-s99-test",
            "artifact_family": family,
            "source_path": source_path.clone(),
            "canonical_status": "candidate_not_admitted",
            "document_key": "data/out/sessions/m99-s99-test",
            "provenance_ref": "data/out/sessions/01_procedencia/test.md.json"
        },
        "source_role": "reporte",
        "text": "Contenido",
        "source_type": "text/markdown",
        "source_position": format!("{source_path}:{order}"),
        "created": "20260430000000000",
        "modified": "20260430000000000"
    })
    .to_string()
}

// ---------------------------------------------------------------------------
// Fallos bloqueantes (Err result) — §8 del contrato
// ---------------------------------------------------------------------------

/// §10 criterio: audit() devuelve Err(DoctorError::RawFileNotFound) si la ruta no existe.
#[test]
fn test_archivo_inexistente_produce_error_raw_file_not_found() {
    let ruta = Path::new("/ruta/que/no/existe/raw.tiddlers.json");
    let resultado = audit(ruta);
    assert!(matches!(resultado, Err(DoctorError::RawFileNotFound(_))));
}

/// §10 criterio: audit() devuelve Err(DoctorError::RawNotValidJson) si el contenido no es JSON válido.
#[test]
fn test_json_invalido_produce_error_raw_not_valid_json() {
    let ruta = fixtures_dir().join("raw_tiddlers_invalid.json");
    let resultado = audit(&ruta);
    assert!(
        matches!(resultado, Err(DoctorError::RawNotValidJson(_))),
        "se esperaba RawNotValidJson, se obtuvo: {:?}",
        resultado
    );
}

// ---------------------------------------------------------------------------
// Auditoría exitosa (Ok result con verdict) — §10 del contrato
// ---------------------------------------------------------------------------

/// §10 criterio: audit() devuelve Ok(DoctorReport) con verdict Ok ante artefacto estructuralmente correcto.
#[test]
fn test_artefacto_minimo_correcto_produce_veredicto_ok() {
    let ruta = fixtures_dir().join("raw_tiddlers_minimal.json");
    let resultado = audit(&ruta).expect("audit() debería devolver Ok para fixture mínimo");
    assert_eq!(
        resultado.verdict,
        DoctorVerdict::Ok,
        "se esperaba veredicto Ok, se obtuvo: {:?}",
        resultado.verdict
    );
    assert!(
        resultado.errors.is_empty(),
        "no debe haber errores: {:?}",
        resultado.errors
    );
}

/// §10 criterio: audit() devuelve Ok(DoctorReport) con verdict Warning ante título vacío.
#[test]
fn test_titulo_vacio_produce_veredicto_warning() {
    let ruta = fixtures_dir().join("raw_tiddlers_empty_title.json");
    let resultado =
        audit(&ruta).expect("audit() debería devolver Ok para fixture con título vacío");
    assert_eq!(
        resultado.verdict,
        DoctorVerdict::Warning,
        "se esperaba veredicto Warning, se obtuvo: {:?}",
        resultado.verdict
    );
    assert!(
        resultado.errors.is_empty(),
        "no debe haber errores bloqueantes: {:?}",
        resultado.errors
    );
    assert!(
        !resultado.warnings.is_empty(),
        "debe haber al menos un warning"
    );
}

/// §10 criterio: audit() devuelve Ok(DoctorReport) con verdict Error ante tiddler sin campo title.
#[test]
fn test_tiddler_sin_titulo_produce_veredicto_error() {
    let ruta = fixtures_dir().join("raw_tiddlers_no_title.json");
    let resultado =
        audit(&ruta).expect("audit() debería devolver Ok incluso con errores de integridad");
    assert_eq!(
        resultado.verdict,
        DoctorVerdict::Error,
        "se esperaba veredicto Error, se obtuvo: {:?}",
        resultado.verdict
    );
    assert!(
        !resultado.errors.is_empty(),
        "debe haber al menos un error de integridad"
    );
}

/// §10 criterio: DoctorReport siempre incluye tiddler_count, warnings y errors.
#[test]
fn test_reporte_siempre_tiene_campos_minimos() {
    let ruta = fixtures_dir().join("raw_tiddlers_minimal.json");
    let reporte = audit(&ruta).expect("audit() debería devolver Ok para fixture mínimo");
    // tiddler_count debe ser > 0 para el fixture mínimo
    assert!(
        reporte.tiddler_count > 0,
        "tiddler_count debe ser > 0 para fixture mínimo, fue {}",
        reporte.tiddler_count
    );
    // warnings y errors son Vecs — siempre presentes (pueden estar vacíos)
    // verificar que los conteos coincidan con el contenido
    assert_eq!(
        reporte.warnings.len(),
        0,
        "fixture mínimo no debe tener warnings"
    );
    assert_eq!(
        reporte.errors.len(),
        0,
        "fixture mínimo no debe tener errors"
    );
}

#[test]
fn test_canonical_line_gate_clasifica_ok_incomplete_inconsistent_y_rejected() {
    let root = temp_repo_root("canonical_line_gate_taxonomy");
    write_minimal_role_contract(&root);
    let input = root.join("data/tmp/candidates.jsonl");
    let complete = complete_canon_line(
        "#### 🌀 Sesión 99 = canonical-line-ok",
        "detalles_de_sesion",
        1,
    );
    let incomplete = r#"{"schema_version":"v0","key":"Nodo incompleto","title":"Nodo incompleto"}"#;
    let inconsistent =
        r#"{"schema_version":"v0","key":"Nodo A","title":"Nodo B","order_in_document":"cero"}"#;
    let rejected = r#"{"schema_version":"v0","id":"PENDIENTE-GENERACION-CONVERTIDOR","key":"Nodo pendiente","title":"Nodo pendiente"}"#;
    write_file(
        &input,
        &format!("{complete}\n{incomplete}\n{inconsistent}\n{rejected}\n"),
    );

    let report = audit_canonical_lines(&root, &input);

    assert_eq!(report.lines_read, 4);
    assert_eq!(report.counts.canon_line_ok, 1);
    assert_eq!(report.counts.canon_line_incomplete, 1);
    assert_eq!(report.counts.canon_line_inconsistent, 1);
    assert_eq!(report.counts.canon_line_rejected, 1);
    assert_eq!(report.role_contract_audit.counts.role_ok, 1);
    assert_eq!(report.role_contract_audit.counts.role_invalid, 0);
    assert_eq!(report.verdict, CanonicalLineVerdict::CanonLineRejected);

    std::fs::remove_dir_all(root).expect("cleanup canonical line taxonomy fixture");
}

#[test]
fn test_canonical_line_gate_detecta_deriva_de_plantilla_por_familia() {
    let root = temp_repo_root("canonical_line_template_drift");
    write_minimal_role_contract(&root);
    let input = root.join("data/tmp/candidates.jsonl");
    let baseline = complete_canon_line("#### 🌀 Sesión 99 = template-a", "detalles_de_sesion", 1);
    let variant = serde_json::json!({
        "schema_version": "v0",
        "id": "123e4567-e89b-12d3-a456-426614174002",
        "key": "#### 🌀 Sesión 99 = template-b",
        "title": "#### 🌀 Sesión 99 = template-b",
        "canonical_slug": "template-b",
        "version_id": "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        "content_type": "text/markdown",
        "modality": "text",
        "encoding": "utf-8",
        "is_binary": false,
        "is_reference_only": false,
        "role_primary": "note",
        "semantic_text": null,
        "mime_type": "text/markdown",
        "document_id": "doc-test",
        "section_path": ["session"],
        "order_in_document": 2,
        "relations": [],
        "source_fields": {"artifact_family": "detalles_de_sesion"},
        "text": "Contenido",
        "source_type": "text/markdown",
        "source_position": "data/out/sessions/test.md.json:2",
        "created": "20260430000000000",
        "modified": "20260430000000000"
    })
    .to_string();
    write_file(&input, &format!("{baseline}\n{variant}\n"));

    let report = audit_canonical_lines(&root, &input);

    assert!(
        report
            .template_families_with_drift
            .iter()
            .any(|family| family.family == "detalles_de_sesion" && family.variant_count == 2),
        "expected detalles_de_sesion template drift, got {:?}",
        report.template_families_with_drift
    );

    std::fs::remove_dir_all(root).expect("cleanup canonical line template drift fixture");
}

#[test]
fn test_canonical_line_gate_reporta_perfiles_y_triage_de_incompletas() {
    let root = temp_repo_root("canonical_line_family_profile");
    write_minimal_role_contract(&root);
    let input = root.join("data/tmp/candidates.jsonl");
    let session_line = complete_canon_line(
        "#### 🌀 Sesión 99 = family-profile-ok",
        "detalles_de_sesion",
        1,
    );
    let asset_without_content = serde_json::json!({
        "schema_version": "v0",
        "id": "123e4567-e89b-12d3-a456-426614174099",
        "key": "asset without content",
        "title": "asset without content",
        "canonical_slug": "asset-without-content",
        "version_id": "sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
        "content_type": "image/png",
        "modality": "image",
        "encoding": "base64",
        "is_binary": true,
        "is_reference_only": false,
        "role_primary": "asset",
        "tags": ["asset:test"],
        "taxonomy_path": ["asset"],
        "semantic_text": null,
        "raw_payload_ref": "node:123e4567-e89b-12d3-a456-426614174099",
        "asset_id": "asset-1",
        "mime_type": "image/png",
        "document_id": "doc-test",
        "section_path": ["assets"],
        "order_in_document": 99,
        "relations": [],
        "source_tags": ["asset:test"],
        "normalized_tags": ["asset:test"],
        "source_fields": {"type": "image/png"},
        "text": "iVBORw0KGgo=",
        "source_type": "image/png",
        "source_position": "html:block0:tiddler99",
        "created": "20260430000000000",
        "modified": "20260430000000000"
    })
    .to_string();
    write_file(
        &input,
        &format!("{session_line}\n{asset_without_content}\n"),
    );

    let report = audit_canonical_lines(&root, &input);

    assert!(report
        .family_profiles
        .iter()
        .any(|profile| profile.family == "detalles_de_sesion"
            && profile.profile_id == "session-artifact-profile-v1"));
    assert!(report
        .family_profiles
        .iter()
        .any(|profile| profile.family == "role:asset"
            && profile.profile_id == "asset-canonical-payload-profile-v1"));
    assert!(report.incomplete_line_triage.iter().any(|triage| {
        triage.family == "role:asset"
            && triage.reason == "asset_without_content_projection"
            && triage.priority == "medium"
            && triage.line_count == 1
    }));

    std::fs::remove_dir_all(root).expect("cleanup canonical line family profile fixture");
}

#[test]
fn test_canonical_line_gate_audita_proyeccion_modal() {
    let root = temp_repo_root("canonical_modal_projection");
    write_minimal_role_contract(&root);
    let input = root.join("data/tmp/candidates.jsonl");
    let asset_projected = serde_json::json!({
        "schema_version": "v0",
        "id": "123e4567-e89b-12d3-a456-426614174101",
        "key": "asset projected",
        "title": "asset projected",
        "canonical_slug": "asset-projected",
        "version_id": "sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
        "content_type": "image/png",
        "modality": "image",
        "encoding": "base64",
        "is_binary": true,
        "is_reference_only": false,
        "role_primary": "asset",
        "tags": ["asset:test"],
        "taxonomy_path": ["asset"],
        "semantic_text": null,
        "content": {
            "projection_kind": "asset",
            "modalities": ["asset"],
            "asset": {
                "asset_id": "asset:123e4567-e89b-12d3-a456-426614174101",
                "mime_type": "image/png",
                "encoding": "base64",
                "payload_ref": "node:123e4567-e89b-12d3-a456-426614174101",
                "payload_present": true,
                "payload_byte_count": 5,
                "payload_sha256": "sha256:2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
            }
        },
        "raw_payload_ref": "node:123e4567-e89b-12d3-a456-426614174101",
        "asset_id": "asset:123e4567-e89b-12d3-a456-426614174101",
        "mime_type": "image/png",
        "document_id": "doc-test",
        "section_path": ["assets"],
        "order_in_document": 1,
        "relations": [],
        "source_tags": ["asset:test"],
        "normalized_tags": ["asset:test"],
        "source_fields": {"type": "image/png"},
        "text": "aGVsbG8=",
        "source_type": "image/png",
        "source_position": "html:block0:tiddler1",
        "created": "20260430000000000",
        "modified": "20260430000000000"
    })
    .to_string();
    let mixed_projected = serde_json::json!({
        "schema_version": "v0",
        "id": "123e4567-e89b-12d3-a456-426614174102",
        "key": "mixed projected",
        "title": "mixed projected",
        "canonical_slug": "mixed-projected",
        "version_id": "sha256:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
        "content_type": "text/markdown",
        "modality": "mixed",
        "encoding": "utf-8",
        "is_binary": false,
        "is_reference_only": false,
        "role_primary": "note",
        "tags": ["note:test"],
        "taxonomy_path": ["note"],
        "semantic_text": null,
        "content": {
            "projection_kind": "mixed",
            "modalities": ["text", "code", "reference"],
            "plain": "Ver paper fmt.Println(\"ok\")",
            "code_blocks": [{"language":"go","text":"fmt.Println(\"ok\")","line_count":1,"byte_count":17,"source":"fenced_code_block:3"}],
            "references": [{"kind":"url","target":"https://example.org","source":"bare_url"}]
        },
        "raw_payload_ref": "node:123e4567-e89b-12d3-a456-426614174102",
        "mime_type": "text/markdown",
        "document_id": "doc-test",
        "section_path": ["notes"],
        "order_in_document": 2,
        "relations": [],
        "source_tags": ["note:test"],
        "normalized_tags": ["note:test"],
        "source_fields": {"type": "text/markdown"},
        "text": "Ver https://example.org\n\n```go\nfmt.Println(\"ok\")\n```",
        "source_type": "text/markdown",
        "source_position": "html:block0:tiddler2",
        "created": "20260430000000000",
        "modified": "20260430000000000"
    })
    .to_string();
    let asset_missing = serde_json::json!({
        "schema_version": "v0",
        "id": "123e4567-e89b-12d3-a456-426614174103",
        "key": "asset missing projection",
        "title": "asset missing projection",
        "canonical_slug": "asset-missing-projection",
        "version_id": "sha256:ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff",
        "content_type": "image/png",
        "modality": "image",
        "encoding": "base64",
        "is_binary": true,
        "is_reference_only": false,
        "role_primary": "asset",
        "tags": ["asset:test"],
        "taxonomy_path": ["asset"],
        "semantic_text": null,
        "raw_payload_ref": "node:123e4567-e89b-12d3-a456-426614174103",
        "asset_id": "asset:123e4567-e89b-12d3-a456-426614174103",
        "mime_type": "image/png",
        "document_id": "doc-test",
        "section_path": ["assets"],
        "order_in_document": 3,
        "relations": [],
        "source_tags": ["asset:test"],
        "normalized_tags": ["asset:test"],
        "source_fields": {"type": "image/png"},
        "text": "aGVsbG8=",
        "source_type": "image/png",
        "source_position": "html:block0:tiddler3",
        "created": "20260430000000000",
        "modified": "20260430000000000"
    })
    .to_string();
    write_file(
        &input,
        &format!("{asset_projected}\n{mixed_projected}\n{asset_missing}\n"),
    );

    let report = audit_canonical_lines(&root, &input);
    let debt = &report.debt_summary;
    assert_eq!(debt.modal_debt_lines, 1);
    assert_eq!(debt.asset_modal_debt_lines, 1);
    assert!(debt.modal_debt_issue_count >= 1);
    let modal = report.modal_projection_audit;

    assert_eq!(modal.inspected_lines, 3);
    assert_eq!(modal.projected_lines, 2);
    assert_eq!(modal.missing_projection_lines, 1);
    assert_eq!(modal.projection_counts.get("asset"), Some(&1));
    assert_eq!(modal.projection_counts.get("code"), Some(&1));
    assert_eq!(modal.projection_counts.get("reference"), Some(&1));
    assert!(modal
        .issues
        .iter()
        .any(|issue| issue.rule_id == "modal-projection-missing"));

    std::fs::remove_dir_all(root).expect("cleanup canonical modal projection fixture");
}

#[test]
fn test_deep_node_inspector_detecta_json_valido_y_recuperable() {
    let root = temp_repo_root("deep_node_json");
    let input = root.join("data/tmp/nodes.jsonl");
    write_file(
        &input,
        r#"{"title":"json valido","text":"{\"id\":\"n1\",\"content\":{\"plain\":\"ok\"}}"}
{"title":"json recuperable","text":"{\"items\":[{\"a\":1} {\"b\":2}]}"}
"#,
    );

    let report = inspect_deep_nodes(&root, &input);

    assert_eq!(report.nodes_read, 2);
    assert_eq!(report.counts.valid_json, 1);
    assert_eq!(report.counts.recoverable_json, 1);
    assert_eq!(report.counts.invalid_json, 0);

    std::fs::remove_dir_all(root).expect("cleanup deep node json fixture");
}

#[test]
fn test_deep_node_inspector_distingue_json_pedagogico_y_fragmento_recuperable() {
    let root = temp_repo_root("deep_node_json_pedagogical");
    let input = root.join("data/tmp/nodes.jsonl");
    write_file(
        &input,
        r#"{"title":"readme example","text":"Ejemplo:\n```json\n{\n  \"id\": \"uuid-v5\", // generado por el convertidor\n  \"title\": \"string\"\n}\n```"}
{"title":"json fragment","text":"```json\n\"meta\": {\"memory_policy\": \"active\"},\n\"memory\": {\"status\": \"active\"}\n```"}
"#,
    );

    let report = inspect_deep_nodes(&root, &input);

    assert_eq!(report.nodes_read, 2);
    assert_eq!(report.counts.pedagogical_json, 1);
    assert_eq!(report.counts.recoverable_json, 1);
    assert_eq!(report.counts.json_fragment, 1);
    assert_eq!(report.counts.invalid_json, 0);
    assert!(report
        .findings
        .iter()
        .any(|finding| finding.status == "pedagogical_json"));
    assert!(report
        .findings
        .iter()
        .any(|finding| finding.status == "recoverable_json_fragment"));

    std::fs::remove_dir_all(root).expect("cleanup deep node json pedagogical fixture");
}

#[test]
fn test_perimetro_minimo_reusable_produce_veredicto_ok() {
    let root = temp_repo_root("perimeter_ok");
    write_minimal_perimeter_fixture(&root);

    let report = audit_perimeter(&root);
    assert_eq!(report.verdict, PerimeterVerdict::Ok);
    assert_eq!(report.errors, 0);
    assert!(report
        .checks
        .iter()
        .any(|check| check.check_id == "seed-main-exists" && check.status == "ok"));
    assert!(report
        .checks
        .iter()
        .any(|check| check.check_id == "registry-derived-noncanonical" && check.status == "ok"));

    std::fs::remove_dir_all(root).expect("cleanup perimeter ok fixture");
}

#[test]
fn test_perimetro_bloquea_sessions_en_raiz() {
    let root = temp_repo_root("perimeter_root_sessions");
    write_minimal_perimeter_fixture(&root);
    std::fs::create_dir_all(root.join("sessions")).expect("root sessions dir");

    let report = audit_perimeter(&root);
    assert_eq!(report.verdict, PerimeterVerdict::Error);
    assert!(report
        .checks
        .iter()
        .any(|check| check.check_id == "no-root-sessions-dir" && check.status == "error"));

    std::fs::remove_dir_all(root).expect("cleanup perimeter root sessions fixture");
}

#[test]
fn test_plan_reconstruccion_staging_desde_html_working_detectado() {
    let root = temp_repo_root("reconstruction_staging");
    write_minimal_perimeter_fixture(&root);
    let source = root.join("data/in/tema-cambiante.html");
    write_file(&source, "<html>working topic</html>");

    let report = audit_reconstruction_plan(
        &root,
        &source,
        ReconstructionSourceRole::Working,
        ReconstructionMode::Staging,
        &root.join("data/tmp/html_export/run-1"),
        false,
        true,
    );

    assert_eq!(report.verdict, ReconstructionPlanVerdict::StagingOnly);
    assert_eq!(report.errors, 0);
    assert!(report
        .checks
        .iter()
        .any(|check| check.check_id == "plan-source-role-coherent" && check.status == "ok"));

    std::fs::remove_dir_all(root).expect("cleanup reconstruction staging fixture");
}

#[test]
fn test_plan_reconstruccion_bloquea_write_local_canon_sin_backup() {
    let root = temp_repo_root("reconstruction_no_backup");
    write_minimal_perimeter_fixture(&root);
    let source = root.join("data/in/tiddly-data-converter (Saved).html");

    let report = audit_reconstruction_plan(
        &root,
        &source,
        ReconstructionSourceRole::Working,
        ReconstructionMode::WriteLocalCanon,
        &root.join("data/out/local"),
        false,
        true,
    );

    assert_eq!(report.verdict, ReconstructionPlanVerdict::Rejected);
    assert!(report
        .checks
        .iter()
        .any(|check| check.check_id == "plan-backup-required" && check.status == "error"));

    std::fs::remove_dir_all(root).expect("cleanup reconstruction no backup fixture");
}

#[test]
fn test_plan_reconstruccion_bloquea_rol_seed_en_html_working() {
    let root = temp_repo_root("reconstruction_role_mismatch");
    write_minimal_perimeter_fixture(&root);
    let source = root.join("data/in/tiddly-data-converter (Saved).html");

    let report = audit_reconstruction_plan(
        &root,
        &source,
        ReconstructionSourceRole::Seed,
        ReconstructionMode::Diagnostic,
        &root.join("data/tmp/reconstruction_plan"),
        false,
        false,
    );

    assert_eq!(report.verdict, ReconstructionPlanVerdict::Rejected);
    assert!(report
        .checks
        .iter()
        .any(|check| check.check_id == "plan-source-role-coherent" && check.status == "error"));

    std::fs::remove_dir_all(root).expect("cleanup reconstruction role mismatch fixture");
}

#[test]
fn test_plan_reconstruccion_write_local_canon_exige_hash_y_backup() {
    let root = temp_repo_root("reconstruction_write_ok");
    write_minimal_perimeter_fixture(&root);
    let source = root.join("data/in/objeto_de_estudio_trazabilidad_y_desarrollo.html");
    write_file(&source, "abc");
    let jsonl = root.join("data/tmp/html_export/export-test/tiddlers.export.jsonl");
    write_file(&jsonl, "abc");
    let abc_hash = "sha256:ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad";
    write_export_manifest(&root, &source, &jsonl, abc_hash, abc_hash);
    let run_dir = root.join("data/tmp/reconstruction/reconstruction-test");

    let report = audit_reconstruction_plan_with_artifacts(
        &root,
        &source,
        ReconstructionSourceRole::Seed,
        ReconstructionMode::WriteLocalCanon,
        &root.join("data/out/local"),
        Some(&jsonl),
        Some(&run_dir),
        true,
        true,
    );

    assert_eq!(report.verdict, ReconstructionPlanVerdict::AllowedWithBackup);
    assert_eq!(report.errors, 0);

    std::fs::remove_dir_all(root).expect("cleanup reconstruction write ok fixture");
}

#[test]
fn test_plan_reconstruccion_rechaza_jsonl_sin_coherencia_html() {
    let root = temp_repo_root("reconstruction_origin_mismatch");
    write_minimal_perimeter_fixture(&root);
    let source = root.join("data/in/tiddly-data-converter (Saved).html");
    write_file(&source, "abc");
    let other_source = root.join("data/in/objeto_de_estudio_trazabilidad_y_desarrollo.html");
    write_file(&other_source, "abc");
    let jsonl = root.join("data/tmp/html_export/export-test/tiddlers.export.jsonl");
    write_file(&jsonl, "abc");
    let abc_hash = "sha256:ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad";
    write_export_manifest(&root, &other_source, &jsonl, abc_hash, abc_hash);
    let run_dir = root.join("data/tmp/reconstruction/reconstruction-test");

    let report = audit_reconstruction_plan_with_artifacts(
        &root,
        &source,
        ReconstructionSourceRole::Working,
        ReconstructionMode::WriteLocalCanon,
        &root.join("data/out/local"),
        Some(&jsonl),
        Some(&run_dir),
        true,
        true,
    );

    assert_eq!(report.verdict, ReconstructionPlanVerdict::Rejected);
    assert!(report.checks.iter().any(
        |check| check.check_id == "plan-input-manifest-source-match" && check.status == "error"
    ));

    std::fs::remove_dir_all(root).expect("cleanup reconstruction origin mismatch fixture");
}

#[test]
fn test_plan_reconstruccion_rechaza_jsonl_legacy_sin_manifiesto() {
    let root = temp_repo_root("reconstruction_legacy_jsonl");
    write_minimal_perimeter_fixture(&root);
    let source = root.join("data/in/tiddly-data-converter (Saved).html");
    let jsonl = root.join("data/tmp/tiddlers.export.jsonl");
    write_file(&jsonl, "abc");
    let run_dir = root.join("data/tmp/reconstruction/reconstruction-test");

    let report = audit_reconstruction_plan_with_artifacts(
        &root,
        &source,
        ReconstructionSourceRole::Working,
        ReconstructionMode::WriteLocalCanon,
        &root.join("data/out/local"),
        Some(&jsonl),
        Some(&run_dir),
        true,
        true,
    );

    assert_eq!(report.verdict, ReconstructionPlanVerdict::Rejected);
    assert!(report
        .checks
        .iter()
        .any(|check| check.check_id == "plan-input-jsonl-scope" && check.status == "error"));

    std::fs::remove_dir_all(root).expect("cleanup reconstruction legacy jsonl fixture");
}

#[test]
fn test_rollback_guiado_valida_backup_y_hash_before() {
    let root = temp_repo_root("reconstruction_rollback_ok");
    write_minimal_perimeter_fixture(&root);
    let backup = root.join("data/tmp/reconstruction/reconstruction-test/canon_before");
    write_file(&backup.join("tiddlers_1.jsonl"), "{}\n");
    let before_hash = canonical_canon_tree_hash(&backup).expect("backup hash");
    let report_path =
        root.join("data/tmp/reconstruction/reconstruction-test/reconstruction-report.json");
    write_file(
        &report_path,
        &format!(
            r#"{{
              "run_id": "reconstruction-test",
              "mode": "write_local_canon",
              "output_target": "data/out/local",
              "backup_dir": "data/tmp/reconstruction/reconstruction-test/canon_before",
              "canon_before_hash": "{}",
              "rollback_ready": true
            }}"#,
            before_hash,
        ),
    );

    let report = audit_reconstruction_rollback(&root, &report_path);

    assert_eq!(report.verdict, ReconstructionRollbackVerdict::Ready);
    assert_eq!(report.errors, 0);
    assert_eq!(
        report.rollback.computed_backup_hash.as_deref(),
        Some(before_hash.as_str())
    );

    std::fs::remove_dir_all(root).expect("cleanup reconstruction rollback ok fixture");
}

#[test]
fn test_rollback_guiado_rechaza_hash_before_ambiguo() {
    let root = temp_repo_root("reconstruction_rollback_hash_mismatch");
    write_minimal_perimeter_fixture(&root);
    let backup = root.join("data/tmp/reconstruction/reconstruction-test/canon_before");
    write_file(&backup.join("tiddlers_1.jsonl"), "{}\n");
    let report_path =
        root.join("data/tmp/reconstruction/reconstruction-test/reconstruction-report.json");
    write_file(
        &report_path,
        r#"{
          "run_id": "reconstruction-test",
          "mode": "write_local_canon",
          "output_target": "data/out/local",
          "backup_dir": "data/tmp/reconstruction/reconstruction-test/canon_before",
          "canon_before_hash": "sha256:0000000000000000000000000000000000000000000000000000000000000000",
          "rollback_ready": true
        }"#,
    );

    let report = audit_reconstruction_rollback(&root, &report_path);

    assert_eq!(report.verdict, ReconstructionRollbackVerdict::Rejected);
    assert!(report.checks.iter().any(|check| check.check_id
        == "rollback-backup-hash-matches-report"
        && check.status == "error"));

    std::fs::remove_dir_all(root).expect("cleanup reconstruction rollback mismatch fixture");
}
