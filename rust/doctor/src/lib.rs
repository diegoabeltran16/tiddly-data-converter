//! # tdc-doctor
//!
//! Doctor / Auditoría mínima para tiddly-data-converter.
//!
//! **Zona arquitectónica:** Extracción e Inspección
//! **Ownership técnico dominante:** Rust
//! **Pipeline:** raw.tiddlers.json → DoctorReport (veredicto + detalle)
//!
//! ## Responsabilidad
//!
//! Este crate recibe el artefacto raw producido por el Extractor HTML,
//! evalúa su integridad estructural mínima y emite un veredicto vinculante
//! (`ok`, `warning`, `error`) que el Bridge usa para decidir si el pipeline
//! puede continuar hacia la Ingesta.
//!
//! ## Lo que este crate NO hace
//!
//! - No canoniza ni asigna UUIDs canónicos.
//! - No normaliza campos, tags ni contenido textual.
//! - No valida integridad semántica de dominio (eso es la Ingesta / Canon).
//! - No modifica el artefacto raw recibido.
//! - No ejecuta reverse ni depende de la zona Canon/Reversibilidad.
//! - No reemplaza el esquema del Canon ni absorbe la lógica del núcleo.
//! - No retiene estado entre ejecuciones.
//!
//! Ref: contratos/m01-s04-doctor-contract.md

pub mod error;
pub mod report;

use std::path::Path;

pub use error::DoctorError;
pub use report::{DoctorReport, DoctorVerdict};

/// Audita la integridad estructural mínima del artefacto raw producido por el Extractor HTML.
///
/// # Contrato
///
/// - Recibe la ruta local de `raw.tiddlers.json`.
/// - Produce `DoctorReport` con veredicto en caso de auditoría completable.
/// - Produce `DoctorError` en caso de fallo que impide toda auditoría.
///
/// # Veredictos
///
/// - `DoctorVerdict::Ok`      — integridad estructural mínima satisfecha; el pipeline puede continuar.
/// - `DoctorVerdict::Warning` — anomalías no bloqueantes detectadas; el pipeline puede continuar con advertencias.
/// - `DoctorVerdict::Error`   — fallos de integridad estructural bloqueantes; el pipeline debe detenerse.
///
/// # Fallos bloqueantes (`Err`)
///
/// - `DoctorError::RawFileNotFound`    — la ruta no existe.
/// - `DoctorError::RawFileNotReadable` — el archivo existe pero no puede leerse.
/// - `DoctorError::RawNotValidJson`    — el contenido no es JSON válido.
/// - `DoctorError::RawNotTiddlerArray` — el JSON no es un array de objetos tiddler.
///
/// Ref: contratos/m01-s04-doctor-contract.md §5, §7, §8
pub fn audit(raw_path: &Path) -> Result<DoctorReport, DoctorError> {
    // §8: archivo no encontrado
    if !raw_path.exists() {
        return Err(DoctorError::RawFileNotFound(
            raw_path.to_string_lossy().to_string(),
        ));
    }

    // §8: archivo no legible
    let content = std::fs::read_to_string(raw_path).map_err(|e| {
        DoctorError::RawFileNotReadable(format!(
            "'{}': {}",
            raw_path.to_string_lossy(),
            e
        ))
    })?;

    // §8: JSON inválido
    let value: serde_json::Value = serde_json::from_str(&content).map_err(|e| {
        DoctorError::RawNotValidJson(format!(
            "'{}': {}",
            raw_path.to_string_lossy(),
            e
        ))
    })?;

    // §8: no es array JSON de objetos tiddler
    let array = match value {
        serde_json::Value::Array(arr) => arr,
        _ => {
            return Err(DoctorError::RawNotTiddlerArray(format!(
                "'{}': se esperaba array JSON, se encontró {}",
                raw_path.to_string_lossy(),
                json_type_name(&value)
            )))
        }
    };

    let mut warnings: Vec<String> = Vec::new();
    let mut errors: Vec<String> = Vec::new();

    // §9 caso 1: array vacío — anomalía no bloqueante
    if array.is_empty() {
        warnings.push("WARN_EMPTY_ARRAY: el artefacto raw no contiene tiddlers".to_string());
    }

    // Auditoría estructural mínima de cada elemento
    for (i, item) in array.iter().enumerate() {
        let obj = match item {
            serde_json::Value::Object(o) => o,
            _ => {
                return Err(DoctorError::RawNotTiddlerArray(format!(
                    "elemento [{}] no es un objeto JSON",
                    i
                )))
            }
        };

        // §9 caso 2: tiddler sin campo title → error bloqueante
        // §9 caso 3: tiddler con title vacío → warning
        match obj.get("title") {
            None => {
                errors.push(format!(
                    "ERR_MISSING_TITLE: tiddler[{}] no tiene campo 'title'",
                    i
                ));
            }
            Some(serde_json::Value::String(s)) if s.is_empty() => {
                warnings.push(format!(
                    "WARN_EMPTY_TITLE: tiddler[{}] tiene campo 'title' vacío",
                    i
                ));
            }
            Some(serde_json::Value::String(_)) => {
                // título válido — ok
            }
            Some(other) => {
                errors.push(format!(
                    "ERR_INVALID_TITLE: tiddler[{}] campo 'title' no es string: {}",
                    i,
                    json_type_name(other)
                ));
            }
        }

        // §9 caso 4: raw_fields ausente → error bloqueante (prometido por contrato Extractor)
        match obj.get("raw_fields") {
            None => {
                errors.push(format!(
                    "ERR_MISSING_RAW_FIELDS: tiddler[{}] no tiene campo 'raw_fields'",
                    i
                ));
            }
            Some(serde_json::Value::Object(_)) => {
                // raw_fields presente y es objeto — ok
            }
            Some(other) => {
                errors.push(format!(
                    "ERR_INVALID_RAW_FIELDS: tiddler[{}] campo 'raw_fields' no es objeto: {}",
                    i,
                    json_type_name(other)
                ));
            }
        }

        // §9 caso 5: raw_text y source_position son opcionales — se toleran sin error
        // §9 caso 6: campos extra no declarados — se ignoran
    }

    // Veredicto: determinado por el peor hallazgo
    let verdict = if !errors.is_empty() {
        DoctorVerdict::Error
    } else if !warnings.is_empty() {
        DoctorVerdict::Warning
    } else {
        DoctorVerdict::Ok
    };

    Ok(DoctorReport {
        verdict,
        tiddler_count: array.len(),
        warnings,
        errors,
    })
}

/// Devuelve el nombre del tipo JSON de un valor, para mensajes de error.
fn json_type_name(v: &serde_json::Value) -> &'static str {
    match v {
        serde_json::Value::Null => "null",
        serde_json::Value::Bool(_) => "boolean",
        serde_json::Value::Number(_) => "number",
        serde_json::Value::String(_) => "string",
        serde_json::Value::Array(_) => "array",
        serde_json::Value::Object(_) => "object",
    }
}
