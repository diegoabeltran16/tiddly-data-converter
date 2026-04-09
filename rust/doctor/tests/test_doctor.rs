//! Tests de contrato del Doctor / Auditoría mínima.
//!
//! Estos tests son placeholders contractuales que documentan los comportamientos
//! exigidos por `contratos/m01-s04-doctor-contract.md`.
//!
//! Estado: marcados `#[ignore]` hasta que `audit()` tenga implementación real.
//! Cada test incluye el criterio de aceptación que valida (§10 del contrato).
//!
//! Ref: contratos/m01-s04-doctor-contract.md §10

use std::path::Path;
#[allow(unused_imports)]
use tdc_doctor::{audit, DoctorError, DoctorVerdict};

// ---------------------------------------------------------------------------
// Fallos bloqueantes (Err result) — §8 del contrato
// ---------------------------------------------------------------------------

/// §10 criterio: audit() devuelve Err(DoctorError::RawFileNotFound) si la ruta no existe.
#[test]
#[ignore = "pendiente implementación de audit() — m01-s04"]
fn test_archivo_inexistente_produce_error_raw_file_not_found() {
    let ruta = Path::new("/ruta/que/no/existe/raw.tiddlers.json");
    let resultado = audit(ruta);
    assert!(matches!(resultado, Err(DoctorError::RawFileNotFound(_))));
}

/// §10 criterio: audit() devuelve Err(DoctorError::RawNotValidJson) si el contenido no es JSON válido.
#[test]
#[ignore = "pendiente implementación de audit() — m01-s04"]
fn test_json_invalido_produce_error_raw_not_valid_json() {
    // Fixture: archivo con contenido no-JSON.
    // TODO: crear tests/fixtures/raw_tiddlers_invalid.json con contenido: "esto no es json"
    todo!("crear fixture raw_tiddlers_invalid.json")
}

// ---------------------------------------------------------------------------
// Auditoría exitosa (Ok result con verdict) — §10 del contrato
// ---------------------------------------------------------------------------

/// §10 criterio: audit() devuelve Ok(DoctorReport) con verdict Ok ante artefacto estructuralmente correcto.
#[test]
#[ignore = "pendiente implementación de audit() — m01-s04"]
fn test_artefacto_minimo_correcto_produce_veredicto_ok() {
    // Fixture: tests/fixtures/raw_tiddlers_minimal.json — array con tiddlers válidos.
    // TODO: crear fixture raw_tiddlers_minimal.json
    todo!("crear fixture raw_tiddlers_minimal.json")
}

/// §10 criterio: audit() devuelve Ok(DoctorReport) con verdict Warning ante título vacío.
#[test]
#[ignore = "pendiente implementación de audit() — m01-s04"]
fn test_titulo_vacio_produce_veredicto_warning() {
    // Fixture: tiddler con "title": "" — anomalía no bloqueante según §9 caso 3.
    todo!("crear fixture con título vacío")
}

/// §10 criterio: audit() devuelve Ok(DoctorReport) con verdict Error ante tiddler sin campo title.
#[test]
#[ignore = "pendiente implementación de audit() — m01-s04"]
fn test_tiddler_sin_titulo_produce_veredicto_error() {
    // Fixture: tiddler sin campo "title" — fallo de integridad estructural según §9 caso 2.
    todo!("crear fixture con tiddler sin title")
}

/// §10 criterio: DoctorReport siempre incluye tiddler_count, warnings y errors.
#[test]
#[ignore = "pendiente implementación de audit() — m01-s04"]
fn test_reporte_siempre_tiene_campos_minimos() {
    // Verificar que DoctorReport.tiddler_count, warnings y errors están siempre presentes.
    todo!("crear fixture mínimo y verificar estructura del reporte")
}
