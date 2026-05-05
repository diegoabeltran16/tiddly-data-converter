from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_DIR = REPO_ROOT / "python_scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import session_cycle_diagnostics as scd


def write_session_artifact(
    sessions_dir: Path,
    family: str,
    number: int,
    slug: str = "cycle-test",
    text: str = "## Decisiones a conservar\n- decisión estable\n",
    valid: bool = True,
) -> Path:
    relative = Path(*scd.REQUIRED_SESSION_FAMILIES[family])
    path = sessions_dir / relative / f"m04-s{number}-{slug}.md.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not valid:
        path.write_text("[{\"title\": \"broken\"", encoding="utf-8")
        return path
    payload = [
        {
            "created": "20260505000000000",
            "modified": "20260505000000000",
            "title": f"#### 🌀 Sesión {number} = {slug}",
            "type": "text/markdown",
            "tags": f"[[session:m04-s{number}]] [[milestone:m04]] [[layer:session]]",
            "text": text,
        }
    ]
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def write_microcycle(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ref = scd.parse_microcycle_filename(path)
    assert ref is not None
    payload = [
        {
            "created": "20260505000000000",
            "modified": "20260505000000000",
            "title": scd.microcycle_title(ref.start, ref.end),
            "type": "text/vnd.tiddlywiki",
            "tags": "[[diagnostic:micro-ciclo]]",
            "text": (
                "# micro\n\n"
                "## Decisiones estabilizadas\n- decisión estable\n\n"
                "## Riesgos actuales\n- riesgo acumulado\n\n"
                "## Señales de madurez\n- madurez local-first\n"
            ),
        }
    ]
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_detects_sessions_groups_artifacts_and_marks_invalid(tmp_path: Path):
    sessions_dir = tmp_path / "sessions"
    write_session_artifact(sessions_dir, "contrato", 94, slug="alpha")
    write_session_artifact(sessions_dir, "balance", 94, slug="alpha")
    write_session_artifact(sessions_dir, "contrato", 95, slug="beta", valid=False)

    records = scd.discover_sessions(sessions_dir)

    assert [record.session_id for record in records] == ["m04-s94", "m04-s95"]
    assert records[0].slug == "alpha"
    assert records[0].artifacts["contrato"].valid is True
    assert records[1].artifacts["contrato"].valid is False
    assert "Expecting" in records[1].artifacts["contrato"].error


def test_orders_by_session_number_and_selects_latest_10(tmp_path: Path):
    sessions_dir = tmp_path / "sessions"
    for number in range(80, 95):
        write_session_artifact(sessions_dir, "contrato", number)

    selected = scd.select_latest_sessions(scd.discover_sessions(sessions_dir), count=10)

    assert [record.identity.number for record in selected] == list(range(85, 95))


def test_select_session_range_keeps_absent_sessions_as_placeholders(tmp_path: Path):
    sessions_dir = tmp_path / "sessions"
    write_session_artifact(sessions_dir, "contrato", 79, slug="range-test")
    write_session_artifact(sessions_dir, "balance", 84, slug="range-test")

    selected = scd.select_session_range(scd.discover_sessions(sessions_dir), "m04", 75, 84)

    assert [record.identity.number for record in selected] == list(range(75, 85))
    assert selected[0].slug == "sin-artefactos-locales"
    assert selected[4].session_id == "m04-s79"
    assert selected[-1].session_id == "m04-s84"


def test_microcycle_filename_route_and_title_are_exact():
    assert scd.MICRO_DIAG_DIR.as_posix().endswith("data/out/local/sessions/06_diagnoses/micro-ciclo")
    assert scd.microcycle_filename("m04", 85, 94) == "m04-micro-ciclo-s085-s094-diagnostico.md.json"
    assert scd.microcycle_title(85, 94) == "#### 🌀 Diagnóstico de microciclo = sesiones S85-S94"


def test_mesocycle_filename_route_and_title_are_exact():
    assert scd.MESO_DIAG_DIR.as_posix().endswith("data/out/local/sessions/06_diagnoses/meso-ciclo")
    assert scd.mesocycle_filename("m04", 64, 94) == "m04-meso-ciclo-s064-s094-diagnostico.md.json"
    assert scd.mesocycle_title(64, 94) == "#### 🌀 Diagnóstico de mesociclo = microciclos S64-S94"


def test_routes_do_not_use_prohibited_roots_or_unhyphenated_cycle_names():
    for path in (scd.MICRO_DIAG_DIR, scd.MESO_DIAG_DIR):
        normalized = path.as_posix()
        assert "data/sessions/" not in normalized
        assert "data/out/sessions/" not in normalized
        assert "/microciclo/" not in normalized
        assert "/mesociclo/" not in normalized
        assert "/micro-ciclo" in normalized or "/meso-ciclo" in normalized


def test_write_tiddler_refuses_canon_shards():
    with pytest.raises(ValueError, match="protected canon shard"):
        scd.write_tiddler(
            REPO_ROOT / "data" / "out" / "local" / "tiddlers_1.jsonl",
            {"title": "x", "text": "x"},
        )


def test_build_microcycle_tiddler_has_required_format_and_sections(tmp_path: Path):
    sessions_dir = tmp_path / "sessions"
    for family in scd.REQUIRED_SESSION_FAMILIES:
        write_session_artifact(
            sessions_dir,
            family,
            85,
            text=(
                "## Decisiones a conservar\n- conservar ruta local\n"
                "## Hipótesis confirmadas\n- H confirmada\n"
                "## Riesgos detectados\n- riesgo local\n"
            ),
        )
    record = scd.discover_sessions(sessions_dir)[0]
    tag_plan = scd.build_cycle_tags("m04", "micro-ciclo", 85, 85, existing_tags={"milestone:m04"})
    tiddler = scd.build_microcycle_tiddler([record], tag_plan, [], sessions_dir, timestamp="20260505000000000")

    assert tiddler["title"] == "#### 🌀 Diagnóstico de microciclo = sesiones S85-S85"
    assert tiddler["type"] == "text/vnd.tiddlywiki"
    for heading in (
        "## Tipo de sesión diagnóstica",
        "## Rango de sesiones analizadas",
        "## Lista de sesiones incluidas",
        "## Sesiones ausentes o incompletas",
        "## Artefactos leídos por sesión",
        "## Diagnósticos temáticos consultados",
        "## Evidencia consultada desde canon",
        "## Evidencia consultada desde repositorio",
        "## Decisiones estabilizadas",
        "## Hipótesis confirmadas",
        "## Hipótesis abiertas",
        "## Deuda técnica cerrada",
        "## Deuda técnica persistente",
        "## Deuda técnica nueva",
        "## Cambios en gobernanza de rutas",
        "## Cambios en canon/reverse",
        "## Cambios en CI/CD",
        "## Cambios en seguridad",
        "## Impacto sobre agentes locales/remotos",
        "## Patrones repetidos",
        "## Riesgos actuales",
        "## Señales de madurez",
        "## Señales de deriva",
        "## Pronóstico operativo",
        "## Tags usados y justificación de tags nuevos",
    ):
        assert heading in tiddler["text"]


def test_prognosis_uses_required_three_recommendation_shape(tmp_path: Path):
    sessions_dir = tmp_path / "sessions"
    write_session_artifact(sessions_dir, "contrato", 90, valid=False)
    record = scd.discover_sessions(sessions_dir)[0]
    tag_plan = scd.build_cycle_tags("m04", "micro-ciclo", 90, 90)
    text = scd.build_microcycle_markdown([record], [], tag_plan, sessions_dir)

    assert "### Próxima sesión recomendada" in text
    assert "### Segunda sesión probable" in text
    assert "### Tercera sesión posible" in text
    assert "- Tipo: necesidad real" in text
    assert "- Tipo: mejora conveniente" in text
    assert "- Tipo: tentación prematura" in text
    assert "- Evidencia desde el microciclo:" in text


def test_session_kind_policy_documents_pure_diagnostic_mode(tmp_path: Path):
    sessions_dir = tmp_path / "sessions"
    write_session_artifact(sessions_dir, "contrato", 94)
    record = scd.discover_sessions(sessions_dir)[0]
    tag_plan = scd.build_cycle_tags("m04", "micro-ciclo", 94, 94)
    text = scd.build_microcycle_markdown(
        [record],
        [],
        tag_plan,
        sessions_dir,
        session_kind="diagnostico-puro",
    )

    assert "## Tipo de sesión diagnóstica" in text
    assert "diagnostico-puro" in text
    assert "debe detenerse y reportar bloqueo" in text
    assert "sesion-mixta" in scd.SESSION_KIND_POLICIES
    assert "sesion-practica-desarrollo" in scd.SESSION_KIND_POLICIES
    assert "sesion-teorica-analitica" in scd.SESSION_KIND_POLICIES


def test_mesocycle_is_controlled_output_when_microcycles_are_missing(tmp_path: Path):
    micro_dir = tmp_path / "micro-ciclo"
    write_microcycle(micro_dir / "m04-micro-ciclo-s085-s094-diagnostico.md.json")

    status = scd.plan_mesocycle(micro_dir)

    assert status.can_produce is False
    assert status.reason == "faltan microciclos suficientes"
    assert status.missing_ranges == [(65, 74), (75, 84)]
    assert [item.display for item in status.available] == ["S85-S94"]


def test_mesocycle_missing_ranges_respect_existing_previous_microcycle(tmp_path: Path):
    micro_dir = tmp_path / "micro-ciclo"
    write_microcycle(micro_dir / "m04-micro-ciclo-s075-s084-diagnostico.md.json")
    write_microcycle(micro_dir / "m04-micro-ciclo-s085-s094-diagnostico.md.json")

    status = scd.plan_mesocycle(micro_dir)

    assert status.can_produce is False
    assert status.missing_ranges == [(65, 74)]
    assert [item.display for item in status.available] == ["S75-S84", "S85-S94"]


def test_mesocycle_consumes_three_continuous_microcycles(tmp_path: Path):
    micro_dir = tmp_path / "micro-ciclo"
    for start, end in ((65, 74), (75, 84), (85, 94)):
        write_microcycle(micro_dir / f"m04-micro-ciclo-s{start:03d}-s{end:03d}-diagnostico.md.json")

    status = scd.plan_mesocycle(micro_dir)
    tag_plan = scd.build_cycle_tags(
        "m04",
        "meso-ciclo",
        65,
        94,
        source_microcycles=True,
        diagnostic_provenance=True,
        remote_read_root=True,
    )
    tiddler = scd.build_mesocycle_tiddler(status.selected, tag_plan, [], timestamp="20260505000000000")

    assert status.can_produce is True
    assert [item.display for item in status.selected] == ["S65-S74", "S75-S84", "S85-S94"]
    assert tiddler["title"] == "#### 🌀 Diagnóstico de mesociclo = microciclos S65-S94"
    for heading in (
        "## Rango de microciclos analizados",
        "## Microciclos incluidos",
        "## Archivos de microdiagnóstico leídos",
        "## Validez de cada microdiagnóstico",
        "## Fuentes auxiliares consultadas",
        "## Gobernanza de procedencia aplicada",
        "## Completitud en staging local",
        "## Completitud canónica",
        "## Síntesis de S65-S74",
        "## Síntesis de S75-S84",
        "## Síntesis de S85-S94",
        "## Continuidad entre microciclos",
        "## Cambios de dirección entre microciclos",
        "## Decisiones estabilizadas",
        "## Hipótesis confirmadas",
        "## Hipótesis abiertas",
        "## Deuda técnica persistente",
        "## Deuda técnica cerrada",
        "## Deuda técnica nueva",
        "## Riesgos acumulados",
        "## Señales de madurez",
        "## Señales de deriva",
        "## Impacto sobre canon",
        "## Impacto sobre reverse",
        "## Impacto sobre CI/CD",
        "## Impacto sobre seguridad",
        "## Impacto sobre agente local",
        "## Impacto sobre agente remoto",
        "## Preparación para diagnóstico global del proyecto",
        "## Pronóstico operativo",
        "## Tags usados y justificación de tags nuevos",
    ):
        assert heading in tiddler["text"]
    assert "[[source:micro-ciclos]]" in tiddler["tags"]
    assert "[[governance:diagnostic-provenance]]" in tiddler["tags"]
    assert "[[agent:remote-read-root]]" in tiddler["tags"]


def test_mesocycle_rejects_microdiagnostic_with_wrong_title(tmp_path: Path):
    micro_dir = tmp_path / "micro-ciclo"
    paths = [
        micro_dir / "m04-micro-ciclo-s065-s074-diagnostico.md.json",
        micro_dir / "m04-micro-ciclo-s075-s084-diagnostico.md.json",
        micro_dir / "m04-micro-ciclo-s085-s094-diagnostico.md.json",
    ]
    for path in paths:
        write_microcycle(path)
    raw = json.loads(paths[0].read_text(encoding="utf-8"))
    raw[0]["title"] = "Diagnóstico microciclo S65-S74"
    paths[0].write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")

    status = scd.plan_mesocycle(micro_dir)
    tag_plan = scd.build_cycle_tags("m04", "meso-ciclo", 65, 94, source_microcycles=True)

    with pytest.raises(ValueError, match="invalid microcycle diagnostics"):
        scd.build_mesocycle_tiddler(status.selected, tag_plan, [], timestamp="20260505000000000")


def test_thematic_diagnostics_are_auxiliary_not_primary_source(tmp_path: Path):
    sessions_dir = tmp_path / "sessions"
    write_session_artifact(sessions_dir, "contrato", 94)
    theme_path = sessions_dir / "06_diagnoses" / "tema" / "diagnostico-tematico.md.json"
    theme_path.parent.mkdir(parents=True, exist_ok=True)
    theme_path.write_text(json.dumps([{"title": "tema", "text": "apoyo"}]), encoding="utf-8")

    records = scd.discover_sessions(sessions_dir)
    thematic = scd.discover_thematic_diagnostics(sessions_dir)
    tag_plan = scd.build_cycle_tags("m04", "micro-ciclo", 94, 94)
    text = scd.build_microcycle_markdown(records, thematic, tag_plan, sessions_dir)

    assert [record.session_id for record in records] == ["m04-s94"]
    assert thematic == [theme_path]
    assert "06_diagnoses/tema/diagnostico-tematico.md.json" in text


def test_generate_microcycle_accepts_explicit_range_without_latest_10(tmp_path: Path):
    sessions_dir = tmp_path / "sessions"
    for number in range(79, 85):
        write_session_artifact(sessions_dir, "contrato", number, slug="explicit-range")

    path, tiddler, _status = scd.generate_microcycle(
        sessions_dir=sessions_dir,
        start_session=75,
        end_session=84,
        milestone="m04",
        session_origin="m04-s96-micro-cycle-s075-s084-diagnosis",
    )

    assert path.name == "m04-micro-ciclo-s075-s084-diagnostico.md.json"
    assert tiddler["title"] == "#### 🌀 Diagnóstico de microciclo = sesiones S75-S84"
    assert "- S75: sin artefactos locales" in tiddler["text"]
    assert "## Artefactos leídos por sesión" in tiddler["text"]
    assert "## Evidencia consultada desde canon" in tiddler["text"]


def test_cycle_tags_prefer_existing_tags_and_justify_new_tags():
    existing = {
        "milestone:m04",
        "layer:session",
        "## 🧭🧱 Protocolo de Sesión",
        "## 🌀🧱 Desarrollo y Evolución",
    }

    plan = scd.build_cycle_tags(
        milestone="m04",
        cycle_type="micro-ciclo",
        start=85,
        end=94,
        existing_tags=existing,
        session_origin="m04-s95-local-cycle-diagnostics-and-prognosis",
    )

    assert "milestone:m04" in plan.existing_tags_used
    assert "layer:session" in plan.existing_tags_used
    assert "diagnostic:micro-ciclo" in plan.new_tag_justifications
    assert "range:s085-s094" in plan.new_tag_justifications
    assert "session:m04-s95" in plan.new_tag_justifications
    assert scd.format_tw_tags(plan.tags).count("[[diagnostic:micro-ciclo]]") == 1


def test_no_active_legacy_cycle_route_constants():
    assert "microciclo" not in scd.MICRO_DIAG_DIR.as_posix()
    assert "mesociclo" not in scd.MESO_DIAG_DIR.as_posix()
    assert "micro_ciclo" not in scd.MICRO_DIAG_DIR.as_posix()
    assert "meso_ciclo" not in scd.MESO_DIAG_DIR.as_posix()
