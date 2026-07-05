//! # extract — CLI mínima del Extractor
//!
//! Uso: extract <html_input> <raw_output>
//!
//! Extrae tiddlers del HTML vivo de TiddlyWiki y escribe el artefacto raw
//! como JSON en la ruta de salida indicada. Emite el reporte por stderr.
//!
//! Código de salida:
//!   0 — extracción ok o parcial (el pipeline puede continuar)
//!   1 — argumentos incorrectos
//!   2 — fallo bloqueante del extractor
//!   3 — error al escribir el artefacto raw
//!
//! Ref: contratos/m01-s12-pipeline-costura.md.json

use std::{env, path::Path, process};

fn main() {
    let args: Vec<String> = env::args().collect();
    if args.len() < 3 {
        eprintln!("[extractor] uso: extract <html_input> <raw_output>");
        process::exit(1);
    }
    let html_path = Path::new(&args[1]);
    let out_path = Path::new(&args[2]);

    match tdc_extractor::extract(html_path) {
        Err(e) => {
            eprintln!("[extractor] ERROR: {}", e);
            process::exit(2);
        }
        Ok((tiddlers, report)) => {
            let status_str = format!("{:?}", report.status).to_lowercase();
            eprintln!(
                "[extractor] status={} tiddlers={} warnings={} errors={}",
                status_str,
                report.tiddler_count,
                report.warnings.len(),
                report.errors.len()
            );
            for w in &report.warnings {
                eprintln!("[extractor] WARN: {}", w);
            }
            for e in &report.errors {
                eprintln!("[extractor] ERR: {}", e);
            }

            let json = serde_json::to_string_pretty(&tiddlers).unwrap_or_else(|e| {
                eprintln!("[extractor] ERROR al serializar tiddlers: {}", e);
                process::exit(2);
            });

            if let Some(parent) = out_path.parent() {
                if !parent.as_os_str().is_empty() {
                    std::fs::create_dir_all(parent).unwrap_or_else(|e| {
                        eprintln!(
                            "[extractor] ERROR al crear directorio '{}': {}",
                            parent.display(),
                            e
                        );
                        process::exit(3);
                    });
                }
            }

            std::fs::write(out_path, &json).unwrap_or_else(|e| {
                eprintln!(
                    "[extractor] ERROR al escribir '{}': {}",
                    out_path.display(),
                    e
                );
                process::exit(3);
            });

            eprintln!(
                "[extractor] raw escrito en '{}'",
                out_path.display()
            );
        }
    }
}
