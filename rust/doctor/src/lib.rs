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
/// Ref: contratos/m01-s04-doctor-contract.md §5, §7
pub fn audit(_raw_path: &Path) -> Result<DoctorReport, DoctorError> {
    todo!("Doctor audit — implementación pendiente (m01-s04)")
}
