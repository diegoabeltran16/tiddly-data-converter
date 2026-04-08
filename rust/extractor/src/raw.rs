use std::collections::HashMap;
use serde::{Deserialize, Serialize};

/// Representa un tiddler extraído del HTML vivo de TiddlyWiki en su forma raw,
/// sin normalización ni interpretación semántica.
///
/// Invariante: `raw_fields` y `raw_text` reflejan exactamente lo que aparece
/// en el HTML fuente; ningún campo se modifica durante la extracción.
///
/// Ref: m01-s01-extractor-contract.md §5, §8 (Invariante 1)
#[derive(Debug, Serialize, Deserialize)]
pub struct RawTiddler {
    /// Título del tiddler, preservado sin modificación.
    pub title: String,

    /// Todos los campos del tiddler preservados como mapa de strings.
    /// Includes `created`, `modified`, `tags`, `type`, y otros campos
    /// arbitrarios declarados en el HTML fuente.
    pub raw_fields: HashMap<String, String>,

    /// Contenido textual del tiddler (`text` field), preservado sin modificación.
    /// None si el tiddler no tiene campo `text` declarado.
    pub raw_text: Option<String>,

    /// Posición de origen dentro del HTML para trazabilidad y debug.
    /// Provisional: puede ser índice de bloque, offset u otro identificador.
    /// Se cerrará en m01-s02 una vez inspeccionado el fixture real.
    pub source_position: Option<String>,
}
