/// Veredicto de auditoría del Doctor.
///
/// Determina si el artefacto raw puede continuar el pipeline.
///
/// Ref: contratos/m01-s04-doctor-contract.md §5
#[derive(Debug, PartialEq)]
pub enum DoctorVerdict {
    /// Integridad estructural mínima satisfecha. El pipeline puede continuar hacia Ingesta.
    Ok,

    /// Anomalías no bloqueantes detectadas. El pipeline puede continuar con advertencias registradas.
    Warning,

    /// Fallos de integridad estructural bloqueantes. El Bridge debe detener el pipeline.
    Error,
}

/// Reporte producido por el Doctor tras la auditoría mínima del artefacto raw.
///
/// Siempre se produce cuando `audit()` devuelve `Ok(...)`, independientemente del veredicto.
///
/// Ref: contratos/m01-s04-doctor-contract.md §5, §7 (invariante 2)
#[derive(Debug)]
pub struct DoctorReport {
    /// Veredicto vinculante de la auditoría.
    pub verdict: DoctorVerdict,

    /// Número de tiddlers auditados en el artefacto raw.
    pub tiddler_count: usize,

    /// Anomalías no bloqueantes detectadas durante la auditoría.
    pub warnings: Vec<String>,

    /// Fallos de integridad estructural detectados durante la auditoría.
    pub errors: Vec<String>,
}
