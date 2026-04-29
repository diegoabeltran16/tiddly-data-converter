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

pub mod error;
pub mod report;

use std::path::{Path, PathBuf};

pub use error::DoctorError;
pub use report::{
    DoctorReport, DoctorVerdict, PerimeterCheck, PerimeterReport, PerimeterVerdict,
    ReconstructionMode, ReconstructionPlanInput, ReconstructionPlanReport,
    ReconstructionPlanVerdict, ReconstructionSourceRole,
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
    let root = repo_root;
    let mut checks: Vec<PerimeterCheck> = Vec::new();
    let source = resolve_plan_path(root, source_html_path);
    let target = resolve_plan_path(root, output_target);
    let data_in = root.join("data/in");
    let data_tmp = root.join("data/tmp");
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

    if path_has_parent_component(source_html_path) || path_has_parent_component(output_target) {
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
