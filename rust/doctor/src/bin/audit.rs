//! # audit — CLI mínima del Doctor
//!
//! Uso:
//!   audit <raw_path>
//!   audit perimeter <repo_root>
//!   audit reconstruction-plan <repo_root> --source-html <path> --source-role <role> --mode <mode> --output-target <path> [--input-jsonl <path>] [--reconstruction-run-dir <path>] --requires-backup <true|false> --requires-hash-report <true|false>
//!   audit reconstruction-rollback <repo_root> --report <path>
//!   audit canonical-line-gate <repo_root> --input <path> [--report <path>]
//!   audit deep-node-inspect <repo_root> --input <path> [--report <path>]
//!
//! Audita la integridad estructural mínima del artefacto raw producido por
//! el Extractor, o el perímetro reusable del repositorio. Emite el reporte
//! raw por stderr y los reportes normativos por JSON en stdout.
//!
//! Código de salida:
//!   0  — veredicto ok o warning (el pipeline puede continuar)
//!   1  — argumentos incorrectos
//!   2  — fallo bloqueante del doctor (error de I/O o JSON inválido)
//!   10 — veredicto Error (fallos estructurales bloqueantes; pipeline debe detenerse)
//!
//! Ref: contratos/m01-s12-pipeline-costura.md.json

use std::{collections::HashMap, env, path::Path, process};

fn main() {
    let args: Vec<String> = env::args().collect();
    if args.len() < 2 {
        eprintln!(
            "[doctor] uso: audit <raw_path> | audit perimeter <repo_root> | audit reconstruction-plan <repo_root> --source-html <path> --source-role <role> --mode <mode> --output-target <path> [--input-jsonl <path>] [--reconstruction-run-dir <path>] --requires-backup <true|false> --requires-hash-report <true|false> | audit reconstruction-rollback <repo_root> --report <path> | audit canonical-line-gate <repo_root> --input <path> [--report <path>] | audit deep-node-inspect <repo_root> --input <path> [--report <path>]"
        );
        process::exit(1);
    }

    if args[1] == "perimeter" {
        let repo_root = args.get(2).map(String::as_str).unwrap_or(".");
        let report = tdc_doctor::audit_perimeter(Path::new(repo_root));
        let json = serde_json::to_string_pretty(&report).unwrap_or_else(|e| {
            eprintln!("[doctor] ERROR al serializar reporte de perímetro: {}", e);
            process::exit(2);
        });
        println!("{}", json);
        eprintln!(
            "[doctor] perimeter verdict={:?} checks={} errors={}",
            report.verdict, report.checks_run, report.errors
        );
        if report.verdict == tdc_doctor::PerimeterVerdict::Error {
            process::exit(10);
        }
        return;
    }

    if args[1] == "reconstruction-plan" {
        let repo_root = args.get(2).map(String::as_str).unwrap_or(".");
        let flags = parse_flags(&args[3..]).unwrap_or_else(|message| {
            eprintln!("[doctor] ERROR: {}", message);
            process::exit(1);
        });
        let source_html = required_flag(&flags, "source-html");
        let source_role = required_flag(&flags, "source-role");
        let mode = required_flag(&flags, "mode");
        let output_target = required_flag(&flags, "output-target");
        let input_jsonl = flags.get("input-jsonl");
        let reconstruction_run_dir = flags.get("reconstruction-run-dir");
        let requires_backup = parse_bool_flag(required_flag(&flags, "requires-backup"));
        let requires_hash_report = parse_bool_flag(required_flag(&flags, "requires-hash-report"));

        let source_role =
            tdc_doctor::parse_reconstruction_source_role(source_role).unwrap_or_else(|| {
                eprintln!(
                    "[doctor] ERROR: source-role inválido '{}'; use seed, working o bootstrap_aux",
                    source_role
                );
                process::exit(1);
            });
        let mode = tdc_doctor::parse_reconstruction_mode(mode).unwrap_or_else(|| {
            eprintln!(
                "[doctor] ERROR: mode inválido '{}'; use diagnostic, staging, write_local_canon o reverse_projection",
                mode
            );
            process::exit(1);
        });

        let report = tdc_doctor::audit_reconstruction_plan_with_artifacts(
            Path::new(repo_root),
            Path::new(source_html),
            source_role,
            mode,
            Path::new(output_target),
            input_jsonl.map(|path| Path::new(path.as_str())),
            reconstruction_run_dir.map(|path| Path::new(path.as_str())),
            requires_backup,
            requires_hash_report,
        );
        let json = serde_json::to_string_pretty(&report).unwrap_or_else(|e| {
            eprintln!("[doctor] ERROR al serializar reporte de plan: {}", e);
            process::exit(2);
        });
        println!("{}", json);
        eprintln!(
            "[doctor] reconstruction-plan verdict={:?} checks={} errors={}",
            report.verdict, report.checks_run, report.errors
        );
        if report.verdict == tdc_doctor::ReconstructionPlanVerdict::Rejected {
            process::exit(10);
        }
        return;
    }

    if args[1] == "reconstruction-rollback" {
        let repo_root = args.get(2).map(String::as_str).unwrap_or(".");
        let flags = parse_flags(&args[3..]).unwrap_or_else(|message| {
            eprintln!("[doctor] ERROR: {}", message);
            process::exit(1);
        });
        let report_path = required_flag(&flags, "report");
        let report =
            tdc_doctor::audit_reconstruction_rollback(Path::new(repo_root), Path::new(report_path));
        let json = serde_json::to_string_pretty(&report).unwrap_or_else(|e| {
            eprintln!("[doctor] ERROR al serializar reporte de rollback: {}", e);
            process::exit(2);
        });
        println!("{}", json);
        eprintln!(
            "[doctor] reconstruction-rollback verdict={:?} checks={} errors={}",
            report.verdict, report.checks_run, report.errors
        );
        if report.verdict == tdc_doctor::ReconstructionRollbackVerdict::Rejected {
            process::exit(10);
        }
        return;
    }

    if args[1] == "canonical-line-gate" {
        let repo_root = args.get(2).map(String::as_str).unwrap_or(".");
        let flags = parse_flags(&args[3..]).unwrap_or_else(|message| {
            eprintln!("[doctor] ERROR: {}", message);
            process::exit(1);
        });
        let input_path = required_flag(&flags, "input");
        let report = tdc_doctor::audit_canonical_lines(Path::new(repo_root), Path::new(input_path));
        let json = serde_json::to_string_pretty(&report).unwrap_or_else(|e| {
            eprintln!("[doctor] ERROR al serializar canonical-line gate: {}", e);
            process::exit(2);
        });
        if let Some(report_path) = flags.get("report") {
            write_report_file(Path::new(report_path), &json);
        }
        println!("{}", json);
        eprintln!(
            "[doctor] canonical-line-gate verdict={:?} lines={} parsed={} rejected={} inconsistent={}",
            report.verdict,
            report.lines_read,
            report.parsed_lines,
            report.counts.canon_line_rejected,
            report.counts.canon_line_inconsistent
        );
        if matches!(
            report.verdict,
            tdc_doctor::CanonicalLineVerdict::CanonLineRejected
                | tdc_doctor::CanonicalLineVerdict::CanonLineInconsistent
        ) {
            process::exit(10);
        }
        return;
    }

    if args[1] == "deep-node-inspect" {
        let repo_root = args.get(2).map(String::as_str).unwrap_or(".");
        let flags = parse_flags(&args[3..]).unwrap_or_else(|message| {
            eprintln!("[doctor] ERROR: {}", message);
            process::exit(1);
        });
        let input_path = required_flag(&flags, "input");
        let report = tdc_doctor::inspect_deep_nodes(Path::new(repo_root), Path::new(input_path));
        let json = serde_json::to_string_pretty(&report).unwrap_or_else(|e| {
            eprintln!("[doctor] ERROR al serializar deep-node inspector: {}", e);
            process::exit(2);
        });
        if let Some(report_path) = flags.get("report") {
            write_report_file(Path::new(report_path), &json);
        }
        println!("{}", json);
        eprintln!(
            "[doctor] deep-node-inspect verdict={:?} nodes={} findings={} structural_json={} pedagogical_json={} invalid_json={}",
            report.verdict,
            report.nodes_read,
            report.findings_count,
            report.counts.structural_json,
            report.counts.pedagogical_json,
            report.counts.invalid_json
        );
        return;
    }

    let raw_path = Path::new(&args[1]);

    match tdc_doctor::audit(raw_path) {
        Err(e) => {
            eprintln!("[doctor] ERROR: {}", e);
            process::exit(2);
        }
        Ok(report) => {
            let verdict_str = match report.verdict {
                tdc_doctor::DoctorVerdict::Ok => "ok",
                tdc_doctor::DoctorVerdict::Warning => "warning",
                tdc_doctor::DoctorVerdict::Error => "error",
            };
            eprintln!(
                "[doctor] verdict={} tiddlers={} warnings={} errors={}",
                verdict_str,
                report.tiddler_count,
                report.warnings.len(),
                report.errors.len()
            );
            for w in &report.warnings {
                eprintln!("[doctor] WARN: {}", w);
            }
            for e in &report.errors {
                eprintln!("[doctor] ERR: {}", e);
            }
            if report.verdict == tdc_doctor::DoctorVerdict::Error {
                process::exit(10);
            }
        }
    }
}

fn parse_flags(args: &[String]) -> Result<HashMap<String, String>, String> {
    let mut flags = HashMap::new();
    let mut index = 0;
    while index < args.len() {
        let key = args[index].strip_prefix("--").ok_or_else(|| {
            format!(
                "argumento inesperado '{}'; los parámetros del plan usan --clave valor",
                args[index]
            )
        })?;
        let value = args
            .get(index + 1)
            .ok_or_else(|| format!("falta valor para --{}", key))?;
        if value.starts_with("--") {
            return Err(format!("falta valor para --{}", key));
        }
        flags.insert(key.to_string(), value.clone());
        index += 2;
    }
    Ok(flags)
}

fn required_flag<'a>(flags: &'a HashMap<String, String>, key: &str) -> &'a str {
    flags.get(key).map(String::as_str).unwrap_or_else(|| {
        eprintln!("[doctor] ERROR: falta --{}", key);
        process::exit(1);
    })
}

fn parse_bool_flag(value: &str) -> bool {
    match value {
        "true" => true,
        "false" => false,
        _ => {
            eprintln!(
                "[doctor] ERROR: valor booleano inválido '{}'; use true o false",
                value
            );
            process::exit(1);
        }
    }
}

fn write_report_file(path: &Path, json: &str) {
    if let Some(parent) = path.parent() {
        if let Err(err) = std::fs::create_dir_all(parent) {
            eprintln!(
                "[doctor] ERROR al crear directorio de reporte '{}': {}",
                parent.display(),
                err
            );
            process::exit(2);
        }
    }
    if let Err(err) = std::fs::write(path, json) {
        eprintln!(
            "[doctor] ERROR al escribir reporte '{}': {}",
            path.display(),
            err
        );
        process::exit(2);
    }
}
