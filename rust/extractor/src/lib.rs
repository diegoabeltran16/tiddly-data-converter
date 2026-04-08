//! # tdc-extractor
//!
//! Extractor HTML para tiddly-data-converter.
//!
//! **Zona arquitectónica:** Extracción e Inspección
//! **Ownership técnico dominante:** Rust
//! **Pipeline:** HTML vivo de TiddlyWiki → raw.tiddlers.json + extraction_report
//!
//! ## Responsabilidad
//!
//! Este crate lee un archivo HTML vivo de TiddlyWiki indicado por ruta,
//! localiza las unidades válidas (tiddlers reales), separa señal de ruido
//! y produce un artefacto raw lossless para que el Doctor lo inspeccione.
//!
//! ## Lo que este crate NO hace
//!
//! - No asigna UUIDs canónicos.
//! - No normaliza campos ni etiquetas.
//! - No valida integridad semántica (eso es el Doctor).
//! - No ejecuta reverse ni escribe en el Canon JSONL.
//! - No retiene estado entre ejecuciones.
//!
//! Ref: m01-s01-extractor-contract.md

pub mod error;
pub mod raw;
pub mod report;

use std::collections::HashMap;
use std::path::Path;

pub use error::ExtractorError;
pub use raw::RawTiddler;
pub use report::{ExtractionReport, ExtractionStatus};

/// Marcador de apertura del bloque de datos del tiddler store en TiddlyWiki 5.x.
/// Confirmado inspeccionando TiddlyWiki 5.3.6 (m01-s02 Momento B).
const CONTAINER_OPEN: &str =
    r#"<script class="tiddlywiki-tiddler-store" type="application/json">"#;

/// Marcador de cierre del bloque del tiddler store.
const CONTAINER_CLOSE: &str = "</script>";

/// Extrae los tiddlers de un archivo HTML vivo de TiddlyWiki.
///
/// # Contrato
///
/// - Recibe la ruta local del archivo HTML.
/// - Produce `(Vec<RawTiddler>, ExtractionReport)` en caso de éxito total o parcial.
/// - Produce `ExtractorError` en caso de fallo bloqueante.
/// - Siempre que retorne `Err`, también está disponible el log del error en el
///   `Display` impl de `ExtractorError`.
///
/// # Errores bloqueantes
///
/// - `ExtractorError::FileNotFound` — el archivo no existe.
/// - `ExtractorError::FileNotReadable` — el archivo no puede leerse.
/// - `ExtractorError::NotTiddlyWikiHtml` — no se detectó estructura TiddlyWiki.
/// - `ExtractorError::ZeroTiddlers` — TiddlyWiki detectado pero sin tiddlers.
/// - `ExtractorError::HtmlParseFatal` — fallo irrecuperable del parseo.
///
/// Ref: m01-s01-extractor-contract.md §3–§9
pub fn extract(
    html_path: &Path,
) -> Result<(Vec<RawTiddler>, ExtractionReport), ExtractorError> {
    // 1. Verificar existencia del archivo
    if !html_path.exists() {
        return Err(ExtractorError::FileNotFound(
            html_path.to_string_lossy().into_owned(),
        ));
    }

    // 2. Leer el archivo en memoria
    let content = std::fs::read_to_string(html_path).map_err(|e| {
        ExtractorError::FileNotReadable(format!(
            "no se pudo leer '{}': {}",
            html_path.display(),
            e
        ))
    })?;

    // 3. Localizar el bloque del tiddler store
    //    TiddlyWiki 5.x serializa todos los tiddlers dentro de un único
    //    <script class="tiddlywiki-tiddler-store" type="application/json"> [...] </script>.
    //    La búsqueda de marcador literal es suficiente y no requiere parser HTML.
    let store_start = match content.find(CONTAINER_OPEN) {
        Some(pos) => pos + CONTAINER_OPEN.len(),
        None => {
            return Err(ExtractorError::NotTiddlyWikiHtml(format!(
                "no se encontró el contenedor tiddlywiki-tiddler-store en '{}'",
                html_path.display()
            )));
        }
    };

    let store_end = match content[store_start..].find(CONTAINER_CLOSE) {
        Some(pos) => store_start + pos,
        None => {
            return Err(ExtractorError::HtmlParseFatal(format!(
                "contenedor tiddlywiki-tiddler-store sin cierre </script> en '{}'",
                html_path.display()
            )));
        }
    };

    let json_str = &content[store_start..store_end];

    // 4. Parsear el array JSON del tiddler store
    let raw_values: Vec<serde_json::Map<String, serde_json::Value>> =
        serde_json::from_str(json_str).map_err(|e| {
            ExtractorError::HtmlParseFatal(format!(
                "error parseando JSON del tiddler-store en '{}': {}",
                html_path.display(),
                e
            ))
        })?;

    // 5. Verificar que hay al menos un tiddler
    if raw_values.is_empty() {
        return Err(ExtractorError::ZeroTiddlers);
    }

    // 6. Mapear cada objeto JSON a RawTiddler
    //    Los tiddlers sin campo 'title' se omiten con advertencia (no son bloqueantes).
    //    Todos los valores de campo en TW5 son strings; si por algún plugin no lo fueran,
    //    se serializa el valor JSON como fallback para no perder datos.
    let mut tiddlers: Vec<RawTiddler> = Vec::with_capacity(raw_values.len());
    let mut warnings: Vec<String> = Vec::new();

    for (index, obj) in raw_values.into_iter().enumerate() {
        let title = match obj.get("title").and_then(|v| v.as_str()) {
            Some(t) => t.to_owned(),
            None => {
                warnings.push(format!(
                    "tiddler en posición {} no tiene campo 'title', omitido",
                    index
                ));
                continue;
            }
        };

        let raw_text = obj
            .get("text")
            .and_then(|v| v.as_str())
            .map(|s| s.to_owned());

        let mut raw_fields: HashMap<String, String> = HashMap::new();
        for (k, v) in &obj {
            let str_val = v
                .as_str()
                .map(|s| s.to_owned())
                .unwrap_or_else(|| v.to_string());
            raw_fields.insert(k.clone(), str_val);
        }

        tiddlers.push(RawTiddler {
            title,
            raw_fields,
            raw_text,
            source_position: Some(format!("tiddler-store:{}", index)),
        });
    }

    let status = if warnings.is_empty() {
        ExtractionStatus::Ok
    } else {
        ExtractionStatus::Partial
    };

    let report = ExtractionReport {
        tiddler_count: tiddlers.len(),
        status,
        warnings,
        errors: vec![],
        uninterpretable_blocks: vec![],
    };

    Ok((tiddlers, report))
}
