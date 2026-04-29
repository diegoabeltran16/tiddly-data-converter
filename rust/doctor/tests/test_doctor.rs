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
    audit, audit_perimeter, audit_reconstruction_plan, DoctorError, DoctorVerdict,
    PerimeterVerdict, ReconstructionMode, ReconstructionPlanVerdict, ReconstructionSourceRole,
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
    std::fs::create_dir_all(root.join("data/sessions")).expect("sessions dir");
    std::fs::create_dir_all(root.join("data/tmp")).expect("tmp dir");
    std::fs::create_dir_all(root.join("data/out/local/reverse_html")).expect("reverse dir");
    write_file(&root.join("data/out/local/tiddlers_1.jsonl"), "{}\n");
    write_file(&root.join("shell_scripts/tdc.sh"), "#!/usr/bin/env bash\n");
    write_file(
        &root.join("README.md"),
        "# tdc\n\n```bash\nshell_scripts/tdc.sh\n```\n",
    );
    write_file(
        &root.join("data/sessions/00_contratos/policy/canon_policy_bundle.json"),
        r#"{
          "local_output_root": "data/out/local",
          "session_semantic_close_default": "data_sessions_staging",
          "reverse_html_root": "data/out/local/reverse_html",
          "direct_canon_write_default": "prohibited_by_default_requires_local_admission"
        }"#,
    );
    write_file(
        &root.join("data/sessions/00_contratos/projections/derived_layers_registry.json"),
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

    let report = audit_reconstruction_plan(
        &root,
        &source,
        ReconstructionSourceRole::Seed,
        ReconstructionMode::WriteLocalCanon,
        &root.join("data/out/local"),
        true,
        true,
    );

    assert_eq!(report.verdict, ReconstructionPlanVerdict::AllowedWithBackup);
    assert_eq!(report.errors, 0);

    std::fs::remove_dir_all(root).expect("cleanup reconstruction write ok fixture");
}
