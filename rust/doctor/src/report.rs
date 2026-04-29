use serde::Serialize;

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

/// Veredicto del perímetro Rust del repositorio.
///
/// Este veredicto no reemplaza `canon_preflight`; solo confirma invariantes
/// estructurales de autoridad, entradas y capas antes de operar el pipeline.
#[derive(Debug, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum PerimeterVerdict {
    Ok,
    Error,
}

/// Resultado individual de un chequeo de perímetro.
#[derive(Debug, Serialize)]
pub struct PerimeterCheck {
    pub check_id: String,
    pub status: String,
    pub message: String,
}

/// Reporte de perímetro reusable del repositorio.
#[derive(Debug, Serialize)]
pub struct PerimeterReport {
    pub verdict: PerimeterVerdict,
    pub repo_root: String,
    pub checks_run: usize,
    pub errors: usize,
    pub checks: Vec<PerimeterCheck>,
}

/// Rol declarado de una fuente HTML de reconstrucción.
#[derive(Debug, Clone, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ReconstructionSourceRole {
    Seed,
    Working,
    BootstrapAux,
}

/// Modo solicitado para una operación de reconstrucción.
#[derive(Debug, Clone, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ReconstructionMode {
    Diagnostic,
    Staging,
    WriteLocalCanon,
    ReverseProjection,
}

/// Veredicto normativo de un plan de reconstrucción.
#[derive(Debug, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ReconstructionPlanVerdict {
    Allowed,
    AllowedWithBackup,
    StagingOnly,
    Rejected,
}

/// Entrada normalizada del plan de reconstrucción.
#[derive(Debug, Serialize)]
pub struct ReconstructionPlanInput {
    pub source_html_path: String,
    pub source_role: ReconstructionSourceRole,
    pub reconstruction_mode: ReconstructionMode,
    pub output_target: String,
    pub requires_backup: bool,
    pub requires_hash_report: bool,
}

/// Reporte normativo previo a ejecutar reconstrucción, shardización o reverse.
#[derive(Debug, Serialize)]
pub struct ReconstructionPlanReport {
    pub verdict: ReconstructionPlanVerdict,
    pub repo_root: String,
    pub plan: ReconstructionPlanInput,
    pub checks_run: usize,
    pub errors: usize,
    pub checks: Vec<PerimeterCheck>,
}
