/// Fallos bloqueantes del Doctor / Auditoría mínima.
///
/// Cualquier variante de este enum detiene el pipeline y se emite como
/// `Err(DoctorError)`. Son distintos de un veredicto `Error` en `DoctorReport`:
/// estos errores impiden que la auditoría siquiera comience.
///
/// Ref: contratos/m01-s04-doctor-contract.md §8
#[derive(Debug)]
pub enum DoctorError {
    /// El archivo raw no fue encontrado en la ruta proporcionada.
    /// Código: ERR_RAW_FILE_NOT_FOUND
    RawFileNotFound(String),

    /// El archivo raw existe pero no puede leerse (permisos, corrupción, I/O).
    /// Código: ERR_RAW_FILE_NOT_READABLE
    RawFileNotReadable(String),

    /// El archivo raw existe y es legible pero no contiene JSON válido.
    /// Código: ERR_RAW_NOT_VALID_JSON
    RawNotValidJson(String),

    /// El JSON es válido pero no es un array de objetos tiddler con estructura mínima reconocible.
    /// Código: ERR_RAW_NOT_TIDDLER_ARRAY
    RawNotTiddlerArray(String),

    /// Fallo en el parseo que impide toda auditoría.
    /// Código: ERR_RAW_PARSE_FATAL
    RawParseFatal(String),
}

impl std::fmt::Display for DoctorError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            DoctorError::RawFileNotFound(path) => {
                write!(f, "ERR_RAW_FILE_NOT_FOUND: no se encontró el archivo '{}'", path)
            }
            DoctorError::RawFileNotReadable(reason) => {
                write!(f, "ERR_RAW_FILE_NOT_READABLE: {}", reason)
            }
            DoctorError::RawNotValidJson(reason) => {
                write!(f, "ERR_RAW_NOT_VALID_JSON: {}", reason)
            }
            DoctorError::RawNotTiddlerArray(reason) => {
                write!(f, "ERR_RAW_NOT_TIDDLER_ARRAY: {}", reason)
            }
            DoctorError::RawParseFatal(reason) => {
                write!(f, "ERR_RAW_PARSE_FATAL: {}", reason)
            }
        }
    }
}

impl std::error::Error for DoctorError {}
