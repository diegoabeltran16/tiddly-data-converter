//! Tests de contrato del Doctor / Auditoría mínima.
//!
//! Estos tests validan los comportamientos exigidos por
//! `contratos/m01-s04-doctor-contract.md`.
//!
//! Activados en m01-s10 con la implementación real de `audit()`.
//! Cada test incluye el criterio de aceptación que valida (§10 del contrato).
//!
//! Ref: contratos/m01-s04-doctor-contract.md §10

use std::path::Path;
use tdc_doctor::{audit, DoctorError, DoctorVerdict};

/// Ruta base a los fixtures compartidos del repositorio.
fn fixtures_dir() -> std::path::PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../../tests/fixtures")
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
    assert!(resultado.errors.is_empty(), "no debe haber errores: {:?}", resultado.errors);
}

/// §10 criterio: audit() devuelve Ok(DoctorReport) con verdict Warning ante título vacío.
#[test]
fn test_titulo_vacio_produce_veredicto_warning() {
    let ruta = fixtures_dir().join("raw_tiddlers_empty_title.json");
    let resultado = audit(&ruta).expect("audit() debería devolver Ok para fixture con título vacío");
    assert_eq!(
        resultado.verdict,
        DoctorVerdict::Warning,
        "se esperaba veredicto Warning, se obtuvo: {:?}",
        resultado.verdict
    );
    assert!(resultado.errors.is_empty(), "no debe haber errores bloqueantes: {:?}", resultado.errors);
    assert!(!resultado.warnings.is_empty(), "debe haber al menos un warning");
}

/// §10 criterio: audit() devuelve Ok(DoctorReport) con verdict Error ante tiddler sin campo title.
#[test]
fn test_tiddler_sin_titulo_produce_veredicto_error() {
    let ruta = fixtures_dir().join("raw_tiddlers_no_title.json");
    let resultado = audit(&ruta).expect("audit() debería devolver Ok incluso con errores de integridad");
    assert_eq!(
        resultado.verdict,
        DoctorVerdict::Error,
        "se esperaba veredicto Error, se obtuvo: {:?}",
        resultado.verdict
    );
    assert!(!resultado.errors.is_empty(), "debe haber al menos un error de integridad");
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
