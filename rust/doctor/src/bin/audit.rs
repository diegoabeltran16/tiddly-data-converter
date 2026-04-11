//! # audit — CLI mínima del Doctor
//!
//! Uso: audit <raw_path>
//!
//! Audita la integridad estructural mínima del artefacto raw producido por
//! el Extractor. Emite el veredicto y el reporte por stderr.
//!
//! Código de salida:
//!   0  — veredicto ok o warning (el pipeline puede continuar)
//!   1  — argumentos incorrectos
//!   2  — fallo bloqueante del doctor (error de I/O o JSON inválido)
//!   10 — veredicto Error (fallos estructurales bloqueantes; pipeline debe detenerse)
//!
//! Ref: contratos/m01-s12-pipeline-costura.md.json

use std::{env, path::Path, process};

fn main() {
    let args: Vec<String> = env::args().collect();
    if args.len() < 2 {
        eprintln!("[doctor] uso: audit <raw_path>");
        process::exit(1);
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
