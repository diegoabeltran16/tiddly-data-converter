use crate::report::{
    CanonQualityDebtSummary, CanonicalLineCounts, CanonicalLineGateReport, CanonicalLineIssue,
    CanonicalLineItemReport, CanonicalLineVerdict, DeepNodeFinding, DeepNodeFindingCounts,
    DeepNodeInspectionReport, DeepNodeInspectorVerdict, FamilyProfileIssueSummary,
    FamilyProfileReport, IncompleteLineTriageReport, ModalProjectionAuditReport,
    ModalProjectionIssueReport, RoleContractAuditReport, RoleContractCounts, TemplateFamilyReport,
    TemplateVariantReport,
};
use serde_json::Value;
use std::{
    collections::{BTreeMap, BTreeSet, HashMap},
    path::{Path, PathBuf},
};

const ALLOWED_TOP_LEVEL_FIELDS: &[&str] = &[
    "schema_version",
    "id",
    "key",
    "title",
    "canonical_slug",
    "version_id",
    "content_type",
    "modality",
    "encoding",
    "is_binary",
    "is_reference_only",
    "role_primary",
    "roles_secondary",
    "tags",
    "taxonomy_path",
    "semantic_text",
    "content",
    "normalized_tags",
    "raw_payload_ref",
    "asset_id",
    "mime_type",
    "document_id",
    "section_path",
    "order_in_document",
    "relations",
    "source_tags",
    "source_fields",
    "source_type",
    "source_position",
    "source_role",
    "text",
    "created",
    "modified",
];

const CORE_EXPECTED_FIELDS: &[&str] = &[
    "schema_version",
    "id",
    "key",
    "title",
    "canonical_slug",
    "version_id",
    "content_type",
    "modality",
    "encoding",
    "is_binary",
    "is_reference_only",
    "role_primary",
    "semantic_text",
    "content",
    "mime_type",
    "document_id",
    "section_path",
    "order_in_document",
    "relations",
    "text",
    "source_type",
    "source_position",
    "created",
    "modified",
];

const RICHNESS_EXPECTED_FIELDS: &[&str] = &[
    "tags",
    "taxonomy_path",
    "normalized_tags",
    "source_tags",
    "source_fields",
    "raw_payload_ref",
];

const FAMILY_PROFILE_RULE_PREFIX: &str = "family-profile-";
const ROLE_CONTRACT_REL_PATH: &str = "data/sessions/00_contratos/policy/canon_policy_bundle.json";

const SESSION_PROFILE_TOP_LEVEL_FIELDS: &[&str] = &[
    "schema_version",
    "id",
    "key",
    "title",
    "canonical_slug",
    "version_id",
    "content_type",
    "modality",
    "encoding",
    "is_binary",
    "is_reference_only",
    "role_primary",
    "tags",
    "taxonomy_path",
    "semantic_text",
    "content",
    "normalized_tags",
    "raw_payload_ref",
    "mime_type",
    "document_id",
    "section_path",
    "order_in_document",
    "relations",
    "source_tags",
    "source_fields",
    "source_type",
    "source_position",
    "source_role",
    "text",
    "created",
    "modified",
];

const SESSION_PROFILE_SOURCE_FIELDS: &[&str] = &[
    "session_origin",
    "artifact_family",
    "source_path",
    "canonical_status",
    "document_key",
    "provenance_ref",
];

const SESSION_PROFILE_TAG_PREFIXES: &[&str] = &["session:", "milestone:", "status:"];

const ASSET_PROFILE_TOP_LEVEL_FIELDS: &[&str] = &[
    "schema_version",
    "id",
    "key",
    "title",
    "canonical_slug",
    "version_id",
    "content_type",
    "modality",
    "encoding",
    "is_binary",
    "is_reference_only",
    "role_primary",
    "tags",
    "taxonomy_path",
    "normalized_tags",
    "raw_payload_ref",
    "asset_id",
    "mime_type",
    "document_id",
    "section_path",
    "order_in_document",
    "relations",
    "source_tags",
    "source_fields",
    "source_type",
    "source_position",
    "text",
    "created",
    "modified",
];

const CONTROLLED_MODALITIES: &[&str] = &[
    "text",
    "metadata",
    "image",
    "audio",
    "video",
    "binary",
    "mixed",
    "equation",
    "table",
    "reference",
    "code",
    "unknown",
];

#[derive(Debug, Clone)]
struct RoleContractIndex {
    contract_ref: String,
    canonical_roles: BTreeSet<String>,
    aliases_allowed: BTreeMap<String, String>,
    legacy_accepted: BTreeMap<String, Option<String>>,
    ambiguous_roles: BTreeMap<String, Vec<String>>,
    load_error: Option<String>,
}

#[derive(Debug)]
struct RoleContractEvaluation {
    verdict: String,
    canonical_role: Option<String>,
    candidate_roles: Vec<String>,
}

/// Clasifica lineas canonicas o candidatas sin modificar el canon.
pub fn audit_canonical_lines(repo_root: &Path, input_path: &Path) -> CanonicalLineGateReport {
    let root = repo_root;
    let input = resolve_quality_path(root, input_path);
    let mut source_files = collect_canonical_input_files(&input);
    source_files.sort();
    let role_contract = load_role_contract_index(root);
    let ai_role_map = load_ai_role_map(root);

    let mut report = CanonicalLineGateReport {
        verdict: CanonicalLineVerdict::CanonLineOk,
        repo_root: root.to_string_lossy().to_string(),
        input_path: display_quality_path(root, &input),
        source_files: source_files
            .iter()
            .map(|path| display_quality_path(root, path))
            .collect(),
        lines_read: 0,
        parsed_lines: 0,
        counts: CanonicalLineCounts::default(),
        template_families_with_drift: Vec::new(),
        family_profiles: Vec::new(),
        incomplete_line_triage: Vec::new(),
        role_contract_audit: empty_role_contract_audit(&role_contract),
        modal_projection_audit: empty_modal_projection_audit(),
        debt_summary: CanonQualityDebtSummary::default(),
        lines: Vec::new(),
    };

    if source_files.is_empty() {
        report.verdict = CanonicalLineVerdict::CanonLineRejected;
        report.counts.canon_line_rejected = 1;
        return report;
    }

    let mut template_observations: HashMap<String, Vec<TemplateObservation>> = HashMap::new();

    for source_file in &source_files {
        let content = match std::fs::read_to_string(source_file) {
            Ok(content) => content,
            Err(err) => {
                let item = rejected_line_item(
                    root,
                    source_file,
                    0,
                    "file-not-readable",
                    &format!("no se pudo leer el archivo: {}", err),
                );
                push_line_item(&mut report, item);
                continue;
            }
        };

        for (index, raw_line) in content.lines().enumerate() {
            let line_number = index + 1;
            let line = raw_line.trim();
            if line.is_empty() {
                continue;
            }
            report.lines_read += 1;

            let value: Value = match serde_json::from_str(line) {
                Ok(value) => value,
                Err(err) => {
                    let item = rejected_line_item(
                        root,
                        source_file,
                        line_number,
                        "invalid-json-line",
                        &format!("linea JSONL invalida: {}", err),
                    );
                    push_line_item(&mut report, item);
                    continue;
                }
            };
            report.parsed_lines += 1;

            let item = classify_canonical_value(
                root,
                source_file,
                line_number,
                &value,
                &role_contract,
                &ai_role_map,
            );
            if let Value::Object(map) = &value {
                template_observations
                    .entry(item.family.clone())
                    .or_default()
                    .push(TemplateObservation {
                        signature: sorted_object_keys(map),
                        title: item
                            .title
                            .clone()
                            .unwrap_or_else(|| format!("line:{}", line_number)),
                    });
            }
            push_line_item(&mut report, item);
        }
    }

    report.template_families_with_drift = build_template_family_reports(template_observations);
    for family in &report.template_families_with_drift {
        report.verdict = worst_verdict(report.verdict, family.verdict);
    }
    report.family_profiles = build_family_profile_reports(&report.lines);
    for profile in &report.family_profiles {
        report.verdict = worst_verdict(report.verdict, profile.verdict);
    }
    report.incomplete_line_triage = build_incomplete_line_triage(&report.lines);
    report.role_contract_audit = build_role_contract_audit(&role_contract, &report.lines);
    report.modal_projection_audit = build_modal_projection_audit(&report.lines);
    report.debt_summary = build_debt_summary(&report);
    report
}

/// Detecta estructura interna aprovechable dentro de nodos sin reescribirlos.
pub fn inspect_deep_nodes(repo_root: &Path, input_path: &Path) -> DeepNodeInspectionReport {
    let root = repo_root;
    let input = resolve_quality_path(root, input_path);
    let mut source_files = collect_deep_node_input_files(&input);
    source_files.sort();

    let mut report = DeepNodeInspectionReport {
        verdict: DeepNodeInspectorVerdict::NoStructureFound,
        repo_root: root.to_string_lossy().to_string(),
        input_path: display_quality_path(root, &input),
        source_files: source_files
            .iter()
            .map(|path| display_quality_path(root, path))
            .collect(),
        nodes_read: 0,
        inspected_text_fields: 0,
        findings_count: 0,
        counts: DeepNodeFindingCounts::default(),
        findings: Vec::new(),
    };

    for source_file in &source_files {
        let records = read_node_records(source_file);
        for record in records {
            let Value::Object(map) = record.value else {
                continue;
            };
            report.nodes_read += 1;
            let title = map.get("title").and_then(Value::as_str).map(str::to_string);
            let fields = text_fields_from_object(&map);
            report.inspected_text_fields += fields.len();
            for (field_name, text) in fields {
                inspect_text_field(
                    root,
                    source_file,
                    record.line,
                    title.clone(),
                    &field_name,
                    &text,
                    &mut report,
                );
            }
        }
    }

    report.findings_count = report.findings.len();
    report.verdict = if report.counts.invalid_json > 0 {
        DeepNodeInspectorVerdict::StructureFoundWithWarnings
    } else if report.findings_count > 0 {
        DeepNodeInspectorVerdict::StructureFound
    } else {
        DeepNodeInspectorVerdict::NoStructureFound
    };
    report
}

fn classify_canonical_value(
    root: &Path,
    source_file: &Path,
    line_number: usize,
    value: &Value,
    role_contract: &RoleContractIndex,
    ai_role_map: &BTreeMap<String, String>,
) -> CanonicalLineItemReport {
    let Some(map) = value.as_object() else {
        return rejected_line_item(
            root,
            source_file,
            line_number,
            "line-not-object",
            "la linea canonica debe ser un objeto JSON",
        );
    };

    let title = map.get("title").and_then(Value::as_str).map(str::to_string);
    let role_primary = map
        .get("role_primary")
        .and_then(Value::as_str)
        .map(str::to_string);
    let modality = map
        .get("modality")
        .and_then(Value::as_str)
        .map(str::to_string);
    let family = artifact_family(map, title.as_deref());
    let mut issues = Vec::new();

    for field in map.keys() {
        if !ALLOWED_TOP_LEVEL_FIELDS.contains(&field.as_str()) {
            issues.push(issue(
                "unknown-top-level-field",
                CanonicalLineVerdict::CanonLineInconsistent,
                &format!(
                    "campo top-level no permitido por la politica canonica: {}",
                    field
                ),
            ));
        }
    }

    check_required_string(
        map,
        "schema_version",
        CanonicalLineVerdict::CanonLineIncomplete,
        &mut issues,
    );
    if let Some(schema) = map.get("schema_version").and_then(Value::as_str) {
        if schema != "v0" {
            issues.push(issue(
                "wrong-schema-version",
                CanonicalLineVerdict::CanonLineRejected,
                &format!("schema_version debe ser v0, encontrado {}", schema),
            ));
        }
    }
    check_required_string(
        map,
        "key",
        CanonicalLineVerdict::CanonLineIncomplete,
        &mut issues,
    );
    check_required_string(
        map,
        "title",
        CanonicalLineVerdict::CanonLineIncomplete,
        &mut issues,
    );

    if let (Some(key), Some(title)) = (
        map.get("key").and_then(Value::as_str),
        map.get("title").and_then(Value::as_str),
    ) {
        if key != title {
            issues.push(issue(
                "key-title-mismatch",
                CanonicalLineVerdict::CanonLineInconsistent,
                "key debe conservar el mismo anclaje que title",
            ));
        }
    }

    for field in CORE_EXPECTED_FIELDS {
        if !map.contains_key(*field) {
            issues.push(issue(
                "missing-core-canon-field",
                CanonicalLineVerdict::CanonLineIncomplete,
                &format!("falta campo canonico esperado: {}", field),
            ));
        }
    }
    for field in RICHNESS_EXPECTED_FIELDS {
        if !map.contains_key(*field) {
            issues.push(issue(
                "missing-richness-field",
                CanonicalLineVerdict::CanonLineWarning,
                &format!("falta campo de riqueza/procedencia recomendado: {}", field),
            ));
        }
    }

    check_optional_string(map, "id", &mut issues);
    check_optional_string(map, "canonical_slug", &mut issues);
    check_optional_string(map, "version_id", &mut issues);
    check_optional_string(map, "content_type", &mut issues);
    check_optional_string(map, "modality", &mut issues);
    check_optional_string(map, "encoding", &mut issues);
    check_optional_string(map, "role_primary", &mut issues);
    check_optional_string(map, "raw_payload_ref", &mut issues);
    check_optional_string(map, "mime_type", &mut issues);
    check_optional_string(map, "document_id", &mut issues);
    check_optional_string(map, "source_type", &mut issues);
    check_optional_string(map, "source_position", &mut issues);
    check_optional_string(map, "source_role", &mut issues);
    check_optional_string(map, "created", &mut issues);
    check_optional_string(map, "modified", &mut issues);
    check_optional_bool(map, "is_binary", &mut issues);
    check_optional_bool(map, "is_reference_only", &mut issues);
    check_optional_integer(map, "order_in_document", &mut issues);
    check_optional_array_or_null(map, "tags", &mut issues);
    check_optional_array_or_null(map, "roles_secondary", &mut issues);
    check_optional_array_or_null(map, "taxonomy_path", &mut issues);
    check_optional_array_or_null(map, "normalized_tags", &mut issues);
    check_optional_array_or_null(map, "source_tags", &mut issues);
    check_optional_array_or_null(map, "section_path", &mut issues);
    check_optional_array_or_null(map, "relations", &mut issues);
    check_optional_object(map, "content", &mut issues);
    check_optional_object(map, "source_fields", &mut issues);

    if let Some(id) = map.get("id").and_then(Value::as_str) {
        if !is_uuid_like(id) {
            issues.push(issue(
                "id-not-uuid-like",
                CanonicalLineVerdict::CanonLineInconsistent,
                "id debe tener forma UUID estable",
            ));
        }
    }
    if let Some(version_id) = map.get("version_id").and_then(Value::as_str) {
        if !is_sha256_label(version_id) {
            issues.push(issue(
                "version-id-not-sha256",
                CanonicalLineVerdict::CanonLineInconsistent,
                "version_id debe tener forma sha256:<64 hex>",
            ));
        }
    }
    for field in ["created", "modified"] {
        if let Some(timestamp) = map.get(field).and_then(Value::as_str) {
            if !is_tiddlywiki_timestamp(timestamp) {
                issues.push(issue(
                    "timestamp-shape-warning",
                    CanonicalLineVerdict::CanonLineWarning,
                    &format!("{} no parece timestamp TW5 YYYYMMDDHHmmssSSS", field),
                ));
            }
        }
    }
    if let Some(role) = map.get("role_primary").and_then(Value::as_str) {
        let role_eval = evaluate_role_contract(role_contract, role);
        match role_eval.verdict.as_str() {
            "role_ok" => {}
            "role_alias_mapped" => issues.push(issue(
                "role-alias-mapped",
                CanonicalLineVerdict::CanonLineWarning,
                &format!(
                    "role_primary usa alias permitido {}; canonical_role={}",
                    role,
                    role_eval.canonical_role.as_deref().unwrap_or("")
                ),
            )),
            "role_legacy_detected" => issues.push(issue(
                "role-legacy-detected",
                CanonicalLineVerdict::CanonLineWarning,
                &format!(
                    "role_primary legado transicional {}; canonical_role={}",
                    role,
                    role_eval.canonical_role.as_deref().unwrap_or("")
                ),
            )),
            "role_ambiguous" => issues.push(issue(
                "role-ambiguous",
                CanonicalLineVerdict::CanonLineInconsistent,
                &format!(
                    "role_primary ambiguo {}; candidatos={:?}",
                    role, role_eval.candidate_roles
                ),
            )),
            _ => issues.push(issue(
                "role-invalid",
                CanonicalLineVerdict::CanonLineInconsistent,
                &format!("role_primary no pertenece al contrato S79: {}", role),
            )),
        }
        if let (Some(id), Some(ai_role)) = (
            map.get("id").and_then(Value::as_str),
            map.get("id")
                .and_then(Value::as_str)
                .and_then(|id| ai_role_map.get(id)),
        ) {
            if ai_role != role {
                issues.push(issue(
                    "role-cross-layer-mismatch",
                    CanonicalLineVerdict::CanonLineWarning,
                    &format!(
                        "role_primary difiere entre canon y AI: canon={} ai={} id={}",
                        role, ai_role, id
                    ),
                ));
            }
        }
    }
    if let Some(modality) = map.get("modality").and_then(Value::as_str) {
        if !CONTROLLED_MODALITIES.contains(&modality) {
            issues.push(issue(
                "modality-outside-known-vocabulary",
                CanonicalLineVerdict::CanonLineWarning,
                &format!("modality fuera del vocabulario observado: {}", modality),
            ));
        }
    }

    for field in [
        "id",
        "key",
        "title",
        "canonical_slug",
        "version_id",
        "content_type",
        "role_primary",
        "document_id",
        "source_position",
    ] {
        if let Some(value) = map.get(field).and_then(Value::as_str) {
            if contains_placeholder(value) {
                issues.push(issue(
                    "placeholder-in-structural-field",
                    CanonicalLineVerdict::CanonLineRejected,
                    &format!("{} contiene marcador pendiente o placeholder", field),
                ));
            }
        }
    }

    if !has_source_anchor(map) {
        issues.push(issue(
            "weak-source-anchor",
            CanonicalLineVerdict::CanonLineWarning,
            "la linea no declara source_position, raw_payload_ref ni source_fields.source_path",
        ));
    }

    if title
        .as_deref()
        .map(is_session_artifact_title)
        .unwrap_or(false)
    {
        if !has_session_origin(map) {
            issues.push(issue(
                "session-artifact-without-session-origin",
                CanonicalLineVerdict::CanonLineWarning,
                "artefacto de sesion sin session_origin/source tag session:* verificable",
            ));
        }
        if !source_fields_string(map, "artifact_family").is_some() {
            issues.push(issue(
                "session-artifact-without-artifact-family",
                CanonicalLineVerdict::CanonLineWarning,
                "artefacto de sesion sin source_fields.artifact_family",
            ));
        }
        if !source_fields_string(map, "source_path").is_some() {
            issues.push(issue(
                "session-artifact-without-source-path",
                CanonicalLineVerdict::CanonLineWarning,
                "artefacto de sesion sin source_fields.source_path bajo data/sessions",
            ));
        }
    }

    let modal_projections = content_projection_kinds(map);
    apply_modal_projection_profile(map, &modal_projections, &mut issues);
    apply_family_profile(&family, map, title.as_deref(), &mut issues);

    let verdict = issues
        .iter()
        .fold(CanonicalLineVerdict::CanonLineOk, |current, item| {
            worst_verdict(current, item.impact)
        });

    CanonicalLineItemReport {
        source_path: display_quality_path(root, source_file),
        line: line_number,
        title,
        role_primary,
        modality,
        family,
        verdict,
        field_count: map.len(),
        modal_projections,
        issues,
    }
}

fn push_line_item(report: &mut CanonicalLineGateReport, item: CanonicalLineItemReport) {
    report.verdict = worst_verdict(report.verdict, item.verdict);
    match item.verdict {
        CanonicalLineVerdict::CanonLineOk => report.counts.canon_line_ok += 1,
        CanonicalLineVerdict::CanonLineWarning => report.counts.canon_line_warning += 1,
        CanonicalLineVerdict::CanonLineIncomplete => report.counts.canon_line_incomplete += 1,
        CanonicalLineVerdict::CanonLineInconsistent => report.counts.canon_line_inconsistent += 1,
        CanonicalLineVerdict::CanonLineRejected => report.counts.canon_line_rejected += 1,
    }
    report.lines.push(item);
}

fn rejected_line_item(
    root: &Path,
    source_file: &Path,
    line: usize,
    rule_id: &str,
    message: &str,
) -> CanonicalLineItemReport {
    CanonicalLineItemReport {
        source_path: display_quality_path(root, source_file),
        line,
        title: None,
        role_primary: None,
        modality: None,
        family: "unparseable".to_string(),
        verdict: CanonicalLineVerdict::CanonLineRejected,
        field_count: 0,
        modal_projections: Vec::new(),
        issues: vec![issue(
            rule_id,
            CanonicalLineVerdict::CanonLineRejected,
            message,
        )],
    }
}

fn load_role_contract_index(root: &Path) -> RoleContractIndex {
    let path = root.join(ROLE_CONTRACT_REL_PATH);
    let contract_ref = display_quality_path(root, &path);
    let content = match std::fs::read_to_string(&path) {
        Ok(content) => content,
        Err(err) => {
            return RoleContractIndex {
                contract_ref,
                canonical_roles: BTreeSet::new(),
                aliases_allowed: BTreeMap::new(),
                legacy_accepted: BTreeMap::new(),
                ambiguous_roles: BTreeMap::new(),
                load_error: Some(format!("no se pudo leer role contract: {}", err)),
            };
        }
    };
    let value: Value = match serde_json::from_str(&content) {
        Ok(value) => value,
        Err(err) => {
            return RoleContractIndex {
                contract_ref,
                canonical_roles: BTreeSet::new(),
                aliases_allowed: BTreeMap::new(),
                legacy_accepted: BTreeMap::new(),
                ambiguous_roles: BTreeMap::new(),
                load_error: Some(format!("role contract no es JSON valido: {}", err)),
            };
        }
    };
    let Some(contract) = value
        .get("role_primary_contract")
        .and_then(Value::as_object)
    else {
        return RoleContractIndex {
            contract_ref,
            canonical_roles: BTreeSet::new(),
            aliases_allowed: BTreeMap::new(),
            legacy_accepted: BTreeMap::new(),
            ambiguous_roles: BTreeMap::new(),
            load_error: Some(
                "role_primary_contract ausente en canon_policy_bundle.json".to_string(),
            ),
        };
    };

    let canonical_roles = string_array_field(contract, "canonical_roles")
        .into_iter()
        .map(|role| normalize_role(&role))
        .filter(|role| !role.is_empty())
        .collect::<BTreeSet<_>>();
    let aliases_allowed = string_map_field(contract, "aliases_allowed");
    let ambiguous_roles = string_array_map_field(contract, "ambiguous_roles");
    let legacy_accepted = legacy_map_field(contract, "legacy_accepted_transitional");

    let load_error = if canonical_roles.is_empty() {
        Some("role_primary_contract.canonical_roles esta vacio".to_string())
    } else if !canonical_roles.contains("unclassified") {
        Some("role_primary_contract.canonical_roles no incluye unclassified".to_string())
    } else {
        None
    };

    RoleContractIndex {
        contract_ref,
        canonical_roles,
        aliases_allowed,
        legacy_accepted,
        ambiguous_roles,
        load_error,
    }
}

fn string_array_field(map: &serde_json::Map<String, Value>, field: &str) -> Vec<String> {
    map.get(field)
        .and_then(Value::as_array)
        .map(|items| {
            items
                .iter()
                .filter_map(Value::as_str)
                .map(str::to_string)
                .collect()
        })
        .unwrap_or_default()
}

fn string_map_field(map: &serde_json::Map<String, Value>, field: &str) -> BTreeMap<String, String> {
    map.get(field)
        .and_then(Value::as_object)
        .map(|items| {
            items
                .iter()
                .filter_map(|(key, value)| {
                    value
                        .as_str()
                        .map(|target| (normalize_role(key), normalize_role(target)))
                })
                .filter(|(key, value)| !key.is_empty() && !value.is_empty())
                .collect()
        })
        .unwrap_or_default()
}

fn string_array_map_field(
    map: &serde_json::Map<String, Value>,
    field: &str,
) -> BTreeMap<String, Vec<String>> {
    map.get(field)
        .and_then(Value::as_object)
        .map(|items| {
            items
                .iter()
                .map(|(key, value)| {
                    let values = value
                        .as_array()
                        .map(|array| {
                            array
                                .iter()
                                .filter_map(Value::as_str)
                                .map(str::to_string)
                                .collect()
                        })
                        .unwrap_or_default();
                    (normalize_role(key), values)
                })
                .filter(|(key, _)| !key.is_empty())
                .collect()
        })
        .unwrap_or_default()
}

fn legacy_map_field(
    map: &serde_json::Map<String, Value>,
    field: &str,
) -> BTreeMap<String, Option<String>> {
    map.get(field)
        .and_then(Value::as_object)
        .map(|items| {
            items
                .iter()
                .map(|(key, value)| {
                    let canonical = value
                        .as_object()
                        .and_then(|object| object.get("canonical_role"))
                        .and_then(Value::as_str)
                        .map(normalize_role);
                    (normalize_role(key), canonical)
                })
                .filter(|(key, _)| !key.is_empty())
                .collect()
        })
        .unwrap_or_default()
}

fn evaluate_role_contract(contract: &RoleContractIndex, role: &str) -> RoleContractEvaluation {
    if let Some(error) = &contract.load_error {
        return RoleContractEvaluation {
            verdict: "role_invalid".to_string(),
            canonical_role: None,
            candidate_roles: vec![error.clone()],
        };
    }

    let normalized = normalize_role(role);
    if contract.canonical_roles.contains(&normalized) {
        return RoleContractEvaluation {
            verdict: "role_ok".to_string(),
            canonical_role: Some(normalized),
            candidate_roles: Vec::new(),
        };
    }
    if let Some(canonical) = contract.aliases_allowed.get(&normalized) {
        return RoleContractEvaluation {
            verdict: "role_alias_mapped".to_string(),
            canonical_role: Some(canonical.clone()),
            candidate_roles: Vec::new(),
        };
    }
    if let Some(canonical) = contract.legacy_accepted.get(&normalized) {
        if let Some(canonical) = canonical {
            return RoleContractEvaluation {
                verdict: "role_legacy_detected".to_string(),
                canonical_role: Some(canonical.clone()),
                candidate_roles: Vec::new(),
            };
        }
        return RoleContractEvaluation {
            verdict: "role_ambiguous".to_string(),
            canonical_role: None,
            candidate_roles: contract
                .ambiguous_roles
                .get(&normalized)
                .cloned()
                .unwrap_or_default(),
        };
    }
    if let Some(candidates) = contract.ambiguous_roles.get(&normalized) {
        return RoleContractEvaluation {
            verdict: "role_ambiguous".to_string(),
            canonical_role: None,
            candidate_roles: candidates.clone(),
        };
    }
    RoleContractEvaluation {
        verdict: "role_invalid".to_string(),
        canonical_role: None,
        candidate_roles: Vec::new(),
    }
}

fn load_ai_role_map(root: &Path) -> BTreeMap<String, String> {
    let ai_dir = root.join("data/out/local/ai");
    let mut paths = match std::fs::read_dir(&ai_dir) {
        Ok(entries) => entries
            .filter_map(Result::ok)
            .map(|entry| entry.path())
            .filter(|path| {
                path.file_name()
                    .and_then(|name| name.to_str())
                    .map(|name| name.starts_with("tiddlers_ai_") && name.ends_with(".jsonl"))
                    .unwrap_or(false)
            })
            .collect::<Vec<_>>(),
        Err(_) => return BTreeMap::new(),
    };
    paths.sort();
    let mut roles = BTreeMap::new();
    for path in paths {
        let Ok(content) = std::fs::read_to_string(path) else {
            continue;
        };
        for line in content.lines() {
            let line = line.trim();
            if line.is_empty() {
                continue;
            }
            let Ok(Value::Object(map)) = serde_json::from_str::<Value>(line) else {
                continue;
            };
            if let (Some(id), Some(role)) = (
                map.get("id").and_then(Value::as_str),
                map.get("role_primary").and_then(Value::as_str),
            ) {
                roles.insert(id.to_string(), role.to_string());
            }
        }
    }
    roles
}

fn empty_role_contract_audit(contract: &RoleContractIndex) -> RoleContractAuditReport {
    RoleContractAuditReport {
        contract_ref: contract.contract_ref.clone(),
        canonical_roles: contract.canonical_roles.iter().cloned().collect(),
        lines_with_role: 0,
        counts: RoleContractCounts::default(),
        examples: BTreeMap::new(),
    }
}

fn build_role_contract_audit(
    contract: &RoleContractIndex,
    lines: &[CanonicalLineItemReport],
) -> RoleContractAuditReport {
    let mut report = empty_role_contract_audit(contract);
    if let Some(error) = &contract.load_error {
        report
            .examples
            .entry("role_invalid".to_string())
            .or_default()
            .push(error.clone());
    }
    for line in lines {
        let Some(role) = line.role_primary.as_deref() else {
            continue;
        };
        report.lines_with_role += 1;
        let eval = evaluate_role_contract(contract, role);
        increment_role_contract_count(&mut report.counts, &eval.verdict);
        push_role_example(&mut report.examples, &eval.verdict, line);
        if line
            .issues
            .iter()
            .any(|issue| issue.rule_id == "role-cross-layer-mismatch")
        {
            report.counts.role_cross_layer_mismatch += 1;
            push_role_example(&mut report.examples, "role_cross_layer_mismatch", line);
        }
    }
    report
}

fn increment_role_contract_count(counts: &mut RoleContractCounts, verdict: &str) {
    match verdict {
        "role_ok" => counts.role_ok += 1,
        "role_alias_mapped" => counts.role_alias_mapped += 1,
        "role_legacy_detected" => counts.role_legacy_detected += 1,
        "role_ambiguous" => counts.role_ambiguous += 1,
        "role_invalid" => counts.role_invalid += 1,
        "role_cross_layer_mismatch" => counts.role_cross_layer_mismatch += 1,
        _ => {}
    }
}

fn push_role_example(
    examples: &mut BTreeMap<String, Vec<String>>,
    verdict: &str,
    line: &CanonicalLineItemReport,
) {
    let bucket = examples.entry(verdict.to_string()).or_default();
    if bucket.len() >= 5 {
        return;
    }
    let title = line
        .title
        .clone()
        .unwrap_or_else(|| format!("{}:{}", line.source_path, line.line));
    bucket.push(title);
}

fn normalize_role(value: &str) -> String {
    value.trim().to_lowercase()
}

fn issue(rule_id: &str, impact: CanonicalLineVerdict, message: &str) -> CanonicalLineIssue {
    let severity = match impact {
        CanonicalLineVerdict::CanonLineOk => "info",
        CanonicalLineVerdict::CanonLineWarning | CanonicalLineVerdict::CanonLineIncomplete => {
            "warning"
        }
        CanonicalLineVerdict::CanonLineInconsistent | CanonicalLineVerdict::CanonLineRejected => {
            "error"
        }
    };
    CanonicalLineIssue {
        rule_id: rule_id.to_string(),
        severity: severity.to_string(),
        impact,
        message: message.to_string(),
    }
}

fn check_required_string(
    map: &serde_json::Map<String, Value>,
    field: &str,
    impact: CanonicalLineVerdict,
    issues: &mut Vec<CanonicalLineIssue>,
) {
    match map.get(field) {
        Some(Value::String(value)) if !value.trim().is_empty() => {}
        Some(Value::String(_)) => issues.push(issue(
            "empty-required-string",
            impact,
            &format!("{} esta vacio", field),
        )),
        Some(_) => issues.push(issue(
            "required-field-wrong-type",
            CanonicalLineVerdict::CanonLineInconsistent,
            &format!("{} debe ser string no vacio", field),
        )),
        None => issues.push(issue(
            "missing-required-field",
            impact,
            &format!("falta campo requerido: {}", field),
        )),
    }
}

fn check_optional_string(
    map: &serde_json::Map<String, Value>,
    field: &str,
    issues: &mut Vec<CanonicalLineIssue>,
) {
    if let Some(value) = map.get(field) {
        if !value.is_string() && !value.is_null() {
            issues.push(issue(
                "field-wrong-type",
                CanonicalLineVerdict::CanonLineInconsistent,
                &format!("{} debe ser string o null", field),
            ));
        }
    }
}

fn check_optional_bool(
    map: &serde_json::Map<String, Value>,
    field: &str,
    issues: &mut Vec<CanonicalLineIssue>,
) {
    if let Some(value) = map.get(field) {
        if !value.is_boolean() {
            issues.push(issue(
                "field-wrong-type",
                CanonicalLineVerdict::CanonLineInconsistent,
                &format!("{} debe ser boolean", field),
            ));
        }
    }
}

fn check_optional_integer(
    map: &serde_json::Map<String, Value>,
    field: &str,
    issues: &mut Vec<CanonicalLineIssue>,
) {
    if let Some(value) = map.get(field) {
        if value.as_i64().is_none() {
            issues.push(issue(
                "field-wrong-type",
                CanonicalLineVerdict::CanonLineInconsistent,
                &format!("{} debe ser entero", field),
            ));
        }
    }
}

fn check_optional_array_or_null(
    map: &serde_json::Map<String, Value>,
    field: &str,
    issues: &mut Vec<CanonicalLineIssue>,
) {
    if let Some(value) = map.get(field) {
        if !value.is_array() && !value.is_null() {
            issues.push(issue(
                "field-wrong-type",
                CanonicalLineVerdict::CanonLineInconsistent,
                &format!("{} debe ser array o null", field),
            ));
        }
    }
}

fn check_optional_object(
    map: &serde_json::Map<String, Value>,
    field: &str,
    issues: &mut Vec<CanonicalLineIssue>,
) {
    if let Some(value) = map.get(field) {
        if !value.is_object() && !value.is_null() {
            issues.push(issue(
                "field-wrong-type",
                CanonicalLineVerdict::CanonLineInconsistent,
                &format!("{} debe ser objeto o null", field),
            ));
        }
    }
}

fn content_projection_kinds(map: &serde_json::Map<String, Value>) -> Vec<String> {
    let Some(Value::Object(content)) = map.get("content") else {
        return Vec::new();
    };

    let mut kinds = BTreeSet::new();
    if content
        .get("plain")
        .and_then(Value::as_str)
        .map(|value| !value.trim().is_empty())
        .unwrap_or(false)
    {
        kinds.insert("text".to_string());
    }
    if content.get("asset").and_then(Value::as_object).is_some() {
        kinds.insert("asset".to_string());
    }
    for (field, kind) in [
        ("code_blocks", "code"),
        ("equations", "equation"),
        ("references", "reference"),
    ] {
        if content
            .get(field)
            .and_then(Value::as_array)
            .map(|items| !items.is_empty())
            .unwrap_or(false)
        {
            kinds.insert(kind.to_string());
        }
    }
    if content
        .get("structured_payload")
        .and_then(Value::as_object)
        .is_some()
    {
        kinds.insert("structured_payload".to_string());
    }
    if let Some(Value::Array(modalities)) = content.get("modalities") {
        for modality in modalities.iter().filter_map(Value::as_str) {
            if !modality.trim().is_empty() {
                kinds.insert(modality.trim().to_string());
            }
        }
    }
    if let Some(kind) = content.get("projection_kind").and_then(Value::as_str) {
        if !kind.trim().is_empty() && kind != "mixed" {
            kinds.insert(kind.trim().to_string());
        }
    }
    kinds.into_iter().collect()
}

fn apply_modal_projection_profile(
    map: &serde_json::Map<String, Value>,
    modal_projections: &[String],
    issues: &mut Vec<CanonicalLineIssue>,
) {
    let role = map
        .get("role_primary")
        .and_then(Value::as_str)
        .unwrap_or("");
    let modality = map.get("modality").and_then(Value::as_str).unwrap_or("");
    let is_binary = map
        .get("is_binary")
        .and_then(Value::as_bool)
        .unwrap_or(false);
    let is_reference_only = map
        .get("is_reference_only")
        .and_then(Value::as_bool)
        .unwrap_or(false);
    let content = map.get("content").and_then(Value::as_object);

    if content.is_some() && modal_projections.is_empty() {
        issues.push(issue(
            "modal-projection-empty-content",
            CanonicalLineVerdict::CanonLineWarning,
            "content existe pero no expone plain, asset, code_blocks, equations, references ni structured_payload",
        ));
    }

    let asset_like = role == "asset"
        || modality == "image"
        || modality == "binary"
        || is_binary
        || is_reference_only;
    if asset_like {
        match content {
            Some(content) if content.get("asset").and_then(Value::as_object).is_some() => {
                check_asset_projection_shape(content, issues);
            }
            Some(_) => issues.push(issue(
                "modal-projection-asset-subprojection-missing",
                CanonicalLineVerdict::CanonLineIncomplete,
                "activo o binario tiene content pero no content.asset",
            )),
            None => issues.push(issue(
                "modal-projection-missing",
                CanonicalLineVerdict::CanonLineWarning,
                "linea asset/binaria sin proyeccion modal content",
            )),
        }
    }

    if modality == "code" && !modal_projections.iter().any(|item| item == "code") {
        issues.push(issue(
            "modal-projection-code-missing",
            CanonicalLineVerdict::CanonLineIncomplete,
            "nodo con modality=code sin content.code_blocks",
        ));
    }
    if modality == "equation" && !modal_projections.iter().any(|item| item == "equation") {
        issues.push(issue(
            "modal-projection-equation-missing",
            CanonicalLineVerdict::CanonLineIncomplete,
            "nodo con modality=equation sin content.equations",
        ));
    }
    if modality == "mixed" {
        let declared_count = content
            .and_then(|content| content.get("modalities"))
            .and_then(Value::as_array)
            .map(|items| items.len())
            .unwrap_or(0);
        if declared_count < 2 || modal_projections.len() < 2 {
            issues.push(issue(
                "modal-projection-mixed-underdeclared",
                CanonicalLineVerdict::CanonLineWarning,
                "nodo mixto debe declarar al menos dos modalidades proyectadas",
            ));
        }
    }
}

fn check_asset_projection_shape(
    content: &serde_json::Map<String, Value>,
    issues: &mut Vec<CanonicalLineIssue>,
) {
    let Some(Value::Object(asset)) = content.get("asset") else {
        return;
    };
    for field in ["asset_id", "mime_type", "encoding", "payload_ref"] {
        if !asset
            .get(field)
            .and_then(Value::as_str)
            .map(|value| !value.trim().is_empty())
            .unwrap_or(false)
        {
            issues.push(issue(
                "modal-projection-asset-anchor-missing",
                CanonicalLineVerdict::CanonLineWarning,
                &format!("content.asset no declara {}", field),
            ));
        }
    }
    if asset.get("payload_present").and_then(Value::as_bool) == Some(true)
        && !asset
            .get("payload_sha256")
            .and_then(Value::as_str)
            .map(is_sha256_label)
            .unwrap_or(false)
    {
        issues.push(issue(
            "modal-projection-asset-payload-hash-missing",
            CanonicalLineVerdict::CanonLineWarning,
            "content.asset declara payload presente sin payload_sha256 valido",
        ));
    }
}

fn apply_family_profile(
    family: &str,
    map: &serde_json::Map<String, Value>,
    title: Option<&str>,
    issues: &mut Vec<CanonicalLineIssue>,
) {
    if let Some(profile) = session_family_profile(family) {
        if let Some(title) = title {
            if !title.starts_with(profile.title_prefix) {
                issues.push(issue(
                    "family-profile-title-prefix-mismatch",
                    CanonicalLineVerdict::CanonLineInconsistent,
                    &format!(
                        "familia {} espera titulos con prefijo '{}'",
                        family, profile.title_prefix
                    ),
                ));
            }
        }

        if let Some(declared) = source_fields_string_from_map(map, "artifact_family") {
            if declared != family {
                issues.push(issue(
                    "family-profile-artifact-family-mismatch",
                    CanonicalLineVerdict::CanonLineInconsistent,
                    &format!(
                        "source_fields.artifact_family declara {} pero la familia detectada es {}",
                        declared, family
                    ),
                ));
            }
        }

        for field in SESSION_PROFILE_SOURCE_FIELDS {
            if source_fields_string_from_map(map, field).is_none() {
                issues.push(issue(
                    "family-profile-missing-source-field",
                    CanonicalLineVerdict::CanonLineWarning,
                    &format!(
                        "perfil {} recomienda source_fields.{} para trazabilidad estable",
                        family, field
                    ),
                ));
            }
        }

        if let Some(source_path) = source_fields_string_from_map(map, "source_path") {
            if !source_path.starts_with(profile.source_path_prefix) {
                issues.push(issue(
                    "family-profile-source-path-outside-family",
                    CanonicalLineVerdict::CanonLineInconsistent,
                    &format!(
                        "source_fields.source_path debe vivir bajo {}",
                        profile.source_path_prefix
                    ),
                ));
            }
        }

        for prefix in SESSION_PROFILE_TAG_PREFIXES {
            if !has_tag_with_prefix(map, prefix) {
                issues.push(issue(
                    "family-profile-missing-tag-prefix",
                    CanonicalLineVerdict::CanonLineWarning,
                    &format!("perfil {} recomienda tag con prefijo {}", family, prefix),
                ));
            }
        }
        let artifact_tag = format!("artifact:{}", family);
        if !has_exact_tag(map, &artifact_tag) {
            issues.push(issue(
                "family-profile-missing-artifact-tag",
                CanonicalLineVerdict::CanonLineWarning,
                &format!("perfil {} recomienda tag {}", family, artifact_tag),
            ));
        }

        if !map.contains_key("source_role") {
            issues.push(issue(
                "family-profile-missing-source-role",
                CanonicalLineVerdict::CanonLineWarning,
                &format!(
                    "perfil {} recomienda source_role para estabilizar la plantilla moderna",
                    family
                ),
            ));
        }
        return;
    }

    if family == "role:asset" {
        for field in [
            "asset_id",
            "raw_payload_ref",
            "mime_type",
            "source_type",
            "source_position",
            "text",
        ] {
            if !map.contains_key(field) {
                issues.push(issue(
                    "family-profile-asset-missing-anchor",
                    CanonicalLineVerdict::CanonLineIncomplete,
                    &format!("activo canonico sin anclaje esperado: {}", field),
                ));
            }
        }

        if map.get("content").is_none() {
            let impact = if map
                .get("is_binary")
                .and_then(Value::as_bool)
                .unwrap_or(false)
            {
                CanonicalLineVerdict::CanonLineWarning
            } else {
                CanonicalLineVerdict::CanonLineIncomplete
            };
            issues.push(issue(
                "family-profile-asset-content-projection-missing",
                impact,
                "activo sin campo content; en binarios puede ser excepcion documentable, no admision automatica",
            ));
        } else if !modal_projections_include_asset(map) {
            issues.push(issue(
                "family-profile-asset-modal-projection-missing",
                CanonicalLineVerdict::CanonLineIncomplete,
                "activo con content pero sin subproyeccion asset verificable",
            ));
        }
    }
}

fn modal_projections_include_asset(map: &serde_json::Map<String, Value>) -> bool {
    map.get("content")
        .and_then(Value::as_object)
        .and_then(|content| content.get("asset"))
        .and_then(Value::as_object)
        .is_some()
}

fn profile_baseline_signature(family: &str) -> Option<Vec<String>> {
    if session_family_profile(family).is_some() {
        return Some(sorted_field_slice(SESSION_PROFILE_TOP_LEVEL_FIELDS));
    }
    if family == "role:asset" {
        return Some(sorted_field_slice(ASSET_PROFILE_TOP_LEVEL_FIELDS));
    }
    None
}

fn core_or_profile_required_field(family: &str, field: &str) -> bool {
    if session_family_profile(family).is_some() {
        return SESSION_PROFILE_TOP_LEVEL_FIELDS.contains(&field);
    }
    if family == "role:asset" {
        return ASSET_PROFILE_TOP_LEVEL_FIELDS.contains(&field);
    }
    CORE_EXPECTED_FIELDS.contains(&field)
}

fn build_template_family_reports(
    observations: HashMap<String, Vec<TemplateObservation>>,
) -> Vec<TemplateFamilyReport> {
    let mut reports = Vec::new();
    for (family, items) in observations {
        if items.len() < 2 {
            continue;
        }

        let mut variants: BTreeMap<Vec<String>, Vec<String>> = BTreeMap::new();
        for item in items {
            variants.entry(item.signature).or_default().push(item.title);
        }
        if variants.len() < 2 {
            continue;
        }

        let (baseline, baseline_source) =
            if let Some(profile_baseline) = profile_baseline_signature(&family) {
                (profile_baseline, "family_profile".to_string())
            } else {
                (
                    variants
                        .iter()
                        .max_by(|(left_sig, left_examples), (right_sig, right_examples)| {
                            left_examples
                                .len()
                                .cmp(&right_examples.len())
                                .then_with(|| right_sig.len().cmp(&left_sig.len()))
                        })
                        .map(|(signature, _)| signature.clone())
                        .unwrap_or_default(),
                    "observed_majority".to_string(),
                )
            };

        let mut verdict = CanonicalLineVerdict::CanonLineWarning;
        let mut variant_reports = Vec::new();
        for (signature, examples) in variants {
            let missing = diff_fields(&baseline, &signature);
            let extra = diff_fields(&signature, &baseline);
            if missing
                .iter()
                .any(|field| core_or_profile_required_field(&family, field))
            {
                verdict = worst_verdict(verdict, CanonicalLineVerdict::CanonLineIncomplete);
            }
            variant_reports.push(TemplateVariantReport {
                count: examples.len(),
                signature,
                missing_from_baseline: missing,
                extra_vs_baseline: extra,
                examples: examples.into_iter().take(5).collect(),
            });
        }
        variant_reports.sort_by(|a, b| b.count.cmp(&a.count));
        reports.push(TemplateFamilyReport {
            family,
            verdict,
            line_count: variant_reports.iter().map(|variant| variant.count).sum(),
            variant_count: variant_reports.len(),
            baseline_source,
            baseline_signature: baseline,
            variants: variant_reports,
        });
    }
    reports.sort_by(|a, b| {
        b.variant_count
            .cmp(&a.variant_count)
            .then_with(|| b.line_count.cmp(&a.line_count))
            .then_with(|| a.family.cmp(&b.family))
    });
    reports
}

fn build_family_profile_reports(lines: &[CanonicalLineItemReport]) -> Vec<FamilyProfileReport> {
    let mut by_family: BTreeMap<String, Vec<&CanonicalLineItemReport>> = BTreeMap::new();
    for line in lines {
        if is_profiled_family(&line.family) {
            by_family.entry(line.family.clone()).or_default().push(line);
        }
    }

    let mut reports = Vec::new();
    for (family, items) in by_family {
        let mut issue_groups: BTreeMap<(String, CanonicalLineVerdict), BTreeSet<String>> =
            BTreeMap::new();
        let mut verdict = CanonicalLineVerdict::CanonLineOk;
        let mut issue_count = 0;
        for item in &items {
            for issue in item
                .issues
                .iter()
                .filter(|issue| issue.rule_id.starts_with(FAMILY_PROFILE_RULE_PREFIX))
            {
                issue_count += 1;
                verdict = worst_verdict(verdict, issue.impact);
                let example = item
                    .title
                    .clone()
                    .unwrap_or_else(|| format!("{}:{}", item.source_path, item.line));
                issue_groups
                    .entry((issue.rule_id.clone(), issue.impact))
                    .or_default()
                    .insert(example);
            }
        }

        let mut issues = Vec::new();
        for ((rule_id, impact), examples) in issue_groups {
            issues.push(FamilyProfileIssueSummary {
                rule_id,
                impact,
                count: examples.len(),
                examples: examples.into_iter().take(5).collect(),
            });
        }
        issues.sort_by(|a, b| {
            verdict_rank(b.impact)
                .cmp(&verdict_rank(a.impact))
                .then_with(|| b.count.cmp(&a.count))
                .then_with(|| a.rule_id.cmp(&b.rule_id))
        });

        reports.push(FamilyProfileReport {
            profile_id: profile_id_for_family(&family).to_string(),
            priority: profile_priority_for_family(&family).to_string(),
            family,
            line_count: items.len(),
            verdict,
            issue_count,
            issues,
        });
    }

    reports.sort_by(|a, b| {
        verdict_rank(b.verdict)
            .cmp(&verdict_rank(a.verdict))
            .then_with(|| b.issue_count.cmp(&a.issue_count))
            .then_with(|| b.line_count.cmp(&a.line_count))
            .then_with(|| a.family.cmp(&b.family))
    });
    reports
}

fn empty_modal_projection_audit() -> ModalProjectionAuditReport {
    ModalProjectionAuditReport {
        profile_id: "canonical-modal-projection-profile-v1".to_string(),
        inspected_lines: 0,
        relevant_lines: 0,
        projected_lines: 0,
        missing_projection_lines: 0,
        modality_counts: BTreeMap::new(),
        projection_counts: BTreeMap::new(),
        issues: Vec::new(),
    }
}

fn build_modal_projection_audit(lines: &[CanonicalLineItemReport]) -> ModalProjectionAuditReport {
    let mut report = empty_modal_projection_audit();
    report.inspected_lines = lines.len();

    for line in lines {
        if line.family == "unparseable" {
            continue;
        }
        for projection in &line.modal_projections {
            *report
                .projection_counts
                .entry(projection.clone())
                .or_insert(0) += 1;
        }
        if !line.modal_projections.is_empty() {
            report.projected_lines += 1;
        }

        let modality_value = line.modality.clone();
        let role_value = line
            .role_primary
            .clone()
            .or_else(|| role_from_family(&line.family));
        if let Some(value) = modality_value.as_ref().filter(|value| !value.is_empty()) {
            *report.modality_counts.entry(value.clone()).or_insert(0) += 1;
        }

        let relevant = is_modal_projection_relevant(line, modality_value.as_deref());
        if relevant {
            report.relevant_lines += 1;
        }
        if relevant && line.modal_projections.is_empty() {
            report.missing_projection_lines += 1;
        }

        for issue in line.issues.iter().filter(|issue| {
            issue.rule_id.starts_with("modal-projection-")
                || issue.rule_id == "family-profile-asset-content-projection-missing"
                || issue.rule_id == "family-profile-asset-modal-projection-missing"
        }) {
            report.issues.push(ModalProjectionIssueReport {
                source_path: line.source_path.clone(),
                line: line.line,
                title: line.title.clone(),
                role_primary: role_value.clone(),
                modality: modality_value.clone(),
                rule_id: issue.rule_id.clone(),
                severity: issue.severity.clone(),
                message: issue.message.clone(),
            });
        }
    }

    report
}

fn build_debt_summary(report: &CanonicalLineGateReport) -> CanonQualityDebtSummary {
    let mut modal_debt_lines = BTreeSet::new();
    let mut asset_modal_debt_lines = BTreeSet::new();
    let mut modal_debt_issue_count = 0;
    let mut modal_debt_families = BTreeSet::new();
    let mut richness_warning_lines = BTreeSet::new();
    let mut incomplete_line_count = 0;
    let mut blocking_line_count = 0;

    for line in &report.lines {
        if line.verdict == CanonicalLineVerdict::CanonLineIncomplete {
            incomplete_line_count += 1;
        }
        if matches!(
            line.verdict,
            CanonicalLineVerdict::CanonLineInconsistent | CanonicalLineVerdict::CanonLineRejected
        ) {
            blocking_line_count += 1;
        }

        let line_key = format!("{}:{}", line.source_path, line.line);
        let mut line_has_modal_debt = false;
        for issue in &line.issues {
            if is_modal_debt_rule(&issue.rule_id) {
                modal_debt_issue_count += 1;
                line_has_modal_debt = true;
            }
            if issue.rule_id == "missing-richness-field" {
                richness_warning_lines.insert(line_key.clone());
            }
        }
        if line_has_modal_debt {
            modal_debt_lines.insert(line_key);
            modal_debt_families.insert(line.family.clone());
            if line.family == "role:asset" || line.role_primary.as_deref() == Some("asset") {
                asset_modal_debt_lines.insert(format!("{}:{}", line.source_path, line.line));
            }
        }
    }

    let template_drift_families_total = report.template_families_with_drift.len();
    let mut template_drift_families_modal_related = 0;
    let mut template_drift_lines_historical = 0;
    for family in &report.template_families_with_drift {
        if modal_debt_families.contains(&family.family) {
            template_drift_families_modal_related += 1;
        } else {
            template_drift_lines_historical += family.line_count;
        }
    }
    let template_drift_families_historical =
        template_drift_families_total.saturating_sub(template_drift_families_modal_related);

    CanonQualityDebtSummary {
        profile_id: "canonical-quality-debt-separation-v1".to_string(),
        modal_debt_lines: modal_debt_lines.len(),
        modal_debt_issue_count,
        asset_modal_debt_lines: asset_modal_debt_lines.len(),
        template_drift_families_total,
        template_drift_families_modal_related,
        template_drift_families_historical,
        template_drift_lines_historical,
        richness_warning_lines: richness_warning_lines.len(),
        incomplete_line_count,
        blocking_line_count,
    }
}

fn is_modal_debt_rule(rule_id: &str) -> bool {
    rule_id.starts_with("modal-projection-")
        || rule_id == "family-profile-asset-content-projection-missing"
        || rule_id == "family-profile-asset-modal-projection-missing"
}

fn is_modal_projection_relevant(line: &CanonicalLineItemReport, modality: Option<&str>) -> bool {
    if line.family == "role:asset" {
        return true;
    }
    matches!(
        modality,
        Some("image")
            | Some("binary")
            | Some("code")
            | Some("equation")
            | Some("mixed")
            | Some("metadata")
    )
}

fn role_from_family(family: &str) -> Option<String> {
    family
        .strip_prefix("role:")
        .filter(|value| !value.is_empty())
        .map(str::to_string)
}

fn build_incomplete_line_triage(
    lines: &[CanonicalLineItemReport],
) -> Vec<IncompleteLineTriageReport> {
    let mut groups: BTreeMap<(String, String), Vec<&CanonicalLineItemReport>> = BTreeMap::new();
    for line in lines
        .iter()
        .filter(|line| line.verdict == CanonicalLineVerdict::CanonLineIncomplete)
    {
        let reason = primary_incomplete_reason(line);
        groups
            .entry((line.family.clone(), reason.to_string()))
            .or_default()
            .push(line);
    }

    let mut reports = Vec::new();
    for ((family, reason), items) in groups {
        let mut rule_ids = Vec::new();
        for item in &items {
            for issue in item
                .issues
                .iter()
                .filter(|issue| issue.impact == CanonicalLineVerdict::CanonLineIncomplete)
            {
                if !rule_ids.contains(&issue.rule_id) {
                    rule_ids.push(issue.rule_id.clone());
                }
            }
        }
        rule_ids.sort();

        reports.push(IncompleteLineTriageReport {
            priority: triage_priority(&family, &reason).to_string(),
            family,
            reason,
            line_count: items.len(),
            rule_ids,
            examples: items
                .into_iter()
                .take(8)
                .map(|item| {
                    let title = item.title.as_deref().unwrap_or("<sin titulo>");
                    format!("{}:{} {}", item.source_path, item.line, title)
                })
                .collect(),
        });
    }

    reports.sort_by(|a, b| {
        triage_rank(&a.priority)
            .cmp(&triage_rank(&b.priority))
            .then_with(|| b.line_count.cmp(&a.line_count))
            .then_with(|| a.family.cmp(&b.family))
    });
    reports
}

fn primary_incomplete_reason(line: &CanonicalLineItemReport) -> &'static str {
    if line.family == "role:asset"
        && line.issues.iter().any(|issue| {
            issue.rule_id == "missing-core-canon-field" && issue.message.ends_with("content")
        })
    {
        return "asset_without_content_projection";
    }
    if line
        .issues
        .iter()
        .any(|issue| issue.rule_id == "missing-core-canon-field")
    {
        return "missing_core_canon_field";
    }
    if line
        .issues
        .iter()
        .any(|issue| issue.rule_id == "missing-required-field")
    {
        return "missing_identity_field";
    }
    "other_incomplete_profile_or_shape"
}

fn triage_priority(family: &str, reason: &str) -> &'static str {
    match (family, reason) {
        ("role:asset", "asset_without_content_projection") => "medium",
        (_, "missing_identity_field") => "high",
        (_, "missing_core_canon_field") => "high",
        _ => "medium",
    }
}

fn triage_rank(priority: &str) -> u8 {
    match priority {
        "high" => 0,
        "medium" => 1,
        "low" => 2,
        _ => 3,
    }
}

fn inspect_text_field(
    root: &Path,
    source_file: &Path,
    line: usize,
    title: Option<String>,
    field: &str,
    text: &str,
    report: &mut DeepNodeInspectionReport,
) {
    let trimmed = text.trim();
    if trimmed.is_empty() {
        return;
    }

    let mut direct_json_found = false;
    if looks_like_json(trimmed) {
        direct_json_found = true;
        push_json_finding(
            root,
            source_file,
            line,
            title.clone(),
            field,
            "embedded_json",
            trimmed,
            None,
            report,
        );
    }

    for block in json_fence_blocks(text) {
        push_json_finding(
            root,
            source_file,
            line,
            title.clone(),
            field,
            "json_fence",
            &block.content,
            Some(&block.context),
            report,
        );
        report.counts.json_fence += 1;
    }

    if has_yaml_front_matter(trimmed) {
        report.counts.yaml_front_matter += 1;
        report.findings.push(DeepNodeFinding {
            source_path: display_quality_path(root, source_file),
            line,
            title: title.clone(),
            field: field.to_string(),
            kind: "yaml_front_matter".to_string(),
            status: "detected".to_string(),
            byte_count: trimmed.len(),
            top_level_type: None,
            top_level_keys: Vec::new(),
            array_len: None,
            recovery_actions: Vec::new(),
            message: "front matter YAML detectable al inicio del texto".to_string(),
        });
    }

    if !direct_json_found && has_markdown_table(trimmed) {
        report.counts.markdown_table += 1;
        report.findings.push(DeepNodeFinding {
            source_path: display_quality_path(root, source_file),
            line,
            title: title.clone(),
            field: field.to_string(),
            kind: "markdown_table".to_string(),
            status: "detected".to_string(),
            byte_count: trimmed.len(),
            top_level_type: None,
            top_level_keys: Vec::new(),
            array_len: None,
            recovery_actions: Vec::new(),
            message: "tabla markdown interna detectable".to_string(),
        });
    }

    if !direct_json_found && has_key_value_block(trimmed) {
        report.counts.key_value_block += 1;
        report.findings.push(DeepNodeFinding {
            source_path: display_quality_path(root, source_file),
            line,
            title,
            field: field.to_string(),
            kind: "key_value_block".to_string(),
            status: "detected".to_string(),
            byte_count: trimmed.len(),
            top_level_type: None,
            top_level_keys: Vec::new(),
            array_len: None,
            recovery_actions: Vec::new(),
            message: "bloque key/value interno detectable".to_string(),
        });
    }
}

fn push_json_finding(
    root: &Path,
    source_file: &Path,
    line: usize,
    title: Option<String>,
    field: &str,
    kind: &str,
    raw: &str,
    context: Option<&str>,
    report: &mut DeepNodeInspectionReport,
) {
    if is_pedagogical_json(kind, raw, context, title.as_deref()) {
        report.counts.pedagogical_json += 1;
        report.findings.push(DeepNodeFinding {
            source_path: display_quality_path(root, source_file),
            line,
            title,
            field: field.to_string(),
            kind: kind.to_string(),
            status: "pedagogical_json".to_string(),
            byte_count: raw.len(),
            top_level_type: None,
            top_level_keys: Vec::new(),
            array_len: None,
            recovery_actions: Vec::new(),
            message:
                "bloque JSON ilustrativo o de fixture; no se interpreta como payload estructural"
                    .to_string(),
        });
        return;
    }

    match serde_json::from_str::<Value>(raw) {
        Ok(value) => {
            report.counts.structural_json += 1;
            report.counts.valid_json += 1;
            let (top_level_type, top_level_keys, array_len) = summarize_json_value(&value);
            report.findings.push(DeepNodeFinding {
                source_path: display_quality_path(root, source_file),
                line,
                title,
                field: field.to_string(),
                kind: kind.to_string(),
                status: "valid_json".to_string(),
                byte_count: raw.len(),
                top_level_type: Some(top_level_type),
                top_level_keys,
                array_len,
                recovery_actions: Vec::new(),
                message: "JSON incrustado valido; no se reescribio el nodo".to_string(),
            });
        }
        Err(err) => {
            let (fragment, fragment_actions) = repair_json_fragment(raw);
            if let Ok(value) = serde_json::from_str::<Value>(&fragment) {
                if !fragment_actions.is_empty() {
                    report.counts.structural_json += 1;
                    report.counts.recoverable_json += 1;
                    report.counts.json_fragment += 1;
                    let (top_level_type, top_level_keys, array_len) = summarize_json_value(&value);
                    report.findings.push(DeepNodeFinding {
                        source_path: display_quality_path(root, source_file),
                        line,
                        title,
                        field: field.to_string(),
                        kind: kind.to_string(),
                        status: "recoverable_json_fragment".to_string(),
                        byte_count: raw.len(),
                        top_level_type: Some(top_level_type),
                        top_level_keys,
                        array_len,
                        recovery_actions: fragment_actions,
                        message: "fragmento JSON recuperable para auditoria; el texto original no fue modificado".to_string(),
                    });
                    return;
                }
            }

            let (repaired, actions) = repair_json_like(raw);
            match serde_json::from_str::<Value>(&repaired) {
                Ok(value) if !actions.is_empty() => {
                    report.counts.structural_json += 1;
                    report.counts.recoverable_json += 1;
                    let (top_level_type, top_level_keys, array_len) = summarize_json_value(&value);
                    report.findings.push(DeepNodeFinding {
                        source_path: display_quality_path(root, source_file),
                        line,
                        title,
                        field: field.to_string(),
                        kind: kind.to_string(),
                        status: "recoverable_json".to_string(),
                        byte_count: raw.len(),
                        top_level_type: Some(top_level_type),
                        top_level_keys,
                        array_len,
                        recovery_actions: actions,
                        message: "JSON casi valido recuperable en reporte; el texto original no fue modificado".to_string(),
                    });
                }
                _ => {
                    report.counts.invalid_json += 1;
                    report.findings.push(DeepNodeFinding {
                        source_path: display_quality_path(root, source_file),
                        line,
                        title,
                        field: field.to_string(),
                        kind: kind.to_string(),
                        status: "invalid_json".to_string(),
                        byte_count: raw.len(),
                        top_level_type: None,
                        top_level_keys: Vec::new(),
                        array_len: None,
                        recovery_actions: actions,
                        message: format!("parece JSON pero no pudo parsearse: {}", err),
                    });
                }
            }
        }
    }
}

fn read_node_records(source_file: &Path) -> Vec<NodeRecord> {
    let content = match std::fs::read_to_string(source_file) {
        Ok(content) => content,
        Err(_) => return Vec::new(),
    };

    if source_file
        .extension()
        .and_then(|ext| ext.to_str())
        .map(|ext| ext.eq_ignore_ascii_case("json"))
        .unwrap_or(false)
    {
        if let Ok(Value::Array(items)) = serde_json::from_str::<Value>(&content) {
            return items
                .into_iter()
                .enumerate()
                .map(|(index, value)| NodeRecord {
                    line: index + 1,
                    value,
                })
                .collect();
        }
    }

    content
        .lines()
        .enumerate()
        .filter_map(|(index, line)| {
            let trimmed = line.trim();
            if trimmed.is_empty() {
                return None;
            }
            serde_json::from_str::<Value>(trimmed)
                .ok()
                .map(|value| NodeRecord {
                    line: index + 1,
                    value,
                })
        })
        .collect()
}

fn text_fields_from_object(map: &serde_json::Map<String, Value>) -> Vec<(String, String)> {
    let mut fields = Vec::new();
    let mut seen_values = Vec::new();
    if let Some(text) = map.get("text").and_then(Value::as_str) {
        fields.push(("text".to_string(), text.to_string()));
        seen_values.push(text.to_string());
    }
    if let Some(Value::Object(content)) = map.get("content") {
        for key in ["plain", "markdown"] {
            if let Some(value) = content.get(key).and_then(Value::as_str) {
                if !seen_values.iter().any(|seen| seen == value) {
                    fields.push((format!("content.{}", key), value.to_string()));
                    seen_values.push(value.to_string());
                }
            }
        }
    }
    fields
}

fn collect_canonical_input_files(input: &Path) -> Vec<PathBuf> {
    if input.is_file() {
        return vec![input.to_path_buf()];
    }
    if !input.is_dir() {
        return Vec::new();
    }
    let mut files = Vec::new();
    if let Ok(entries) = std::fs::read_dir(input) {
        for entry in entries.flatten() {
            let path = entry.path();
            if path.is_file() && is_jsonl_path(&path) {
                files.push(path);
            }
        }
    }
    files
}

fn collect_deep_node_input_files(input: &Path) -> Vec<PathBuf> {
    if input.is_file() {
        return vec![input.to_path_buf()];
    }
    collect_canonical_input_files(input)
}

fn resolve_quality_path(root: &Path, value: &Path) -> PathBuf {
    if value.is_absolute() {
        value.to_path_buf()
    } else {
        root.join(value)
    }
}

fn display_quality_path(root: &Path, path: &Path) -> String {
    path.strip_prefix(root)
        .unwrap_or(path)
        .to_string_lossy()
        .to_string()
}

fn is_jsonl_path(path: &Path) -> bool {
    path.extension()
        .and_then(|ext| ext.to_str())
        .map(|ext| ext.eq_ignore_ascii_case("jsonl"))
        .unwrap_or(false)
}

fn sorted_object_keys(map: &serde_json::Map<String, Value>) -> Vec<String> {
    let mut keys: Vec<String> = map.keys().cloned().collect();
    keys.sort();
    keys
}

fn sorted_field_slice(fields: &[&str]) -> Vec<String> {
    let mut keys: Vec<String> = fields.iter().map(|field| field.to_string()).collect();
    keys.sort();
    keys
}

struct SessionFamilyProfile {
    title_prefix: &'static str,
    source_path_prefix: &'static str,
}

fn session_family_profile(family: &str) -> Option<SessionFamilyProfile> {
    match family {
        "contrato_de_sesion" => Some(SessionFamilyProfile {
            title_prefix: "#### 🌀 Contrato de sesión",
            source_path_prefix: "data/sessions/00_contratos/",
        }),
        "procedencia_de_sesion" => Some(SessionFamilyProfile {
            title_prefix: "#### 🌀🧾 Procedencia de sesión",
            source_path_prefix: "data/sessions/01_procedencia/",
        }),
        "detalles_de_sesion" => Some(SessionFamilyProfile {
            title_prefix: "#### 🌀 Sesión",
            source_path_prefix: "data/sessions/02_detalles_de_sesion/",
        }),
        "hipotesis_de_sesion" => Some(SessionFamilyProfile {
            title_prefix: "#### 🌀🧪 Hipótesis de sesión",
            source_path_prefix: "data/sessions/03_hipotesis/",
        }),
        "balance_de_sesion" => Some(SessionFamilyProfile {
            title_prefix: "#### 🌀 Balance de sesión",
            source_path_prefix: "data/sessions/04_balance_de_sesion/",
        }),
        "propuesta_de_sesion" => Some(SessionFamilyProfile {
            title_prefix: "#### 🌀 Propuesta de sesión",
            source_path_prefix: "data/sessions/05_propuesta_de_sesion/",
        }),
        "diagnostico_de_sesion" => Some(SessionFamilyProfile {
            title_prefix: "#### 🌀 Diagnóstico de sesión",
            source_path_prefix: "data/sessions/06_diagnoses/sesion/",
        }),
        _ => None,
    }
}

fn is_profiled_family(family: &str) -> bool {
    session_family_profile(family).is_some() || family == "role:asset"
}

fn profile_id_for_family(family: &str) -> &'static str {
    if session_family_profile(family).is_some() {
        "session-artifact-profile-v1"
    } else if family == "role:asset" {
        "asset-canonical-payload-profile-v1"
    } else {
        "unprofiled"
    }
}

fn profile_priority_for_family(family: &str) -> &'static str {
    if session_family_profile(family).is_some() {
        "high"
    } else if family == "role:asset" {
        "medium"
    } else {
        "low"
    }
}

fn artifact_family(map: &serde_json::Map<String, Value>, title: Option<&str>) -> String {
    if let Some(family) = source_fields_string_from_map(map, "artifact_family") {
        return family.to_string();
    }
    if let Some(title) = title {
        if title.starts_with("#### 🌀 Contrato de sesión") {
            return "contrato_de_sesion".to_string();
        }
        if title.starts_with("#### 🌀🧾 Procedencia de sesión") {
            return "procedencia_de_sesion".to_string();
        }
        if title.starts_with("#### 🌀 Sesión") {
            return "detalles_de_sesion".to_string();
        }
        if title.starts_with("#### 🌀🧪 Hipótesis de sesión") {
            return "hipotesis_de_sesion".to_string();
        }
        if title.starts_with("#### 🌀 Balance de sesión") {
            return "balance_de_sesion".to_string();
        }
        if title.starts_with("#### 🌀 Propuesta de sesión") {
            return "propuesta_de_sesion".to_string();
        }
        if title.starts_with("#### 🌀 Diagnóstico de sesión") {
            return "diagnostico_de_sesion".to_string();
        }
    }
    if let Some(role) = map.get("role_primary").and_then(Value::as_str) {
        return format!("role:{}", role);
    }
    if let Some(source_type) = map.get("source_type").and_then(Value::as_str) {
        return format!("source_type:{}", source_type);
    }
    "unclassified".to_string()
}

fn source_fields_string(map: &serde_json::Map<String, Value>, key: &str) -> Option<String> {
    source_fields_string_from_map(map, key).map(str::to_string)
}

fn source_fields_string_from_map<'a>(
    map: &'a serde_json::Map<String, Value>,
    key: &str,
) -> Option<&'a str> {
    map.get("source_fields")
        .and_then(Value::as_object)
        .and_then(|fields| fields.get(key))
        .and_then(Value::as_str)
        .filter(|value| !value.trim().is_empty())
}

fn tag_values(map: &serde_json::Map<String, Value>) -> Vec<&str> {
    let mut tags = Vec::new();
    for key in ["tags", "source_tags", "normalized_tags"] {
        if let Some(Value::Array(values)) = map.get(key) {
            tags.extend(values.iter().filter_map(Value::as_str));
        }
    }
    tags
}

fn has_tag_with_prefix(map: &serde_json::Map<String, Value>, prefix: &str) -> bool {
    tag_values(map)
        .iter()
        .any(|tag| tag.trim().starts_with(prefix))
}

fn has_exact_tag(map: &serde_json::Map<String, Value>, expected: &str) -> bool {
    tag_values(map).iter().any(|tag| tag.trim() == expected)
}

fn has_source_anchor(map: &serde_json::Map<String, Value>) -> bool {
    for key in ["source_position", "raw_payload_ref"] {
        if map
            .get(key)
            .and_then(Value::as_str)
            .map(|value| !value.trim().is_empty())
            .unwrap_or(false)
        {
            return true;
        }
    }
    source_fields_string_from_map(map, "source_path").is_some()
}

fn has_session_origin(map: &serde_json::Map<String, Value>) -> bool {
    if source_fields_string_from_map(map, "session_origin").is_some() {
        return true;
    }
    for key in ["source_tags", "tags"] {
        if let Some(Value::Array(tags)) = map.get(key) {
            if tags
                .iter()
                .filter_map(Value::as_str)
                .any(|tag| tag.starts_with("session:"))
            {
                return true;
            }
        }
    }
    false
}

fn is_session_artifact_title(title: &str) -> bool {
    title.starts_with("#### 🌀")
}

fn contains_placeholder(value: &str) -> bool {
    let lower = value.to_lowercase();
    lower.contains("pendiente")
        || lower.contains("todo")
        || lower.contains("resolver luego")
        || lower.contains("fixme")
}

fn is_uuid_like(value: &str) -> bool {
    let uuid = value.strip_prefix("urn:uuid:").unwrap_or(value);
    if uuid.len() != 36 {
        return false;
    }
    for (index, byte) in uuid.bytes().enumerate() {
        match index {
            8 | 13 | 18 | 23 => {
                if byte != b'-' {
                    return false;
                }
            }
            _ => {
                if !byte.is_ascii_hexdigit() {
                    return false;
                }
            }
        }
    }
    true
}

fn is_sha256_label(value: &str) -> bool {
    let Some(hex) = value.strip_prefix("sha256:") else {
        return false;
    };
    hex.len() == 64 && hex.bytes().all(|byte| byte.is_ascii_hexdigit())
}

fn is_tiddlywiki_timestamp(value: &str) -> bool {
    value.len() == 17 && value.bytes().all(|byte| byte.is_ascii_digit())
}

fn diff_fields(left: &[String], right: &[String]) -> Vec<String> {
    left.iter()
        .filter(|field| !right.contains(field))
        .cloned()
        .collect()
}

fn worst_verdict(left: CanonicalLineVerdict, right: CanonicalLineVerdict) -> CanonicalLineVerdict {
    if verdict_rank(right) > verdict_rank(left) {
        right
    } else {
        left
    }
}

fn verdict_rank(verdict: CanonicalLineVerdict) -> u8 {
    match verdict {
        CanonicalLineVerdict::CanonLineOk => 0,
        CanonicalLineVerdict::CanonLineWarning => 1,
        CanonicalLineVerdict::CanonLineIncomplete => 2,
        CanonicalLineVerdict::CanonLineInconsistent => 3,
        CanonicalLineVerdict::CanonLineRejected => 4,
    }
}

fn looks_like_json(value: &str) -> bool {
    value.starts_with('{') || value.starts_with('[')
}

fn summarize_json_value(value: &Value) -> (String, Vec<String>, Option<usize>) {
    match value {
        Value::Object(map) => {
            let mut keys: Vec<String> = map.keys().take(20).cloned().collect();
            keys.sort();
            ("object".to_string(), keys, None)
        }
        Value::Array(items) => ("array".to_string(), Vec::new(), Some(items.len())),
        Value::Null => ("null".to_string(), Vec::new(), None),
        Value::Bool(_) => ("bool".to_string(), Vec::new(), None),
        Value::Number(_) => ("number".to_string(), Vec::new(), None),
        Value::String(_) => ("string".to_string(), Vec::new(), None),
    }
}

fn json_fence_blocks(text: &str) -> Vec<JsonFenceBlock> {
    let lower = text.to_ascii_lowercase();
    let mut blocks = Vec::new();
    let mut offset = 0;
    while let Some(start_rel) = lower[offset..].find("```json") {
        let fence_start = offset + start_rel;
        let Some(line_end_rel) = text[fence_start..].find('\n') else {
            break;
        };
        let content_start = fence_start + line_end_rel + 1;
        let Some(end_rel) = text[content_start..].find("```") else {
            break;
        };
        let content_end = content_start + end_rel;
        blocks.push(JsonFenceBlock {
            content: text[content_start..content_end].trim().to_string(),
            context: fence_context(text, fence_start),
        });
        offset = content_end + 3;
    }
    blocks
}

fn fence_context(text: &str, fence_start: usize) -> String {
    let prefix = &text[..fence_start.min(text.len())];
    let mut context_lines: Vec<&str> = prefix
        .lines()
        .rev()
        .filter(|line| !line.trim().is_empty())
        .take(4)
        .collect();
    context_lines.reverse();
    context_lines.join("\n")
}

fn has_yaml_front_matter(text: &str) -> bool {
    if !text.starts_with("---\n") {
        return false;
    }
    text[4..].contains("\n---")
}

fn has_markdown_table(text: &str) -> bool {
    let mut has_row = false;
    let mut has_separator = false;
    for line in text.lines().take(80) {
        let trimmed = line.trim();
        if trimmed.starts_with('|') && trimmed.ends_with('|') {
            has_row = true;
            if trimmed.contains("---") {
                has_separator = true;
            }
        }
    }
    has_row && has_separator
}

fn has_key_value_block(text: &str) -> bool {
    let mut count = 0;
    for line in text.lines().take(40) {
        let trimmed = line.trim();
        if trimmed.starts_with('#') || trimmed.starts_with('-') || trimmed.is_empty() {
            continue;
        }
        let Some((key, value)) = trimmed.split_once(':') else {
            continue;
        };
        if !key.is_empty()
            && !value.trim().is_empty()
            && key
                .bytes()
                .all(|byte| byte.is_ascii_alphanumeric() || byte == b'_' || byte == b'-')
        {
            count += 1;
        }
    }
    count >= 3
}

fn is_pedagogical_json(kind: &str, raw: &str, context: Option<&str>, title: Option<&str>) -> bool {
    if kind != "json_fence" {
        return false;
    }

    let trimmed = raw.trim();
    let lower_raw = trimmed.to_ascii_lowercase();
    let lower_context = context.unwrap_or("").to_ascii_lowercase();
    let lower_title = title.unwrap_or("").to_ascii_lowercase();

    if lower_raw.contains("json.dumps(")
        || lower_raw.contains("esto no es json")
        || lower_raw.contains("//")
        || lower_raw.contains("/*")
        || lower_raw.contains("...")
        || lower_raw.contains("uuid-v5")
        || lower_raw.contains("uuid-v5-del")
        || lower_raw.contains("\"string\"")
        || lower_raw.contains(": \"string")
    {
        return true;
    }

    if lower_context.contains("ejemplo")
        || lower_context.contains("plantilla")
        || lower_context.contains("schema")
        || lower_context.contains("formato")
        || lower_context.contains("fixture")
        || lower_title.contains("readme")
        || lower_title.contains("fixture")
    {
        return true;
    }

    if !looks_like_json(trimmed) && !looks_like_json_object_fragment(trimmed) {
        return true;
    }

    false
}

fn looks_like_json_object_fragment(raw: &str) -> bool {
    let trimmed = raw.trim_start();
    trimmed.starts_with('"') && trimmed.contains("\":")
}

fn repair_json_fragment(raw: &str) -> (String, Vec<String>) {
    let trimmed = raw.trim();
    if looks_like_json_object_fragment(trimmed) {
        return (
            format!("{{{}}}", trimmed),
            vec!["wrapped JSON object fragment with braces".to_string()],
        );
    }
    (raw.to_string(), Vec::new())
}

fn repair_json_like(raw: &str) -> (String, Vec<String>) {
    let mut working = raw.to_string();
    let mut actions = Vec::new();
    for _ in 0..3 {
        if serde_json::from_str::<Value>(&working).is_ok() {
            break;
        }
        let mut changed = false;
        let escaped = repair_invalid_json_escapes(&working);
        if escaped != working {
            working = escaped;
            changed = true;
            if !actions
                .iter()
                .any(|item| item == "repaired invalid JSON escapes")
            {
                actions.push("repaired invalid JSON escapes".to_string());
            }
        }
        if serde_json::from_str::<Value>(&working).is_ok() {
            break;
        }
        let commas = repair_missing_json_array_commas(&working);
        if commas != working {
            working = commas;
            changed = true;
            if !actions
                .iter()
                .any(|item| item == "repaired missing JSON array commas")
            {
                actions.push("repaired missing JSON array commas".to_string());
            }
        }
        if !changed {
            break;
        }
    }
    (working, actions)
}

fn repair_invalid_json_escapes(raw: &str) -> String {
    let bytes = raw.as_bytes();
    let mut out: Vec<u8> = Vec::with_capacity(raw.len() + 16);
    let mut in_string = false;
    let mut index = 0;
    while index < bytes.len() {
        let ch = bytes[index];
        if !in_string {
            out.push(ch);
            if ch == b'"' {
                in_string = true;
            }
            index += 1;
            continue;
        }
        match ch {
            b'"' => {
                in_string = false;
                out.push(b'"');
                index += 1;
            }
            b'\\' => {
                if index + 1 < bytes.len() {
                    let next = bytes[index + 1];
                    if next == b'u'
                        && index + 5 < bytes.len()
                        && is_hex_quartet(&raw[index + 2..index + 6])
                    {
                        out.extend_from_slice(&bytes[index..index + 6]);
                        index += 6;
                        continue;
                    }
                    if is_standard_json_escape(next) {
                        out.push(b'\\');
                        out.push(next);
                        index += 2;
                        continue;
                    }
                }
                out.extend_from_slice(b"\\\\");
                index += 1;
            }
            _ => {
                out.push(ch);
                index += 1;
            }
        }
    }
    String::from_utf8(out).unwrap_or_else(|_| raw.to_string())
}

fn repair_missing_json_array_commas(raw: &str) -> String {
    let bytes = raw.as_bytes();
    let mut out: Vec<u8> = Vec::with_capacity(raw.len() + 16);
    let mut stack: Vec<u8> = Vec::new();
    let mut in_string = false;
    let mut escaped = false;

    for index in 0..bytes.len() {
        let ch = bytes[index];
        out.push(ch);
        if in_string {
            if escaped {
                escaped = false;
                continue;
            }
            match ch {
                b'\\' => escaped = true,
                b'"' => in_string = false,
                _ => {}
            }
            continue;
        }
        match ch {
            b'"' => in_string = true,
            b'{' | b'[' => stack.push(ch),
            b'}' => {
                if stack.last() == Some(&b'{') {
                    stack.pop();
                }
                if inside_json_array(&stack) && next_json_array_value_needs_comma(bytes, index + 1)
                {
                    out.push(b',');
                }
            }
            b']' => {
                if stack.last() == Some(&b'[') {
                    stack.pop();
                }
                if inside_json_array(&stack) && next_json_array_value_needs_comma(bytes, index + 1)
                {
                    out.push(b',');
                }
            }
            _ => {}
        }
    }
    String::from_utf8(out).unwrap_or_else(|_| raw.to_string())
}

fn inside_json_array(stack: &[u8]) -> bool {
    stack.last() == Some(&b'[')
}

fn next_json_array_value_needs_comma(bytes: &[u8], start: usize) -> bool {
    let mut index = start;
    while index < bytes.len() && is_json_whitespace(bytes[index]) {
        index += 1;
    }
    if index >= bytes.len() {
        return false;
    }
    match bytes[index] {
        b',' | b']' => false,
        other => is_json_value_start(other),
    }
}

fn is_json_whitespace(byte: u8) -> bool {
    matches!(byte, b' ' | b'\n' | b'\r' | b'\t')
}

fn is_json_value_start(byte: u8) -> bool {
    matches!(byte, b'"' | b'{' | b'[' | b't' | b'f' | b'n') || is_json_number_start(byte)
}

fn is_json_number_start(byte: u8) -> bool {
    byte.is_ascii_digit() || byte == b'-'
}

fn is_standard_json_escape(byte: u8) -> bool {
    matches!(byte, b'"' | b'\\' | b'/' | b'b' | b'f' | b'n' | b'r' | b't')
}

fn is_hex_quartet(value: &str) -> bool {
    value.len() == 4 && value.bytes().all(|byte| byte.is_ascii_hexdigit())
}

#[derive(Debug)]
struct TemplateObservation {
    signature: Vec<String>,
    title: String,
}

struct NodeRecord {
    line: usize,
    value: Value,
}

struct JsonFenceBlock {
    content: String,
    context: String,
}
