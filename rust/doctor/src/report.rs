use serde::Serialize;
use std::collections::BTreeMap;

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
    #[serde(skip_serializing_if = "Option::is_none")]
    pub input_jsonl_path: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub reconstruction_run_dir: Option<String>,
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

/// Veredicto de la compuerta Rust para rollback guiado de reconstrucción.
#[derive(Debug, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ReconstructionRollbackVerdict {
    Ready,
    Rejected,
}

/// Entrada normalizada de rollback guiado de reconstrucción.
#[derive(Debug, Serialize)]
pub struct ReconstructionRollbackInput {
    pub report_path: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub backup_dir: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub output_target: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub expected_canon_before_hash: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub computed_backup_hash: Option<String>,
}

/// Reporte normativo previo a que Python restaure un backup de reconstrucción.
#[derive(Debug, Serialize)]
pub struct ReconstructionRollbackReport {
    pub verdict: ReconstructionRollbackVerdict,
    pub repo_root: String,
    pub rollback: ReconstructionRollbackInput,
    pub checks_run: usize,
    pub errors: usize,
    pub checks: Vec<PerimeterCheck>,
}

/// Veredicto graduado para una linea canonica o candidata.
///
/// No equivale a admision canonica: clasifica calidad estructural observable
/// para priorizar validacion y reparacion sin escribir el canon.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum CanonicalLineVerdict {
    CanonLineOk,
    CanonLineWarning,
    CanonLineIncomplete,
    CanonLineInconsistent,
    CanonLineRejected,
}

/// Issue puntual detectado por la compuerta de lineas canonicas.
#[derive(Debug, Clone, Serialize)]
pub struct CanonicalLineIssue {
    pub rule_id: String,
    pub severity: String,
    pub impact: CanonicalLineVerdict,
    pub message: String,
}

/// Clasificacion de una linea individual.
#[derive(Debug, Serialize)]
pub struct CanonicalLineItemReport {
    pub source_path: String,
    pub line: usize,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub title: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub role_primary: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub modality: Option<String>,
    pub family: String,
    pub verdict: CanonicalLineVerdict,
    pub field_count: usize,
    #[serde(skip_serializing_if = "Vec::is_empty")]
    pub modal_projections: Vec<String>,
    pub issues: Vec<CanonicalLineIssue>,
}

/// Conteos por veredicto de la compuerta canonica.
#[derive(Debug, Default, Serialize)]
pub struct CanonicalLineCounts {
    pub canon_line_ok: usize,
    pub canon_line_warning: usize,
    pub canon_line_incomplete: usize,
    pub canon_line_inconsistent: usize,
    pub canon_line_rejected: usize,
}

/// Variante de plantilla detectada dentro de una familia de artefactos.
#[derive(Debug, Serialize)]
pub struct TemplateVariantReport {
    pub count: usize,
    pub signature: Vec<String>,
    pub missing_from_baseline: Vec<String>,
    pub extra_vs_baseline: Vec<String>,
    pub examples: Vec<String>,
}

/// Reporte de estabilidad de plantilla por familia.
#[derive(Debug, Serialize)]
pub struct TemplateFamilyReport {
    pub family: String,
    pub verdict: CanonicalLineVerdict,
    pub line_count: usize,
    pub variant_count: usize,
    pub baseline_source: String,
    pub baseline_signature: Vec<String>,
    pub variants: Vec<TemplateVariantReport>,
}

/// Resumen de issues detectados por un perfil focal de familia.
#[derive(Debug, Serialize)]
pub struct FamilyProfileIssueSummary {
    pub rule_id: String,
    pub impact: CanonicalLineVerdict,
    pub count: usize,
    pub examples: Vec<String>,
}

/// Evaluacion focal de una familia priorizada.
#[derive(Debug, Serialize)]
pub struct FamilyProfileReport {
    pub family: String,
    pub profile_id: String,
    pub priority: String,
    pub line_count: usize,
    pub verdict: CanonicalLineVerdict,
    pub issue_count: usize,
    pub issues: Vec<FamilyProfileIssueSummary>,
}

/// Triage accionable de lineas incompletas.
#[derive(Debug, Serialize)]
pub struct IncompleteLineTriageReport {
    pub family: String,
    pub priority: String,
    pub reason: String,
    pub line_count: usize,
    pub rule_ids: Vec<String>,
    pub examples: Vec<String>,
}

/// Issue modal detectado al auditar `content` como proyeccion derivada.
#[derive(Debug, Serialize)]
pub struct ModalProjectionIssueReport {
    pub source_path: String,
    pub line: usize,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub title: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub role_primary: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub modality: Option<String>,
    pub rule_id: String,
    pub severity: String,
    pub message: String,
}

/// Auditoria agregada de la proyeccion modal canonica.
#[derive(Debug, Serialize)]
pub struct ModalProjectionAuditReport {
    pub profile_id: String,
    pub inspected_lines: usize,
    pub relevant_lines: usize,
    pub projected_lines: usize,
    pub missing_projection_lines: usize,
    pub modality_counts: BTreeMap<String, usize>,
    pub projection_counts: BTreeMap<String, usize>,
    pub issues: Vec<ModalProjectionIssueReport>,
}

/// Separacion operacional entre deudas de naturaleza distinta.
#[derive(Debug, Default, Serialize)]
pub struct CanonQualityDebtSummary {
    pub profile_id: String,
    pub modal_debt_lines: usize,
    pub modal_debt_issue_count: usize,
    pub asset_modal_debt_lines: usize,
    pub template_drift_families_total: usize,
    pub template_drift_families_modal_related: usize,
    pub template_drift_families_historical: usize,
    pub template_drift_lines_historical: usize,
    pub richness_warning_lines: usize,
    pub incomplete_line_count: usize,
    pub blocking_line_count: usize,
}

/// Reporte agregado de canonical-line gate.
#[derive(Debug, Serialize)]
pub struct CanonicalLineGateReport {
    pub verdict: CanonicalLineVerdict,
    pub repo_root: String,
    pub input_path: String,
    pub source_files: Vec<String>,
    pub lines_read: usize,
    pub parsed_lines: usize,
    pub counts: CanonicalLineCounts,
    pub template_families_with_drift: Vec<TemplateFamilyReport>,
    pub family_profiles: Vec<FamilyProfileReport>,
    pub incomplete_line_triage: Vec<IncompleteLineTriageReport>,
    pub modal_projection_audit: ModalProjectionAuditReport,
    pub debt_summary: CanonQualityDebtSummary,
    pub lines: Vec<CanonicalLineItemReport>,
}

/// Veredicto agregado del inspector profundo de nodos.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum DeepNodeInspectorVerdict {
    NoStructureFound,
    StructureFound,
    StructureFoundWithWarnings,
}

/// Conteos por tipo de hallazgo del deep-node inspector.
#[derive(Debug, Default, Serialize)]
pub struct DeepNodeFindingCounts {
    pub structural_json: usize,
    pub valid_json: usize,
    pub recoverable_json: usize,
    pub invalid_json: usize,
    pub pedagogical_json: usize,
    pub json_fragment: usize,
    pub json_fence: usize,
    pub yaml_front_matter: usize,
    pub markdown_table: usize,
    pub key_value_block: usize,
}

/// Hallazgo estructural dentro de un nodo.
#[derive(Debug, Serialize)]
pub struct DeepNodeFinding {
    pub source_path: String,
    pub line: usize,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub title: Option<String>,
    pub field: String,
    pub kind: String,
    pub status: String,
    pub byte_count: usize,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub top_level_type: Option<String>,
    #[serde(skip_serializing_if = "Vec::is_empty")]
    pub top_level_keys: Vec<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub array_len: Option<usize>,
    #[serde(skip_serializing_if = "Vec::is_empty")]
    pub recovery_actions: Vec<String>,
    pub message: String,
}

/// Reporte no destructivo sobre riqueza estructural interna de nodos.
#[derive(Debug, Serialize)]
pub struct DeepNodeInspectionReport {
    pub verdict: DeepNodeInspectorVerdict,
    pub repo_root: String,
    pub input_path: String,
    pub source_files: Vec<String>,
    pub nodes_read: usize,
    pub inspected_text_fields: usize,
    pub findings_count: usize,
    pub counts: DeepNodeFindingCounts,
    pub findings: Vec<DeepNodeFinding>,
}
