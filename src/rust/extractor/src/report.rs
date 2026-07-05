use serde::{Deserialize, Serialize};

/// Estado agregado de la operación de extracción.
#[derive(Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum ExtractionStatus {
    /// Todos los tiddlers fueron extraídos sin problemas.
    Ok,
    /// Algunos tiddlers fueron extraídos pero hubo bloques no interpretables.
    Partial,
    /// La extracción falló de forma bloqueante.
    Error,
}

/// Reporte de la operación de extracción.
///
/// Se produce siempre, incluso en caso de fallo parcial o total.
/// Su función es dar observabilidad mínima al pipeline y al debug.
///
/// Ref: m01-s01-extractor-contract.md §5, §8 (Invariante 3)
#[derive(Debug, Serialize, Deserialize)]
pub struct ExtractionReport {
    /// Estado agregado de la extracción.
    pub status: ExtractionStatus,

    /// Número de tiddlers extraídos exitosamente.
    pub tiddler_count: usize,

    /// Advertencias no bloqueantes (campos vacíos, encoding sospechoso, etc.).
    pub warnings: Vec<String>,

    /// Errores bloqueantes o parciales con descripción.
    pub errors: Vec<String>,

    /// Bloques del HTML que no pudieron ser interpretados como tiddlers.
    /// Cada entrada debe contener suficiente información para localizar el bloque.
    pub uninterpretable_blocks: Vec<String>,
}

impl ExtractionReport {
    /// Construye un reporte de error puro (sin tiddlers extraídos).
    pub fn fatal(error_msg: impl Into<String>) -> Self {
        ExtractionReport {
            status: ExtractionStatus::Error,
            tiddler_count: 0,
            warnings: vec![],
            errors: vec![error_msg.into()],
            uninterpretable_blocks: vec![],
        }
    }
}
