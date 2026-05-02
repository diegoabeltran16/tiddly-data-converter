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
//! - No ejecuta reverse ni canoniza; solo audita perímetro y planes cuando se invoca como compuerta.
//! - No reemplaza el esquema del Canon ni absorbe la lógica del núcleo.
//! - No retiene estado entre ejecuciones.
//!
//! Ref: contratos/m01-s04-doctor-contract.md

pub mod canon_quality;
pub mod error;
pub mod report;

use std::path::{Path, PathBuf};

pub use canon_quality::{audit_canonical_lines, inspect_deep_nodes};
pub use error::DoctorError;
pub use report::{
    CanonQualityDebtSummary, CanonicalLineCounts, CanonicalLineGateReport, CanonicalLineIssue,
    CanonicalLineItemReport, CanonicalLineVerdict, DeepNodeFinding, DeepNodeFindingCounts,
    DeepNodeInspectionReport, DeepNodeInspectorVerdict, DoctorReport, DoctorVerdict,
    FamilyProfileIssueSummary, FamilyProfileReport, IncompleteLineTriageReport,
    ModalProjectionAuditReport, ModalProjectionIssueReport, PerimeterCheck, PerimeterReport,
    PerimeterVerdict, ReconstructionMode, ReconstructionPlanInput, ReconstructionPlanReport,
    ReconstructionPlanVerdict, ReconstructionRollbackInput, ReconstructionRollbackReport,
    ReconstructionRollbackVerdict, ReconstructionSourceRole, TemplateFamilyReport,
    TemplateVariantReport,
};

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
        DoctorError::RawFileNotReadable(format!("'{}': {}", raw_path.to_string_lossy(), e))
    })?;

    // §8: JSON inválido
    let value: serde_json::Value = serde_json::from_str(&content).map_err(|e| {
        DoctorError::RawNotValidJson(format!("'{}': {}", raw_path.to_string_lossy(), e))
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

/// Audita el perímetro reusable del repositorio sin modificar archivos.
///
/// Este chequeo inaugura el perímetro del futuro kernel Rust: valida que las
/// superficies de entrada, canon, reverse, sesiones y derivados conserven su
/// autoridad declarada antes de operar el menú local.
pub fn audit_perimeter(repo_root: &Path) -> PerimeterReport {
    let root = repo_root;
    let mut checks: Vec<PerimeterCheck> = Vec::new();

    push_path_check(
        &mut checks,
        root,
        "seed-main-exists",
        "data/in/objeto_de_estudio_trazabilidad_y_desarrollo.html",
        ExpectedPathKind::File,
        "semilla reusable principal de tema",
    );
    push_path_check(
        &mut checks,
        root,
        "seed-empty-store-auxiliary-exists",
        "data/in/empty-store.html",
        ExpectedPathKind::File,
        "superficie auxiliar de arranque, no semilla madre",
    );
    check_working_html_surfaces(root, &mut checks);
    push_path_check(
        &mut checks,
        root,
        "sessions-staging-exists",
        "data/sessions",
        ExpectedPathKind::Dir,
        "staging operativo de sesiones",
    );
    push_path_check(
        &mut checks,
        root,
        "canon-local-exists",
        "data/out/local",
        ExpectedPathKind::Dir,
        "canon local oficial",
    );
    push_path_check(
        &mut checks,
        root,
        "reverse-html-projection-exists",
        "data/out/local/reverse_html",
        ExpectedPathKind::Dir,
        "reverse_html es proyección no autoritativa",
    );
    push_path_check(
        &mut checks,
        root,
        "tmp-workspace-exists",
        "data/tmp",
        ExpectedPathKind::Dir,
        "zona temporal de reportes y artefactos intermedios",
    );
    push_path_check(
        &mut checks,
        root,
        "operator-wrapper-exists",
        "shell_scripts/tdc.sh",
        ExpectedPathKind::File,
        "único wrapper operativo público",
    );

    let root_sessions = root.join("sessions");
    if root_sessions.exists() {
        push_error(
            &mut checks,
            "no-root-sessions-dir",
            "sessions/ en raíz existe; la ruta oficial es data/sessions",
        );
    } else {
        push_ok(
            &mut checks,
            "no-root-sessions-dir",
            "no existe sessions/ en raíz",
        );
    }

    let seed = root.join("data/in/objeto_de_estudio_trazabilidad_y_desarrollo.html");
    let empty = root.join("data/in/empty-store.html");
    if seed == empty {
        push_error(
            &mut checks,
            "main-seed-not-empty-store",
            "la semilla principal no puede ser empty-store.html",
        );
    } else {
        push_ok(
            &mut checks,
            "main-seed-not-empty-store",
            "objeto_de_estudio_trazabilidad_y_desarrollo.html y empty-store.html son superficies distintas",
        );
    }

    check_canon_shards(root, &mut checks);
    check_policy_bundle(root, &mut checks);
    check_derived_registry(root, &mut checks);
    check_readme_single_operator(root, &mut checks);

    let errors = checks
        .iter()
        .filter(|check| check.status == "error")
        .count();
    let verdict = if errors == 0 {
        PerimeterVerdict::Ok
    } else {
        PerimeterVerdict::Error
    };

    PerimeterReport {
        verdict,
        repo_root: root.to_string_lossy().to_string(),
        checks_run: checks.len(),
        errors,
        checks,
    }
}

/// Audita un plan de reconstrucción antes de que el menú ejecute extracción,
/// shardización o reverse.
///
/// Rust no reconstruye el canon en S72. Solo emite un veredicto normativo sobre
/// la intención operacional: fuente HTML explícita, rol declarado, modo,
/// destino y evidencias mínimas de backup/hash cuando el plan puede tocar el
/// canon local.
pub fn audit_reconstruction_plan(
    repo_root: &Path,
    source_html_path: &Path,
    source_role: ReconstructionSourceRole,
    reconstruction_mode: ReconstructionMode,
    output_target: &Path,
    requires_backup: bool,
    requires_hash_report: bool,
) -> ReconstructionPlanReport {
    audit_reconstruction_plan_with_artifacts(
        repo_root,
        source_html_path,
        source_role,
        reconstruction_mode,
        output_target,
        None,
        None,
        requires_backup,
        requires_hash_report,
    )
}

/// Audita un plan de reconstrucción con artefactos operativos concretos.
///
/// Esta variante se usa cuando el menú ya seleccionó un JSONL temporal o un
/// run directory de reconstrucción. Rust no ejecuta shardización ni reverse:
/// valida que la procedencia HTML -> JSONL esté demostrada por manifiesto y
/// que el espacio de evidencia viva bajo `data/tmp/reconstruction/`.
pub fn audit_reconstruction_plan_with_artifacts(
    repo_root: &Path,
    source_html_path: &Path,
    source_role: ReconstructionSourceRole,
    reconstruction_mode: ReconstructionMode,
    output_target: &Path,
    input_jsonl_path: Option<&Path>,
    reconstruction_run_dir: Option<&Path>,
    requires_backup: bool,
    requires_hash_report: bool,
) -> ReconstructionPlanReport {
    let root = repo_root;
    let mut checks: Vec<PerimeterCheck> = Vec::new();
    let source = resolve_plan_path(root, source_html_path);
    let target = resolve_plan_path(root, output_target);
    let input_jsonl = input_jsonl_path.map(|path| resolve_plan_path(root, path));
    let run_dir = reconstruction_run_dir.map(|path| resolve_plan_path(root, path));
    let data_in = root.join("data/in");
    let data_tmp = root.join("data/tmp");
    let html_export_dir = root.join("data/tmp/html_export");
    let reconstruction_dir = root.join("data/tmp/reconstruction");
    let canon_dir = root.join("data/out/local");
    let reverse_html_dir = root.join("data/out/local/reverse_html");

    check_source_html(root, &source, &source_role, &mut checks);
    check_reconstruction_target(
        &target,
        &data_tmp,
        &canon_dir,
        &reverse_html_dir,
        &reconstruction_mode,
        &mut checks,
    );
    check_reconstruction_run_dir(
        root,
        run_dir.as_deref(),
        &reconstruction_dir,
        &reconstruction_mode,
        &mut checks,
    );
    check_input_jsonl_origin(
        root,
        &source,
        input_jsonl.as_deref(),
        &html_export_dir,
        &reconstruction_mode,
        &mut checks,
    );

    if source == target {
        push_error(
            &mut checks,
            "plan-source-target-distinct",
            "source_html_path y output_target no pueden ser la misma ruta",
        );
    } else {
        push_ok(
            &mut checks,
            "plan-source-target-distinct",
            "source_html_path y output_target son rutas distintas",
        );
    }

    if path_has_parent_component(source_html_path)
        || path_has_parent_component(output_target)
        || input_jsonl_path
            .map(path_has_parent_component)
            .unwrap_or(false)
        || reconstruction_run_dir
            .map(path_has_parent_component)
            .unwrap_or(false)
    {
        push_error(
            &mut checks,
            "plan-no-parent-path-components",
            "el plan no acepta rutas con componentes '..'",
        );
    } else {
        push_ok(
            &mut checks,
            "plan-no-parent-path-components",
            "el plan no usa componentes '..'",
        );
    }

    if !path_under(&source, &data_in) {
        push_error(
            &mut checks,
            "plan-source-under-data-in",
            "source_html_path debe estar bajo data/in",
        );
    } else {
        push_ok(
            &mut checks,
            "plan-source-under-data-in",
            "source_html_path esta bajo data/in",
        );
    }

    match reconstruction_mode {
        ReconstructionMode::WriteLocalCanon => {
            if requires_backup {
                push_ok(
                    &mut checks,
                    "plan-backup-required",
                    "write_local_canon declara backup previo",
                );
            } else {
                push_error(
                    &mut checks,
                    "plan-backup-required",
                    "write_local_canon requiere backup previo",
                );
            }
            if requires_hash_report {
                push_ok(
                    &mut checks,
                    "plan-hash-report-required",
                    "write_local_canon declara reporte de hash before/after",
                );
            } else {
                push_error(
                    &mut checks,
                    "plan-hash-report-required",
                    "write_local_canon requiere reporte de hash before/after",
                );
            }
            push_ok(
                &mut checks,
                "plan-post-reconstruction-evidence",
                "el plan debe validarse despues con strict, reverse-preflight y Rejected: 0 cuando aplique",
            );
        }
        ReconstructionMode::Staging => {
            if requires_backup {
                push_error(
                    &mut checks,
                    "plan-staging-no-canon-backup",
                    "staging no debe declarar backup de canon porque no escribe data/out/local",
                );
            } else {
                push_ok(
                    &mut checks,
                    "plan-staging-no-canon-backup",
                    "staging no declara backup de canon",
                );
            }
            if requires_hash_report {
                push_ok(
                    &mut checks,
                    "plan-staging-hash-evidence",
                    "staging declara evidencia de hash/manifest",
                );
            } else {
                push_error(
                    &mut checks,
                    "plan-staging-hash-evidence",
                    "staging debe producir evidencia de hash/manifest",
                );
            }
        }
        ReconstructionMode::ReverseProjection => {
            if requires_backup {
                push_error(
                    &mut checks,
                    "plan-reverse-no-canon-backup",
                    "reverse_projection no debe declarar backup de canon porque no escribe shards",
                );
            } else {
                push_ok(
                    &mut checks,
                    "plan-reverse-no-canon-backup",
                    "reverse_projection no declara backup de canon",
                );
            }
            if requires_hash_report {
                push_ok(
                    &mut checks,
                    "plan-reverse-report-evidence",
                    "reverse_projection declara reporte de salida/reverse",
                );
            } else {
                push_error(
                    &mut checks,
                    "plan-reverse-report-evidence",
                    "reverse_projection debe conservar reporte de salida/reverse",
                );
            }
        }
        ReconstructionMode::Diagnostic => {
            if requires_backup {
                push_error(
                    &mut checks,
                    "plan-diagnostic-no-canon-backup",
                    "diagnostic no debe declarar backup de canon",
                );
            } else {
                push_ok(
                    &mut checks,
                    "plan-diagnostic-no-canon-backup",
                    "diagnostic no declara backup de canon",
                );
            }
        }
    }

    let errors = checks
        .iter()
        .filter(|check| check.status == "error")
        .count();
    let verdict = if errors > 0 {
        ReconstructionPlanVerdict::Rejected
    } else {
        match reconstruction_mode {
            ReconstructionMode::WriteLocalCanon => ReconstructionPlanVerdict::AllowedWithBackup,
            ReconstructionMode::Staging => ReconstructionPlanVerdict::StagingOnly,
            ReconstructionMode::Diagnostic | ReconstructionMode::ReverseProjection => {
                ReconstructionPlanVerdict::Allowed
            }
        }
    };

    ReconstructionPlanReport {
        verdict,
        repo_root: root.to_string_lossy().to_string(),
        plan: ReconstructionPlanInput {
            source_html_path: display_plan_path(root, &source),
            source_role,
            reconstruction_mode,
            output_target: display_plan_path(root, &target),
            input_jsonl_path: input_jsonl
                .as_deref()
                .map(|path| display_plan_path(root, path)),
            reconstruction_run_dir: run_dir.as_deref().map(|path| display_plan_path(root, path)),
            requires_backup,
            requires_hash_report,
        },
        checks_run: checks.len(),
        errors,
        checks,
    }
}

pub fn parse_reconstruction_source_role(value: &str) -> Option<ReconstructionSourceRole> {
    match value {
        "seed" => Some(ReconstructionSourceRole::Seed),
        "working" => Some(ReconstructionSourceRole::Working),
        "bootstrap_aux" => Some(ReconstructionSourceRole::BootstrapAux),
        _ => None,
    }
}

pub fn parse_reconstruction_mode(value: &str) -> Option<ReconstructionMode> {
    match value {
        "diagnostic" => Some(ReconstructionMode::Diagnostic),
        "staging" => Some(ReconstructionMode::Staging),
        "write_local_canon" => Some(ReconstructionMode::WriteLocalCanon),
        "reverse_projection" => Some(ReconstructionMode::ReverseProjection),
        _ => None,
    }
}

/// Audita un reporte de reconstrucción antes de que Python restaure su backup.
///
/// Rust no modifica `data/out/local`. Solo comprueba que el reporte pertenece
/// a `data/tmp/reconstruction/`, que declara rollback habilitado, que el backup
/// contiene shards reales y que el hash de ese backup coincide con el
/// `canon_before_hash` registrado.
pub fn audit_reconstruction_rollback(
    repo_root: &Path,
    report_path: &Path,
) -> ReconstructionRollbackReport {
    let root = repo_root;
    let mut checks: Vec<PerimeterCheck> = Vec::new();
    let report = resolve_plan_path(root, report_path);
    let reconstruction_dir = root.join("data/tmp/reconstruction");
    let canon_dir = root.join("data/out/local");

    if path_has_parent_component(report_path) {
        push_error(
            &mut checks,
            "rollback-report-no-parent-path-components",
            "el reporte de rollback no acepta componentes '..'",
        );
    } else {
        push_ok(
            &mut checks,
            "rollback-report-no-parent-path-components",
            "el reporte de rollback no usa componentes '..'",
        );
    }

    if path_under(&report, &reconstruction_dir) {
        push_ok(
            &mut checks,
            "rollback-report-under-reconstruction",
            "reporte de reconstruccion esta bajo data/tmp/reconstruction",
        );
    } else {
        push_error(
            &mut checks,
            "rollback-report-under-reconstruction",
            "reporte de reconstruccion debe estar bajo data/tmp/reconstruction",
        );
    }

    let value = match read_json_object(&report) {
        Ok(value) => {
            push_ok(
                &mut checks,
                "rollback-report-readable",
                "reporte de reconstruccion es JSON valido",
            );
            value
        }
        Err(message) => {
            push_error(&mut checks, "rollback-report-readable", &message);
            return finish_rollback_report(root, &report, None, None, None, None, checks);
        }
    };

    if value.get("rollback_ready").and_then(|item| item.as_bool()) == Some(true) {
        push_ok(
            &mut checks,
            "rollback-ready-flag",
            "reporte declara rollback_ready=true",
        );
    } else {
        push_error(
            &mut checks,
            "rollback-ready-flag",
            "reporte debe declarar rollback_ready=true",
        );
    }

    let backup_dir = value
        .get("backup_dir")
        .and_then(|item| item.as_str())
        .map(|path| resolve_plan_path(root, Path::new(path)));
    let output_target = value
        .get("output_target")
        .and_then(|item| item.as_str())
        .map(|path| resolve_plan_path(root, Path::new(path)));
    let expected_hash = value
        .get("canon_before_hash")
        .and_then(|item| item.as_str())
        .map(|item| item.to_string());

    match &output_target {
        Some(target) if target == &canon_dir => {
            push_ok(
                &mut checks,
                "rollback-output-target-local-canon",
                "rollback apunta exactamente a data/out/local",
            );
        }
        Some(target) => {
            push_error(
                &mut checks,
                "rollback-output-target-local-canon",
                &format!(
                    "rollback debe apuntar a data/out/local, no a {}",
                    display_plan_path(root, target)
                ),
            );
        }
        None => {
            push_error(
                &mut checks,
                "rollback-output-target-local-canon",
                "reporte no declara output_target",
            );
        }
    }

    let computed_hash = match &backup_dir {
        Some(path) if path_under(path, &reconstruction_dir) && path.ends_with("canon_before") => {
            push_ok(
                &mut checks,
                "rollback-backup-under-reconstruction",
                "backup canon_before esta bajo data/tmp/reconstruction",
            );
            match canonical_canon_tree_hash(path) {
                Ok(hash) => {
                    push_ok(
                        &mut checks,
                        "rollback-backup-hash-computable",
                        "hash del backup canon_before calculable sobre shards reales",
                    );
                    Some(hash)
                }
                Err(message) => {
                    push_error(&mut checks, "rollback-backup-hash-computable", &message);
                    None
                }
            }
        }
        Some(_) => {
            push_error(
                &mut checks,
                "rollback-backup-under-reconstruction",
                "backup debe ser canon_before bajo data/tmp/reconstruction",
            );
            None
        }
        None => {
            push_error(
                &mut checks,
                "rollback-backup-under-reconstruction",
                "reporte no declara backup_dir",
            );
            None
        }
    };

    match (&expected_hash, &computed_hash) {
        (Some(expected), Some(computed)) if is_sha256_label(expected) && expected == computed => {
            push_ok(
                &mut checks,
                "rollback-backup-hash-matches-report",
                "canon_before_hash coincide con el contenido real del backup",
            );
        }
        (Some(expected), Some(computed)) if !is_sha256_label(expected) => {
            push_error(
                &mut checks,
                "rollback-backup-hash-matches-report",
                &format!("canon_before_hash invalido: {}", expected),
            );
        }
        (Some(expected), Some(computed)) => {
            push_error(
                &mut checks,
                "rollback-backup-hash-matches-report",
                &format!(
                    "canon_before_hash esperado {}, calculado {}",
                    expected, computed
                ),
            );
        }
        (None, _) => {
            push_error(
                &mut checks,
                "rollback-backup-hash-matches-report",
                "reporte no declara canon_before_hash",
            );
        }
        (_, None) => {
            push_error(
                &mut checks,
                "rollback-backup-hash-matches-report",
                "no se pudo calcular hash del backup",
            );
        }
    }

    finish_rollback_report(
        root,
        &report,
        backup_dir.as_deref(),
        output_target.as_deref(),
        expected_hash.as_deref(),
        computed_hash.as_deref(),
        checks,
    )
}

fn finish_rollback_report(
    root: &Path,
    report: &Path,
    backup_dir: Option<&Path>,
    output_target: Option<&Path>,
    expected_hash: Option<&str>,
    computed_hash: Option<&str>,
    checks: Vec<PerimeterCheck>,
) -> ReconstructionRollbackReport {
    let errors = checks
        .iter()
        .filter(|check| check.status == "error")
        .count();
    let verdict = if errors == 0 {
        ReconstructionRollbackVerdict::Ready
    } else {
        ReconstructionRollbackVerdict::Rejected
    };

    ReconstructionRollbackReport {
        verdict,
        repo_root: root.to_string_lossy().to_string(),
        rollback: ReconstructionRollbackInput {
            report_path: display_plan_path(root, report),
            backup_dir: backup_dir.map(|path| display_plan_path(root, path)),
            output_target: output_target.map(|path| display_plan_path(root, path)),
            expected_canon_before_hash: expected_hash.map(str::to_string),
            computed_backup_hash: computed_hash.map(str::to_string),
        },
        checks_run: checks.len(),
        errors,
        checks,
    }
}

/// Calcula el hash de árbol usado por los reportes de reconstrucción:
/// nombre de shard, byte NUL, contenido real, byte NUL, en orden de shard.
pub fn canonical_canon_tree_hash(canon_dir: &Path) -> Result<String, String> {
    let mut shards: Vec<PathBuf> = std::fs::read_dir(canon_dir)
        .map_err(|e| format!("no se pudo leer '{}': {}", canon_dir.display(), e))?
        .flatten()
        .map(|entry| entry.path())
        .filter(|path| {
            path.file_name()
                .and_then(|name| name.to_str())
                .and_then(shard_number)
                .is_some()
        })
        .collect();
    shards.sort_by(|a, b| a.file_name().cmp(&b.file_name()));
    if shards.is_empty() {
        return Err(format!(
            "no se encontraron shards tiddlers_*.jsonl en '{}'",
            canon_dir.display()
        ));
    }

    let mut sha = Sha256::new();
    for shard in shards {
        let name = shard
            .file_name()
            .and_then(|name| name.to_str())
            .ok_or_else(|| format!("nombre de shard invalido: {}", shard.display()))?;
        let data = std::fs::read(&shard)
            .map_err(|e| format!("no se pudo leer '{}': {}", shard.display(), e))?;
        sha.update(name.as_bytes());
        sha.update(&[0]);
        sha.update(&data);
        sha.update(&[0]);
    }
    Ok(format!("sha256:{}", hex_lower(&sha.finalize())))
}

fn sha256_file_label(path: &Path) -> Result<String, String> {
    let data = std::fs::read(path)
        .map_err(|e| format!("no se pudo leer '{}' para hash: {}", path.display(), e))?;
    let mut sha = Sha256::new();
    sha.update(&data);
    Ok(format!("sha256:{}", hex_lower(&sha.finalize())))
}

fn is_sha256_label(value: &str) -> bool {
    let Some(hex) = value.strip_prefix("sha256:") else {
        return false;
    };
    hex.len() == 64 && hex.bytes().all(|b| b.is_ascii_hexdigit())
}

fn hex_lower(bytes: &[u8; 32]) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut out = String::with_capacity(64);
    for byte in bytes {
        out.push(HEX[(byte >> 4) as usize] as char);
        out.push(HEX[(byte & 0x0f) as usize] as char);
    }
    out
}

struct Sha256 {
    state: [u32; 8],
    buffer: [u8; 64],
    buffer_len: usize,
    length_bytes: u64,
}

impl Sha256 {
    fn new() -> Self {
        Self {
            state: [
                0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab,
                0x5be0cd19,
            ],
            buffer: [0; 64],
            buffer_len: 0,
            length_bytes: 0,
        }
    }

    fn update(&mut self, mut data: &[u8]) {
        self.length_bytes = self.length_bytes.wrapping_add(data.len() as u64);
        if self.buffer_len > 0 {
            let needed = 64 - self.buffer_len;
            let take = needed.min(data.len());
            self.buffer[self.buffer_len..self.buffer_len + take].copy_from_slice(&data[..take]);
            self.buffer_len += take;
            data = &data[take..];
            if self.buffer_len == 64 {
                let block = self.buffer;
                self.process_block(&block);
                self.buffer_len = 0;
            }
        }

        while data.len() >= 64 {
            let block: [u8; 64] = data[..64].try_into().expect("64 byte block");
            self.process_block(&block);
            data = &data[64..];
        }

        if !data.is_empty() {
            self.buffer[..data.len()].copy_from_slice(data);
            self.buffer_len = data.len();
        }
    }

    fn finalize(mut self) -> [u8; 32] {
        let bit_len = self.length_bytes.wrapping_mul(8);
        self.update_padding_byte(0x80);
        while self.buffer_len != 56 {
            self.update_padding_byte(0);
        }
        for byte in bit_len.to_be_bytes() {
            self.update_padding_byte(byte);
        }

        let mut out = [0u8; 32];
        for (index, word) in self.state.iter().enumerate() {
            out[index * 4..index * 4 + 4].copy_from_slice(&word.to_be_bytes());
        }
        out
    }

    fn update_padding_byte(&mut self, byte: u8) {
        self.buffer[self.buffer_len] = byte;
        self.buffer_len += 1;
        if self.buffer_len == 64 {
            let block = self.buffer;
            self.process_block(&block);
            self.buffer_len = 0;
        }
    }

    fn process_block(&mut self, block: &[u8; 64]) {
        const K: [u32; 64] = [
            0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4,
            0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe,
            0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f,
            0x4a7484aa, 0x5cb0a9dc, 0x76f988da, 0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7,
            0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc,
            0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b,
            0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070, 0x19a4c116,
            0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
            0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7,
            0xc67178f2,
        ];

        let mut w = [0u32; 64];
        for (index, chunk) in block.chunks_exact(4).take(16).enumerate() {
            w[index] = u32::from_be_bytes(chunk.try_into().expect("4 byte word"));
        }
        for index in 16..64 {
            let s0 = w[index - 15].rotate_right(7)
                ^ w[index - 15].rotate_right(18)
                ^ (w[index - 15] >> 3);
            let s1 = w[index - 2].rotate_right(17)
                ^ w[index - 2].rotate_right(19)
                ^ (w[index - 2] >> 10);
            w[index] = w[index - 16]
                .wrapping_add(s0)
                .wrapping_add(w[index - 7])
                .wrapping_add(s1);
        }

        let mut a = self.state[0];
        let mut b = self.state[1];
        let mut c = self.state[2];
        let mut d = self.state[3];
        let mut e = self.state[4];
        let mut f = self.state[5];
        let mut g = self.state[6];
        let mut h = self.state[7];

        for index in 0..64 {
            let s1 = e.rotate_right(6) ^ e.rotate_right(11) ^ e.rotate_right(25);
            let ch = (e & f) ^ ((!e) & g);
            let temp1 = h
                .wrapping_add(s1)
                .wrapping_add(ch)
                .wrapping_add(K[index])
                .wrapping_add(w[index]);
            let s0 = a.rotate_right(2) ^ a.rotate_right(13) ^ a.rotate_right(22);
            let maj = (a & b) ^ (a & c) ^ (b & c);
            let temp2 = s0.wrapping_add(maj);

            h = g;
            g = f;
            f = e;
            e = d.wrapping_add(temp1);
            d = c;
            c = b;
            b = a;
            a = temp1.wrapping_add(temp2);
        }

        self.state[0] = self.state[0].wrapping_add(a);
        self.state[1] = self.state[1].wrapping_add(b);
        self.state[2] = self.state[2].wrapping_add(c);
        self.state[3] = self.state[3].wrapping_add(d);
        self.state[4] = self.state[4].wrapping_add(e);
        self.state[5] = self.state[5].wrapping_add(f);
        self.state[6] = self.state[6].wrapping_add(g);
        self.state[7] = self.state[7].wrapping_add(h);
    }
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

enum ExpectedPathKind {
    File,
    Dir,
}

fn push_path_check(
    checks: &mut Vec<PerimeterCheck>,
    root: &Path,
    check_id: &str,
    rel_path: &str,
    expected: ExpectedPathKind,
    role: &str,
) {
    let path = root.join(rel_path);
    let ok = match expected {
        ExpectedPathKind::File => path.is_file(),
        ExpectedPathKind::Dir => path.is_dir(),
    };
    if ok {
        push_ok(checks, check_id, &format!("{}: {}", rel_path, role));
    } else {
        push_error(
            checks,
            check_id,
            &format!("falta {} requerido para {}", rel_path, role),
        );
    }
}

fn push_ok(checks: &mut Vec<PerimeterCheck>, check_id: &str, message: &str) {
    checks.push(PerimeterCheck {
        check_id: check_id.to_string(),
        status: "ok".to_string(),
        message: message.to_string(),
    });
}

fn push_error(checks: &mut Vec<PerimeterCheck>, check_id: &str, message: &str) {
    checks.push(PerimeterCheck {
        check_id: check_id.to_string(),
        status: "error".to_string(),
        message: message.to_string(),
    });
}

fn check_working_html_surfaces(root: &Path, checks: &mut Vec<PerimeterCheck>) {
    let data_in = root.join("data/in");
    let seed = root.join("data/in/objeto_de_estudio_trazabilidad_y_desarrollo.html");
    let empty = root.join("data/in/empty-store.html");
    let entries = match std::fs::read_dir(&data_in) {
        Ok(entries) => entries,
        Err(_) => {
            push_error(
                checks,
                "working-html-detected",
                "no se pudo leer data/in para detectar superficies HTML de trabajo",
            );
            return;
        }
    };

    let mut working: Vec<String> = Vec::new();
    for entry in entries.flatten() {
        let path = entry.path();
        if !path.is_file() || !is_html_path(&path) {
            continue;
        }
        if path == seed || path == empty {
            continue;
        }
        working.push(display_plan_path(root, &path));
    }

    if working.is_empty() {
        push_error(
            checks,
            "working-html-detected",
            "no se encontro HTML de trabajo en data/in distinto de la semilla y empty-store",
        );
    } else {
        push_ok(
            checks,
            "working-html-detected",
            &format!(
                "HTML de trabajo detectado en data/in: {}",
                working.join(", ")
            ),
        );
    }
}

fn check_source_html(
    root: &Path,
    source: &Path,
    source_role: &ReconstructionSourceRole,
    checks: &mut Vec<PerimeterCheck>,
) {
    if source.is_file() {
        push_ok(
            checks,
            "plan-source-html-exists",
            "source_html_path existe y es archivo",
        );
    } else {
        push_error(
            checks,
            "plan-source-html-exists",
            "source_html_path no existe o no es archivo",
        );
    }

    if is_html_path(source) {
        push_ok(
            checks,
            "plan-source-html-extension",
            "source_html_path tiene extension HTML/HTM",
        );
    } else {
        push_error(
            checks,
            "plan-source-html-extension",
            "source_html_path debe terminar en .html o .htm",
        );
    }

    let seed = root.join("data/in/objeto_de_estudio_trazabilidad_y_desarrollo.html");
    let empty = root.join("data/in/empty-store.html");
    let role_ok = match source_role {
        ReconstructionSourceRole::Seed => source == seed,
        ReconstructionSourceRole::BootstrapAux => source == empty,
        ReconstructionSourceRole::Working => source != seed && source != empty,
    };

    if role_ok {
        push_ok(
            checks,
            "plan-source-role-coherent",
            "source_role coincide con la fuente HTML seleccionada",
        );
    } else {
        push_error(
            checks,
            "plan-source-role-coherent",
            "source_role no coincide con la fuente HTML seleccionada",
        );
    }
}

fn check_reconstruction_target(
    target: &Path,
    data_tmp: &Path,
    canon_dir: &Path,
    reverse_html_dir: &Path,
    reconstruction_mode: &ReconstructionMode,
    checks: &mut Vec<PerimeterCheck>,
) {
    match reconstruction_mode {
        ReconstructionMode::Diagnostic => {
            if path_under(target, data_tmp) {
                push_ok(
                    checks,
                    "plan-target-diagnostic",
                    "diagnostic apunta a data/tmp",
                );
            } else {
                push_error(
                    checks,
                    "plan-target-diagnostic",
                    "diagnostic debe apuntar a data/tmp",
                );
            }
        }
        ReconstructionMode::Staging => {
            if path_under(target, data_tmp) && target != canon_dir {
                push_ok(checks, "plan-target-staging", "staging apunta a data/tmp");
            } else {
                push_error(
                    checks,
                    "plan-target-staging",
                    "staging debe escribir solo bajo data/tmp",
                );
            }
        }
        ReconstructionMode::WriteLocalCanon => {
            if target == canon_dir {
                push_ok(
                    checks,
                    "plan-target-local-canon",
                    "write_local_canon apunta exactamente a data/out/local",
                );
            } else {
                push_error(
                    checks,
                    "plan-target-local-canon",
                    "write_local_canon debe apuntar exactamente a data/out/local",
                );
            }
        }
        ReconstructionMode::ReverseProjection => {
            if path_under(target, reverse_html_dir) {
                push_ok(
                    checks,
                    "plan-target-reverse-projection",
                    "reverse_projection apunta a data/out/local/reverse_html",
                );
            } else {
                push_error(
                    checks,
                    "plan-target-reverse-projection",
                    "reverse_projection debe apuntar bajo data/out/local/reverse_html",
                );
            }
        }
    }
}

fn check_reconstruction_run_dir(
    root: &Path,
    run_dir: Option<&Path>,
    reconstruction_dir: &Path,
    reconstruction_mode: &ReconstructionMode,
    checks: &mut Vec<PerimeterCheck>,
) {
    match reconstruction_mode {
        ReconstructionMode::WriteLocalCanon => match run_dir {
            Some(path) if path_under(path, reconstruction_dir) && path != reconstruction_dir => {
                push_ok(
                    checks,
                    "plan-reconstruction-run-dir",
                    "write_local_canon declara run_id bajo data/tmp/reconstruction",
                );
            }
            Some(path) => {
                push_error(
                    checks,
                    "plan-reconstruction-run-dir",
                    &format!(
                        "write_local_canon debe declarar run_id bajo data/tmp/reconstruction, no {}",
                        display_plan_path(root, path)
                    ),
                );
            }
            None => {
                push_error(
                    checks,
                    "plan-reconstruction-run-dir",
                    "write_local_canon requiere run_id de evidencia bajo data/tmp/reconstruction",
                );
            }
        },
        ReconstructionMode::Diagnostic
        | ReconstructionMode::Staging
        | ReconstructionMode::ReverseProjection => {
            if let Some(path) = run_dir {
                if path_under(path, reconstruction_dir) {
                    push_ok(
                        checks,
                        "plan-reconstruction-run-dir",
                        "run_id de evidencia permanece bajo data/tmp/reconstruction",
                    );
                } else {
                    push_error(
                        checks,
                        "plan-reconstruction-run-dir",
                        "run_id de evidencia debe permanecer bajo data/tmp/reconstruction",
                    );
                }
            } else {
                push_ok(
                    checks,
                    "plan-reconstruction-run-dir",
                    "modo no destructivo no requiere run_id de reconstruccion",
                );
            }
        }
    }
}

fn check_input_jsonl_origin(
    root: &Path,
    source_html: &Path,
    input_jsonl: Option<&Path>,
    html_export_dir: &Path,
    reconstruction_mode: &ReconstructionMode,
    checks: &mut Vec<PerimeterCheck>,
) {
    if reconstruction_mode != &ReconstructionMode::WriteLocalCanon {
        if let Some(path) = input_jsonl {
            if path_under(path, html_export_dir) {
                push_ok(
                    checks,
                    "plan-input-jsonl-scope",
                    "JSONL temporal permanece bajo data/tmp/html_export",
                );
            } else {
                push_error(
                    checks,
                    "plan-input-jsonl-scope",
                    "JSONL temporal debe provenir de data/tmp/html_export",
                );
            }
        } else {
            push_ok(
                checks,
                "plan-input-jsonl-scope",
                "modo sin shardizacion no requiere JSONL temporal",
            );
        }
        return;
    }

    let input_jsonl = match input_jsonl {
        Some(path) => path,
        None => {
            push_error(
                checks,
                "plan-input-jsonl-required",
                "write_local_canon requiere JSONL temporal seleccionado",
            );
            return;
        }
    };
    push_ok(
        checks,
        "plan-input-jsonl-required",
        "write_local_canon declara JSONL temporal seleccionado",
    );

    if path_under(input_jsonl, html_export_dir) {
        push_ok(
            checks,
            "plan-input-jsonl-scope",
            "JSONL temporal esta bajo data/tmp/html_export",
        );
    } else {
        push_error(
            checks,
            "plan-input-jsonl-scope",
            "JSONL temporal debe estar bajo data/tmp/html_export; rutas legacy sin manifiesto quedan bloqueadas",
        );
    }

    if input_jsonl.is_file() {
        push_ok(
            checks,
            "plan-input-jsonl-exists",
            "JSONL temporal existe y es archivo",
        );
    } else {
        push_error(
            checks,
            "plan-input-jsonl-exists",
            "JSONL temporal no existe o no es archivo",
        );
    }

    if input_jsonl
        .extension()
        .and_then(|ext| ext.to_str())
        .map(|ext| ext.eq_ignore_ascii_case("jsonl"))
        .unwrap_or(false)
    {
        push_ok(
            checks,
            "plan-input-jsonl-extension",
            "JSONL temporal termina en .jsonl",
        );
    } else {
        push_error(
            checks,
            "plan-input-jsonl-extension",
            "JSONL temporal debe terminar en .jsonl",
        );
    }

    let manifest_path = input_jsonl.with_file_name("tiddlers.export.manifest.json");
    let manifest = match read_json_object(&manifest_path) {
        Ok(value) => {
            push_ok(
                checks,
                "plan-input-manifest-readable",
                "manifiesto de export temporal es JSON valido",
            );
            value
        }
        Err(message) => {
            push_error(checks, "plan-input-manifest-readable", &message);
            return;
        }
    };

    expect_json_string(
        checks,
        &manifest,
        "plan-input-manifest-role",
        "artifact_role",
        "canon_export",
    );

    check_manifest_path_matches(
        root,
        checks,
        &manifest,
        "plan-input-manifest-output-match",
        "output_path",
        input_jsonl,
    );
    check_manifest_path_matches(
        root,
        checks,
        &manifest,
        "plan-input-manifest-source-match",
        "source_html_path",
        source_html,
    );
    check_manifest_hash_matches(
        checks,
        &manifest,
        "plan-input-manifest-jsonl-hash",
        "sha256",
        input_jsonl,
    );
    check_manifest_hash_matches(
        checks,
        &manifest,
        "plan-input-manifest-source-hash",
        "source_html_sha256",
        source_html,
    );
}

fn check_manifest_path_matches(
    root: &Path,
    checks: &mut Vec<PerimeterCheck>,
    manifest: &serde_json::Value,
    check_id: &str,
    key: &str,
    expected: &Path,
) {
    let Some(actual) = manifest.get(key).and_then(|item| item.as_str()) else {
        push_error(checks, check_id, &format!("manifiesto no declara {}", key));
        return;
    };
    let actual_path = resolve_plan_path(root, Path::new(actual));
    if actual_path == expected {
        push_ok(
            checks,
            check_id,
            &format!("{} del manifiesto coincide con el artefacto declarado", key),
        );
    } else {
        push_error(
            checks,
            check_id,
            &format!(
                "{} del manifiesto apunta a {}, no a {}",
                key,
                display_plan_path(root, &actual_path),
                display_plan_path(root, expected)
            ),
        );
    }
}

fn check_manifest_hash_matches(
    checks: &mut Vec<PerimeterCheck>,
    manifest: &serde_json::Value,
    check_id: &str,
    key: &str,
    expected_path: &Path,
) {
    let Some(actual) = manifest.get(key).and_then(|item| item.as_str()) else {
        push_error(checks, check_id, &format!("manifiesto no declara {}", key));
        return;
    };
    if !is_sha256_label(actual) {
        push_error(
            checks,
            check_id,
            &format!("{} no tiene formato sha256:<64 hex>", key),
        );
        return;
    }
    match sha256_file_label(expected_path) {
        Ok(expected) if expected == actual => {
            push_ok(
                checks,
                check_id,
                &format!("{} coincide con el contenido real declarado", key),
            );
        }
        Ok(expected) => {
            push_error(
                checks,
                check_id,
                &format!("{} esperado {}, encontrado {}", key, expected, actual),
            );
        }
        Err(message) => push_error(checks, check_id, &message),
    }
}

fn resolve_plan_path(root: &Path, value: &Path) -> PathBuf {
    if value.is_absolute() {
        value.to_path_buf()
    } else {
        root.join(value)
    }
}

fn display_plan_path(root: &Path, path: &Path) -> String {
    path.strip_prefix(root)
        .map(|relative| relative.to_string_lossy().to_string())
        .unwrap_or_else(|_| path.to_string_lossy().to_string())
}

fn is_html_path(path: &Path) -> bool {
    path.extension()
        .and_then(|ext| ext.to_str())
        .map(|ext| ext.eq_ignore_ascii_case("html") || ext.eq_ignore_ascii_case("htm"))
        .unwrap_or(false)
}

fn path_under(path: &Path, parent: &Path) -> bool {
    path == parent || path.starts_with(parent)
}

fn path_has_parent_component(path: &Path) -> bool {
    path.components()
        .any(|component| matches!(component, std::path::Component::ParentDir))
}

fn check_canon_shards(root: &Path, checks: &mut Vec<PerimeterCheck>) {
    let canon_dir = root.join("data/out/local");
    let mut shard_numbers: Vec<u32> = Vec::new();
    let entries = match std::fs::read_dir(&canon_dir) {
        Ok(entries) => entries,
        Err(_) => {
            push_error(
                checks,
                "canon-shards-readable",
                "no se pudo leer data/out/local para validar shards",
            );
            return;
        }
    };

    for entry in entries.flatten() {
        let file_name = entry.file_name().to_string_lossy().to_string();
        if let Some(number) = shard_number(&file_name) {
            shard_numbers.push(number);
        }
    }

    shard_numbers.sort_unstable();
    if shard_numbers.is_empty() {
        push_error(
            checks,
            "canon-shards-contiguous",
            "no se encontraron shards data/out/local/tiddlers_*.jsonl",
        );
        return;
    }

    let expected: Vec<u32> = (1..=shard_numbers.len() as u32).collect();
    if shard_numbers == expected {
        push_ok(
            checks,
            "canon-shards-contiguous",
            &format!(
                "shards canónicos contiguos detectados: {}",
                shard_numbers.len()
            ),
        );
    } else {
        push_error(
            checks,
            "canon-shards-contiguous",
            &format!("shards no contiguos: {:?}", shard_numbers),
        );
    }
}

fn shard_number(file_name: &str) -> Option<u32> {
    let prefix = "tiddlers_";
    let suffix = ".jsonl";
    if !file_name.starts_with(prefix) || !file_name.ends_with(suffix) {
        return None;
    }
    file_name[prefix.len()..file_name.len() - suffix.len()]
        .parse::<u32>()
        .ok()
}

fn check_policy_bundle(root: &Path, checks: &mut Vec<PerimeterCheck>) {
    let path = root.join("data/sessions/00_contratos/policy/canon_policy_bundle.json");
    let value = match read_json_object(&path) {
        Ok(value) => value,
        Err(message) => {
            push_error(checks, "policy-bundle-readable", &message);
            return;
        }
    };
    push_ok(
        checks,
        "policy-bundle-readable",
        "canon_policy_bundle.json es JSON válido",
    );

    expect_json_string(
        checks,
        &value,
        "policy-source-of-truth",
        "local_output_root",
        "data/out/local",
    );
    expect_json_string(
        checks,
        &value,
        "policy-session-staging",
        "session_semantic_close_default",
        "data_sessions_staging",
    );
    expect_json_string(
        checks,
        &value,
        "policy-reverse-html-root",
        "reverse_html_root",
        "data/out/local/reverse_html",
    );
    if let Some(contract) = value
        .get("role_primary_contract")
        .and_then(serde_json::Value::as_object)
    {
        push_ok(
            checks,
            "policy-role-primary-contract-present",
            "role_primary_contract existe en canon_policy_bundle.json",
        );
        if contract.get("field").and_then(serde_json::Value::as_str) == Some("role_primary") {
            push_ok(
                checks,
                "policy-role-primary-contract-field",
                "role_primary_contract gobierna el campo role_primary",
            );
        } else {
            push_error(
                checks,
                "policy-role-primary-contract-field",
                "role_primary_contract.field debe ser role_primary",
            );
        }
        if contract
            .get("canonical_roles")
            .and_then(serde_json::Value::as_array)
            .map(|roles| {
                roles
                    .iter()
                    .any(|role| role.as_str() == Some("unclassified"))
            })
            .unwrap_or(false)
        {
            push_ok(
                checks,
                "policy-role-primary-contract-fallback",
                "role_primary_contract declara unclassified como fallback canonico",
            );
        } else {
            push_error(
                checks,
                "policy-role-primary-contract-fallback",
                "role_primary_contract.canonical_roles debe incluir unclassified",
            );
        }
    } else {
        push_error(
            checks,
            "policy-role-primary-contract-present",
            "canon_policy_bundle.json no declara role_primary_contract",
        );
    }

    let direct_write = value
        .get("direct_canon_write_default")
        .and_then(|item| item.as_str())
        .unwrap_or("");
    if direct_write.contains("prohibited") {
        push_ok(
            checks,
            "policy-direct-canon-write-prohibited",
            "la política prohíbe escritura directa al canon por defecto",
        );
    } else {
        push_error(
            checks,
            "policy-direct-canon-write-prohibited",
            "direct_canon_write_default no declara prohibición por defecto",
        );
    }
}

fn check_derived_registry(root: &Path, checks: &mut Vec<PerimeterCheck>) {
    let path = root.join("data/sessions/00_contratos/projections/derived_layers_registry.json");
    let value = match read_json_object(&path) {
        Ok(value) => value,
        Err(message) => {
            push_error(checks, "derived-registry-readable", &message);
            return;
        }
    };
    push_ok(
        checks,
        "derived-registry-readable",
        "derived_layers_registry.json es JSON válido",
    );

    expect_json_string(
        checks,
        &value,
        "registry-source-layer-canon",
        "source_of_truth_layer",
        "canon",
    );
    expect_layer_class_bool(
        checks,
        &value,
        "registry-canon-authoritative",
        "canon",
        "is_canonical",
        true,
    );
    expect_layer_class_bool(
        checks,
        &value,
        "registry-session-staging-noncanonical",
        "session_staging",
        "is_canonical",
        false,
    );
    expect_layer_class_bool(
        checks,
        &value,
        "registry-derived-noncanonical",
        "derived",
        "is_canonical",
        false,
    );
    expect_layer_class_bool(
        checks,
        &value,
        "registry-reverse-projection-noncanonical",
        "reverse_projection",
        "is_canonical",
        false,
    );
}

fn check_readme_single_operator(root: &Path, checks: &mut Vec<PerimeterCheck>) {
    let readme_path = root.join("README.md");
    let text = match std::fs::read_to_string(&readme_path) {
        Ok(text) => text,
        Err(_) => {
            push_error(checks, "readme-readable", "no se pudo leer README.md");
            return;
        }
    };
    push_ok(checks, "readme-readable", "README.md legible");

    if text.contains("shell_scripts/tdc.sh") {
        push_ok(
            checks,
            "readme-single-operator-wrapper",
            "README apunta al wrapper operativo único shell_scripts/tdc.sh",
        );
    } else {
        push_error(
            checks,
            "readme-single-operator-wrapper",
            "README no menciona shell_scripts/tdc.sh como entry point operativo",
        );
    }

    let mentions_obsolete_wrapper = text.contains("`scripts/tdc.sh`")
        || text.lines().any(|line| line.trim() == "scripts/tdc.sh");
    if mentions_obsolete_wrapper {
        push_error(
            checks,
            "readme-no-obsolete-scripts-wrapper",
            "README todavía menciona scripts/tdc.sh",
        );
    } else {
        push_ok(
            checks,
            "readme-no-obsolete-scripts-wrapper",
            "README no menciona el wrapper obsoleto scripts/tdc.sh",
        );
    }
}

fn read_json_object(path: &Path) -> Result<serde_json::Value, String> {
    let content = std::fs::read_to_string(path)
        .map_err(|e| format!("no se pudo leer '{}': {}", path.display(), e))?;
    serde_json::from_str(&content)
        .map_err(|e| format!("JSON inválido en '{}': {}", path.display(), e))
}

fn expect_json_string(
    checks: &mut Vec<PerimeterCheck>,
    value: &serde_json::Value,
    check_id: &str,
    key: &str,
    expected: &str,
) {
    let actual = value.get(key).and_then(|item| item.as_str());
    if actual == Some(expected) {
        push_ok(checks, check_id, &format!("{} == {}", key, expected));
    } else {
        push_error(
            checks,
            check_id,
            &format!("{} esperado {:?}, encontrado {:?}", key, expected, actual),
        );
    }
}

fn expect_layer_class_bool(
    checks: &mut Vec<PerimeterCheck>,
    value: &serde_json::Value,
    check_id: &str,
    class_name: &str,
    key: &str,
    expected: bool,
) {
    let actual = value
        .get("layer_classes")
        .and_then(|item| item.get(class_name))
        .and_then(|item| item.get(key))
        .and_then(|item| item.as_bool());
    if actual == Some(expected) {
        push_ok(
            checks,
            check_id,
            &format!("layer_classes.{}.{} == {}", class_name, key, expected),
        );
    } else {
        push_error(
            checks,
            check_id,
            &format!(
                "layer_classes.{}.{} esperado {}, encontrado {:?}",
                class_name, key, expected, actual
            ),
        );
    }
}
