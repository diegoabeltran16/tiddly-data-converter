use std::path::{Path, PathBuf};
use tdc_extractor::{extract, ExtractionStatus, ExtractorError};

/// Devuelve la ruta absoluta a un fixture bajo tests/fixtures/ en la raíz del proyecto.
fn fixture(name: &str) -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../../tests/fixtures")
        .join(name)
}

// ---------------------------------------------------------------------------
// Tests de comportamiento bloqueante (no dependen del parser real)
// Válidos desde el Momento A del bootstrap (m01-s02).
// ---------------------------------------------------------------------------

#[test]
fn test_archivo_inexistente_produce_error_file_not_found() {
    let path = Path::new("tests/fixtures/no_existe_en_ningun_lugar.html");
    let result = extract(path);
    assert!(
        matches!(result, Err(ExtractorError::FileNotFound(_))),
        "Se esperaba FileNotFound pero se obtuvo: {:?}",
        result
    );
}

#[test]
fn test_error_tiene_mensaje_descriptivo() {
    let path = Path::new("tests/fixtures/no_existe.html");
    let result = extract(path);
    if let Err(e) = result {
        let msg = e.to_string();
        assert!(
            msg.contains("ERR_FILE_NOT_FOUND"),
            "El mensaje de error debe incluir el código ERR_FILE_NOT_FOUND, obtenido: {}",
            msg
        );
    }
}

// ---------------------------------------------------------------------------
// Tests con fixture mínimo controlado
// Requieren tests/fixtures/minimal_tiddlywiki.html.
// Se activan en Momento B (m01-s02) una vez disponible el fixture.
// Para ejecutar: cargo test -- --include-ignored
// ---------------------------------------------------------------------------

#[test]
fn test_extraccion_exitosa_desde_fixture_minimo() {
    // El fixture contiene 4 tiddlers: Alpha, Beta, Sin Texto, $:/SiteTitle
    let path = fixture("minimal_tiddlywiki.html");
    let result = extract(&path);
    assert!(result.is_ok(), "La extracción del fixture mínimo debe ser exitosa: {:?}", result);
    let (tiddlers, report) = result.unwrap();
    assert_eq!(tiddlers.len(), 4, "El fixture debe producir exactamente 4 tiddlers");
    assert_eq!(
        report.status,
        ExtractionStatus::Ok,
        "El reporte debe indicar status: Ok"
    );
    assert_eq!(report.tiddler_count, 4);
    // Verificar que el primer tiddler tiene el título correcto
    assert_eq!(tiddlers[0].title, "Tiddler Alpha");
}

#[test]
fn test_raw_fields_no_modificados() {
    let path = fixture("minimal_tiddlywiki.html");
    let (tiddlers, _) = extract(&path).unwrap();
    for t in &tiddlers {
        assert!(!t.title.is_empty(), "El título del tiddler no puede ser vacío");
        // El campo title en raw_fields debe coincidir con el campo title de conveniencia
        assert_eq!(
            t.raw_fields.get("title").map(|s| s.as_str()),
            Some(t.title.as_str()),
            "raw_fields[title] debe ser idéntico al campo title"
        );
    }
    // Tiddler sin texto: raw_text debe ser None
    let sin_texto = tiddlers.iter().find(|t| t.title == "Tiddler Sin Texto");
    assert!(sin_texto.is_some(), "Debe existir el tiddler 'Tiddler Sin Texto'");
    assert!(sin_texto.unwrap().raw_text.is_none(), "Tiddler sin campo text debe tener raw_text = None");
    // Tiddler Alpha: raw_text debe ser Some
    let alpha = tiddlers.iter().find(|t| t.title == "Tiddler Alpha");
    assert!(alpha.unwrap().raw_text.is_some(), "Tiddler Alpha debe tener raw_text");
}

#[test]
fn test_siempre_hay_reporte_en_exito() {
    let path = fixture("minimal_tiddlywiki.html");
    let result = extract(&path);
    // Con el fixture mínimo la extracción debe ser exitosa
    assert!(result.is_ok(), "El fixture mínimo debe extraerse sin error");
    let (tiddlers, report) = result.unwrap();
    // El reporte siempre se construye y refleja la realidad
    assert_eq!(report.tiddler_count, tiddlers.len(), "report.tiddler_count debe coincidir con Vec len");
    assert!(report.errors.is_empty(), "No debe haber errores en una extracción limpia");
    // source_position debe estar presente en todos los tiddlers
    for t in &tiddlers {
        assert!(
            t.source_position.is_some(),
            "Todos los tiddlers deben tener source_position"
        );
    }
}
