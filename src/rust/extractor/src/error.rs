/// Errores bloqueantes del Extractor HTML.
///
/// Cualquier variante de este enum debe detener el pipeline y emitirse
/// como `status: "error"` en el ExtractionReport con mensaje descriptivo.
///
/// Ref: m01-s01-extractor-contract.md §9
#[derive(Debug)]
pub enum ExtractorError {
    /// El archivo indicado no fue encontrado en la ruta proporcionada.
    FileNotFound(String),

    /// El archivo existe pero no puede leerse (permisos, corrupción, I/O).
    FileNotReadable(String),

    /// El archivo fue leído pero no contiene estructura TiddlyWiki reconocible.
    NotTiddlyWikiHtml(String),

    /// El HTML es TiddlyWiki pero no se encontró ningún tiddler extraíble.
    ZeroTiddlers,

    /// El parseo del HTML falló de forma irrecuperable.
    HtmlParseFatal(String),
}

impl std::fmt::Display for ExtractorError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            ExtractorError::FileNotFound(path) => {
                write!(f, "ERR_FILE_NOT_FOUND: no se encontró el archivo '{}'", path)
            }
            ExtractorError::FileNotReadable(reason) => {
                write!(f, "ERR_FILE_NOT_READABLE: {}", reason)
            }
            ExtractorError::NotTiddlyWikiHtml(reason) => {
                write!(f, "ERR_NOT_TIDDLYWIKI_HTML: {}", reason)
            }
            ExtractorError::ZeroTiddlers => {
                write!(
                    f,
                    "ERR_ZERO_TIDDLERS: el HTML es TiddlyWiki pero no contiene tiddlers extraíbles"
                )
            }
            ExtractorError::HtmlParseFatal(reason) => {
                write!(f, "ERR_HTML_PARSE_FATAL: {}", reason)
            }
        }
    }
}

impl std::error::Error for ExtractorError {}
