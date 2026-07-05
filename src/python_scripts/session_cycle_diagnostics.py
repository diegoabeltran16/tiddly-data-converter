#!/usr/bin/env python3
"""Local diagnostics for session micro-cycles and meso-cycles.

The active source of raw session evidence is data/out/local/sessions/.
Micro-cycle diagnostics read session artifacts. Meso-cycle diagnostics read
micro-cycle diagnostics only; they do not re-read raw session artifacts.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from path_governance import DEFAULT_SESSIONS_DIR, REPO_ROOT, as_display_path  # noqa: E402


MICRO_DIAG_DIR = DEFAULT_SESSIONS_DIR / "06_diagnoses" / "micro-ciclo"
MESO_DIAG_DIR = DEFAULT_SESSIONS_DIR / "06_diagnoses" / "meso-ciclo"
DEFAULT_CANON_DIR = REPO_ROOT / "data" / "out" / "local"
PROHIBITED_SESSION_ROOTS = (
    REPO_ROOT / "data" / "sessions",
    REPO_ROOT / "data" / "out" / "sessions",
    REPO_ROOT / "sessions",
)
PROHIBITED_CYCLE_ROUTE_NAMES = ("microciclo", "mesociclo")
LEGACY_CYCLE_ROUTE_NAMES = ("micro_ciclo", "meso_ciclo")
CANON_WRITE_GUARD_GLOBS = ("data/out/local/tiddlers_*.jsonl",)

SESSION_FILE_RE = re.compile(r"^(m\d+)-s(\d+)([a-z]?)-(.+)\.md\.json$")
SESSION_TAG_RE = re.compile(r"^session:(m\d+)-s(\d+)([a-z]?)$")
MICRO_FILE_RE = re.compile(
    r"^(m\d+)-micro-ciclo-s(?P<start>\d{3})-s(?P<end>\d{3})-diagnostico\.md\.json$"
)

REQUIRED_SESSION_FAMILIES: dict[str, tuple[str, ...]] = {
    "contrato": ("00_contratos",),
    "procedencia": ("01_procedencia",),
    "detalles": ("02_detalles_de_sesion",),
    "hipotesis": ("03_hipotesis",),
    "balance": ("04_balance_de_sesion",),
    "propuesta": ("05_propuesta_de_sesion",),
    "diagnostico_sesion": ("06_diagnoses", "sesion"),
}

CANON_ARTIFACT_TAG_TO_FAMILY = {
    "artifact:contrato_de_sesion": "contrato",
    "artifact:procedencia_de_sesion": "procedencia",
    "artifact:detalles_de_sesion": "detalles",
    "artifact:hipotesis_de_sesion": "hipotesis",
    "artifact:balance_de_sesion": "balance",
    "artifact:propuesta_de_sesion": "propuesta",
    "artifact:diagnostico_de_sesion": "diagnostico_sesion",
}

THEMATIC_DIAG_FAMILIES: tuple[tuple[str, ...], ...] = (
    ("06_diagnoses", "tema"),
    ("06_diagnoses", "tematico"),
    ("06_diagnoses", "contexto"),
    ("06_diagnoses", "arquitectura"),
    ("06_diagnoses", "seguridad"),
    ("06_diagnoses", "rutas"),
)

PREFERRED_EXISTING_TAGS = (
    "layer:session",
    "## 🧭🧱 Protocolo de Sesión",
    "## 🌀🧱 Desarrollo y Evolución",
    "## 🧠🧱 Política de Memoria Activa",
    "## 🧪🧱 Hipótesis",
    "## 🧾🧱 Procedencia epistemológica",
    "## 🗂🧱 Principios de Gestion",
)

SESSION_KIND_POLICIES = {
    "diagnostico-puro": (
        "lee evidencia y produce diagnóstico; si requiere modificar código, "
        "debe detenerse y reportar bloqueo"
    ),
    "infraestructura-diagnostica": (
        "puede ajustar instrucciones, scripts o tests del flujo diagnóstico y "
        "debe cerrar con los 7 entregables normales"
    ),
    "sesion-mixta": (
        "combina ajuste técnico limitado con diagnóstico mayor y debe declarar "
        "qué parte fue infraestructura y qué parte fue diagnóstico"
    ),
    "sesion-practica-desarrollo": "implementa o corrige superficies del sistema y produce cierre normal",
    "sesion-teorica-analitica": "produce análisis, decisiones o diseño con trazabilidad de memoria",
    "desarrollo-normal": "alias histórico de sesión práctica/desarrollo",
    "hibrida-transicional": "excepción temporal mientras se estabiliza el flujo diagnóstico",
}


@dataclass(frozen=True)
class SessionIdentity:
    milestone: str
    number: int
    suffix: str = ""

    @property
    def session_id(self) -> str:
        return f"{self.milestone}-s{self.number}{self.suffix}"

    @property
    def display(self) -> str:
        return f"S{self.number}{self.suffix}"

    @property
    def sort_key(self) -> tuple[int, int, str]:
        milestone_num = int(self.milestone[1:]) if self.milestone[1:].isdigit() else 0
        return (milestone_num, self.number, self.suffix)


@dataclass
class ArtifactLoad:
    family: str
    path: Path
    valid: bool
    title: str = ""
    text: str = ""
    type: str = ""
    tags: str = ""
    error: str = ""


@dataclass
class SessionRecord:
    identity: SessionIdentity
    slug: str
    artifacts: dict[str, ArtifactLoad] = field(default_factory=dict)

    @property
    def session_id(self) -> str:
        return self.identity.session_id

    @property
    def display(self) -> str:
        return self.identity.display

    @property
    def valid_family_count(self) -> int:
        return sum(1 for artifact in self.artifacts.values() if artifact.valid)

    @property
    def is_complete(self) -> bool:
        return not self.missing_families() and not self.invalid_artifacts()

    def missing_families(self) -> list[str]:
        return [family for family in REQUIRED_SESSION_FAMILIES if family not in self.artifacts]

    def invalid_artifacts(self) -> list[ArtifactLoad]:
        return [artifact for artifact in self.artifacts.values() if not artifact.valid]


@dataclass(frozen=True)
class MicrocycleRef:
    milestone: str
    start: int
    end: int
    path: Path

    @property
    def display(self) -> str:
        return f"S{self.start}-S{self.end}"


@dataclass
class MicrodiagnosticLoad:
    ref: MicrocycleRef
    valid_json: bool
    valid_title: bool
    valid_type: bool
    title: str = ""
    text: str = ""
    type: str = ""
    tags: str = ""
    error: str = ""

    @property
    def is_valid(self) -> bool:
        return self.valid_json and self.valid_title and self.valid_type


@dataclass
class TagPlan:
    tags: list[str]
    existing_tags_used: list[str]
    new_tag_justifications: dict[str, str]


@dataclass
class MesocycleStatus:
    can_produce: bool
    available: list[MicrocycleRef]
    missing_ranges: list[tuple[int, int]]
    reason: str
    selected: list[MicrocycleRef] = field(default_factory=list)


@dataclass(frozen=True)
class CanonEvidence:
    session_id: str
    display: str
    family: str
    title: str
    shard: Path
    line_number: int


def stamp_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S000")


def parse_session_filename(name: str) -> tuple[SessionIdentity, str] | None:
    match = SESSION_FILE_RE.match(name)
    if not match:
        return None
    milestone, number, suffix, slug = match.groups()
    if slug.startswith("session-"):
        slug = slug[len("session-") :]
    return SessionIdentity(milestone=milestone, number=int(number), suffix=suffix), slug


def load_tiddler(path: Path, family: str) -> ArtifactLoad:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            if not payload or not isinstance(payload[0], dict):
                raise ValueError("JSON array does not contain a tiddler object")
            tiddler = payload[0]
        elif isinstance(payload, dict):
            tiddler = payload
        else:
            raise ValueError("JSON payload is not an object or tiddler array")
    except Exception as exc:  # noqa: BLE001 - diagnostic must preserve malformed artifacts.
        return ArtifactLoad(family=family, path=path, valid=False, error=str(exc))

    return ArtifactLoad(
        family=family,
        path=path,
        valid=True,
        title=str(tiddler.get("title", "")),
        text=str(tiddler.get("text", "")),
        type=str(tiddler.get("type", "")),
        tags=str(tiddler.get("tags", "")),
    )


def discover_sessions(sessions_dir: Path = DEFAULT_SESSIONS_DIR) -> list[SessionRecord]:
    records: dict[tuple[str, int, str], SessionRecord] = {}
    for family, relative_root in REQUIRED_SESSION_FAMILIES.items():
        root = sessions_dir.joinpath(*relative_root)
        if not root.is_dir():
            continue
        for path in sorted(root.glob("*.md.json")):
            parsed = parse_session_filename(path.name)
            if parsed is None:
                continue
            identity, slug = parsed
            key = (identity.milestone, identity.number, identity.suffix)
            records.setdefault(key, SessionRecord(identity=identity, slug=slug))
            records[key].artifacts[family] = load_tiddler(path, family)
    return sorted(records.values(), key=lambda record: record.identity.sort_key)


def discover_canon_session_records(
    start: int,
    end: int,
    canon_dir: Path = DEFAULT_CANON_DIR,
) -> tuple[list[SessionRecord], list[CanonEvidence]]:
    records: dict[tuple[str, int, str], SessionRecord] = {}
    evidence: list[CanonEvidence] = []
    for shard in sorted(canon_dir.glob("tiddlers_*.jsonl")):
        for line_number, line in enumerate(shard.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            tags = set()
            for field_name in ("tags", "source_tags", "normalized_tags"):
                tags.update(parse_tw_tags(payload.get(field_name)))
            session_tag = next((tag for tag in tags if SESSION_TAG_RE.match(tag)), None)
            if not session_tag:
                continue
            session_match = SESSION_TAG_RE.match(session_tag)
            if session_match is None:
                continue
            milestone, raw_number, suffix = session_match.groups()
            number = int(raw_number)
            if number < start or number > end:
                continue
            family = next(
                (CANON_ARTIFACT_TAG_TO_FAMILY[tag] for tag in tags if tag in CANON_ARTIFACT_TAG_TO_FAMILY),
                None,
            )
            if family is None:
                continue
            identity = SessionIdentity(milestone=milestone, number=number, suffix=suffix)
            title = str(payload.get("title", ""))
            slug = _slug_from_title_or_session(title, session_tag)
            key = (identity.milestone, identity.number, identity.suffix)
            records.setdefault(key, SessionRecord(identity=identity, slug=slug))
            if family not in records[key].artifacts:
                records[key].artifacts[family] = ArtifactLoad(
                    family=family,
                    path=shard,
                    valid=True,
                    title=title,
                    text=str(payload.get("text", "")),
                    type=str(payload.get("mime_type") or payload.get("source_type") or "text/markdown"),
                    tags=" ".join(sorted(tags)),
                )
            evidence.append(
                CanonEvidence(
                    session_id=identity.session_id,
                    display=identity.display,
                    family=family,
                    title=title,
                    shard=shard,
                    line_number=line_number,
                )
            )
    return sorted(records.values(), key=lambda record: record.identity.sort_key), evidence


def _slug_from_title_or_session(title: str, session_tag: str) -> str:
    if "=" in title:
        return title.rsplit("=", 1)[-1].strip()
    return session_tag.removeprefix("session:")


def select_latest_sessions(records: Iterable[SessionRecord], count: int = 10) -> list[SessionRecord]:
    ordered = sorted(records, key=lambda record: record.identity.sort_key)
    return ordered[-count:]


def select_session_range(
    records: Iterable[SessionRecord],
    milestone: str,
    start: int,
    end: int,
) -> list[SessionRecord]:
    if start > end:
        raise ValueError("start session must be less than or equal to end session")
    indexed: dict[tuple[str, int], SessionRecord] = {
        (record.identity.milestone, record.identity.number): record
        for record in records
        if record.identity.suffix == ""
    }
    selected: list[SessionRecord] = []
    for number in range(start, end + 1):
        record = indexed.get((milestone, number))
        if record is None:
            record = SessionRecord(
                identity=SessionIdentity(milestone=milestone, number=number),
                slug="sin-artefactos-locales",
            )
        selected.append(record)
    return selected


def records_for_analysis(local_records: list[SessionRecord], canon_records: list[SessionRecord]) -> list[SessionRecord]:
    canon_by_number = {record.identity.number: record for record in canon_records}
    merged: list[SessionRecord] = []
    for record in local_records:
        if record.artifacts:
            merged.append(record)
        else:
            merged.append(canon_by_number.get(record.identity.number, record))
    return merged


def format_range_slug(start: int, end: int) -> str:
    return f"s{start:03d}-s{end:03d}"


def microcycle_filename(milestone: str, start: int, end: int) -> str:
    return f"{milestone}-micro-ciclo-{format_range_slug(start, end)}-diagnostico.md.json"


def mesocycle_filename(milestone: str, start: int, end: int) -> str:
    return f"{milestone}-meso-ciclo-{format_range_slug(start, end)}-diagnostico.md.json"


def microcycle_title(start: int, end: int) -> str:
    return f"#### 🌀 Diagnóstico de microciclo = sesiones S{start}-S{end}"


def mesocycle_title(start: int, end: int) -> str:
    return f"#### 🌀 Diagnóstico de mesociclo = microciclos S{start}-S{end}"


def parse_tw_tags(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if not isinstance(value, str):
        return []
    tags: list[str] = []
    index = 0
    while index < len(value):
        if value.startswith("[[", index):
            end = value.find("]]", index + 2)
            if end == -1:
                break
            tags.append(value[index + 2 : end])
            index = end + 2
            continue
        if value[index].isspace():
            index += 1
            continue
        end = index
        while end < len(value) and not value[end].isspace():
            end += 1
        tags.append(value[index:end])
        index = end
    return [tag for tag in tags if tag]


def load_existing_tags(
    canon_dir: Path = REPO_ROOT / "data" / "out" / "local",
    fixture_path: Path = REPO_ROOT / "tests" / "fixtures" / "canon_policy_bundle.json",
) -> set[str]:
    tags: set[str] = set()
    for shard in sorted(canon_dir.glob("tiddlers_*.jsonl")):
        for line in shard.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            for field_name in ("tags", "source_tags", "normalized_tags"):
                for tag in parse_tw_tags(payload.get(field_name)):
                    tags.add(tag)

    if fixture_path.is_file():
        try:
            fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            fixture = {}
        for section in ("tag_role_mappings", "source_role_mappings"):
            mapping = fixture.get("role_primary_contract", {}).get(section, {})
            if isinstance(mapping, dict):
                tags.update(str(key) for key in mapping)
    return tags


def _session_tag_from_origin(session_origin: str | None) -> str | None:
    if not session_origin:
        return None
    parsed = parse_session_filename(f"{session_origin}.md.json")
    if parsed is not None:
        identity, _slug = parsed
        return f"session:{identity.session_id}"
    simple = re.match(r"^(m\d+)-s(\d+)", session_origin)
    if simple:
        return f"session:{simple.group(1)}-s{int(simple.group(2))}"
    return f"session:{session_origin}"


def build_cycle_tags(
    milestone: str,
    cycle_type: str,
    start: int,
    end: int,
    existing_tags: set[str] | None = None,
    session_origin: str | None = None,
    source_microcycles: bool = False,
    diagnostic_provenance: bool = False,
    remote_read_root: bool = False,
) -> TagPlan:
    tags: list[str] = []
    new_justifications: dict[str, str] = {}

    def add(tag: str, justification: str | None = None) -> None:
        if tag in tags:
            return
        tags.append(tag)
        if existing_tags is not None and tag not in existing_tags and justification:
            new_justifications[tag] = justification

    origin_tag = _session_tag_from_origin(session_origin)
    if origin_tag:
        add(origin_tag, "instancia nueva del patrón canónico session:mXX-sNN para trazar la sesión que produjo el diagnóstico")
    add(f"milestone:{milestone}", "instancia de milestone requerida por el rango analizado")

    for tag in PREFERRED_EXISTING_TAGS:
        if existing_tags is None or tag in existing_tags:
            add(tag)

    add(
        f"diagnostic:{cycle_type}",
        f"no existe un tag canónico específico para diagnóstico de {cycle_type}; evita reutilizar tags de sesión simple",
    )
    add(
        f"range:{format_range_slug(start, end)}",
        "el rango operativo del ciclo necesita búsqueda directa sin crear una familia extensa de tags",
    )
    if source_microcycles:
        add(
            "source:micro-ciclos",
            "el mesociclo consume microciclos como fuente primaria, no sesiones crudas",
        )
    if diagnostic_provenance:
        add(
            "governance:diagnostic-provenance",
            "S97 formaliza la jerarquía de fuentes diagnósticas entre microdiagnósticos, sessions, canon, repositorio y remoto",
        )
    if remote_read_root:
        add(
            "agent:remote-read-root",
            "el contrato remoto debe recordar que el agente lee `data/out/local/` y escribe candidatos bajo sessions, no canon directo",
        )

    existing_used = [tag for tag in tags if existing_tags is None or tag in existing_tags]
    return TagPlan(tags=tags, existing_tags_used=existing_used, new_tag_justifications=new_justifications)


def format_tw_tag(tag: str) -> str:
    raw = tag.strip()
    if raw.startswith("[[") and raw.endswith("]]"):
        return raw
    return f"[[{raw}]]"


def format_tw_tags(tags: Iterable[str]) -> str:
    return " ".join(format_tw_tag(tag) for tag in tags if tag.strip())


def discover_thematic_diagnostics(sessions_dir: Path = DEFAULT_SESSIONS_DIR) -> list[Path]:
    paths: list[Path] = []
    for relative_root in THEMATIC_DIAG_FAMILIES:
        root = sessions_dir.joinpath(*relative_root)
        if root.is_dir():
            paths.extend(sorted(root.glob("*.md.json")))
    return sorted(paths)


def _lines_from_section(text: str, headings: tuple[str, ...], limit: int = 4) -> list[str]:
    lines = text.splitlines()
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped.startswith("##"):
            continue
        if not any(heading.lower() in stripped.lower() for heading in headings):
            continue
        body: list[str] = []
        for body_line in lines[index + 1 :]:
            if body_line.startswith("## "):
                break
            clean = body_line.strip()
            if not clean or clean.startswith("|---"):
                continue
            if clean.startswith("###") or clean.startswith("```"):
                continue
            if clean.startswith("|"):
                cells = [cell.strip() for cell in clean.strip("|").split("|")]
                clean = " — ".join(cell for cell in cells if cell)
            if clean.startswith(("- ", "* ")):
                clean = clean[2:].strip()
            body.append(clean)
            if len(body) >= limit:
                return body
        if body:
            return body[:limit]
    return []


def _snippet(text: str, limit: int = 180) -> str:
    compact = " ".join(line.strip() for line in text.splitlines() if line.strip())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3].rstrip() + "..."


def _collect_section_bullets(
    records: Iterable[SessionRecord],
    family: str,
    headings: tuple[str, ...],
    limit_per_session: int = 2,
    total_limit: int = 12,
) -> list[str]:
    bullets: list[str] = []
    for record in records:
        artifact = record.artifacts.get(family)
        if not artifact or not artifact.valid:
            continue
        items = _lines_from_section(artifact.text, headings, limit=limit_per_session)
        if not items:
            items = _lines_from_keyed_list(artifact.text, headings, limit=limit_per_session)
        for item in items:
            bullets.append(f"{record.display}: {item}")
            if len(bullets) >= total_limit:
                return bullets
    return bullets


def _lines_from_keyed_list(text: str, keys: tuple[str, ...], limit: int = 4) -> list[str]:
    normalized_keys = {_normalize_label(key) for key in keys}
    lines = text.splitlines()
    for index, line in enumerate(lines):
        clean = line.strip()
        label = clean[2:].strip() if clean.startswith("- ") else clean
        if not label.endswith(":"):
            continue
        if _normalize_label(label[:-1]) not in normalized_keys:
            continue
        body: list[str] = []
        for body_line in lines[index + 1 :]:
            stripped = body_line.strip()
            if not stripped:
                continue
            if stripped.startswith("## "):
                break
            if stripped.startswith("- ") and stripped.endswith(":"):
                break
            if stripped.startswith("- "):
                body.append(stripped[2:].strip())
            elif body_line.startswith(("  ", "\t")):
                body.append(stripped)
            if len(body) >= limit:
                return body
        return body[:limit]
    return []


def _normalize_label(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def _keyword_hits(records: Iterable[SessionRecord], keywords: tuple[str, ...], total_limit: int = 10) -> list[str]:
    hits: list[str] = []
    for record in records:
        for artifact in record.artifacts.values():
            if not artifact.valid:
                continue
            for line in artifact.text.splitlines():
                clean = line.strip()
                if not clean or clean.startswith("```"):
                    continue
                if any(_line_has_keyword(clean, keyword) for keyword in keywords):
                    hits.append(f"{record.display}: {_snippet(clean)}")
                    break
            if hits and hits[-1].startswith(f"{record.display}:"):
                break
        if len(hits) >= total_limit:
            break
    return hits


def _line_has_keyword(line: str, keyword: str) -> bool:
    if len(keyword) <= 3 and keyword.isalnum():
        return re.search(rf"(?<![A-Za-z0-9_]){re.escape(keyword)}(?![A-Za-z0-9_])", line, re.IGNORECASE) is not None
    return keyword.lower() in line.lower()


def _session_list(records: Iterable[SessionRecord]) -> list[str]:
    lines: list[str] = []
    for record in records:
        status = "completa" if record.is_complete else "incompleta"
        lines.append(
            f"- {record.display} ({record.session_id}): {record.slug} "
            f"({record.valid_family_count}/{len(REQUIRED_SESSION_FAMILIES)} artefactos válidos, {status})"
        )
    return lines


def _missing_or_incomplete_lines(records: Iterable[SessionRecord]) -> list[str]:
    lines: list[str] = []
    for record in records:
        if not record.artifacts:
            lines.append(f"- {record.display}: sin artefactos locales bajo `data/out/local/sessions/`")
            continue
        missing = record.missing_families()
        invalid = record.invalid_artifacts()
        if not missing and not invalid:
            continue
        details: list[str] = []
        if missing:
            details.append("faltan " + ", ".join(missing))
        if invalid:
            details.extend(
                f"{artifact.family} inválido ({artifact.path.name}: {artifact.error})"
                for artifact in invalid
            )
        lines.append(f"- {record.display}: " + "; ".join(details))
    return lines or ["- ninguna"]


def _artifact_inventory_lines(records: Iterable[SessionRecord]) -> list[str]:
    lines: list[str] = []
    for record in records:
        if not record.artifacts:
            lines.append(f"- {record.display}: ninguno")
            continue
        parts: list[str] = []
        for family in REQUIRED_SESSION_FAMILIES:
            artifact = record.artifacts.get(family)
            if artifact is None:
                parts.append(f"{family}=faltante")
                continue
            status = "válido" if artifact.valid else "inválido"
            parts.append(f"{family}={as_display_path(artifact.path)} ({status})")
        lines.append(f"- {record.display}: " + "; ".join(parts))
    return lines


def _canon_evidence_lines(canon_evidence: list[CanonEvidence]) -> list[str]:
    if not canon_evidence:
        return ["- ninguna"]
    grouped: dict[str, list[CanonEvidence]] = {}
    for item in canon_evidence:
        grouped.setdefault(item.display, []).append(item)
    lines: list[str] = []
    for display in sorted(grouped, key=lambda item: int(item[1:])):
        items = grouped[display]
        families = sorted({item.family for item in items})
        locations = sorted({f"{as_display_path(item.shard)}:{item.line_number}" for item in items})
        lines.append(
            f"- {display}: {len(items)} artefactos canónicos ({', '.join(families)}); "
            f"evidencia en {', '.join(locations[:4])}"
            + (" ..." if len(locations) > 4 else "")
        )
    return lines


def _repo_evidence_lines(paths: list[str]) -> list[str]:
    return [f"- {path}" for path in paths] if paths else ["- ninguna"]


def _legacy_route_lines(records: Iterable[SessionRecord], sessions_dir: Path) -> list[str]:
    lines: list[str] = []
    diagnoses_root = sessions_dir / "06_diagnoses"
    for legacy_name in (*PROHIBITED_CYCLE_ROUTE_NAMES, *LEGACY_CYCLE_ROUTE_NAMES):
        legacy_dir = diagnoses_root / legacy_name
        if legacy_dir.exists():
            lines.append(f"- Ruta legacy/deriva detectada: `{as_display_path(legacy_dir)}`. No se movió ni borró.")
    for record in records:
        for artifact in record.artifacts.values():
            if not artifact.valid:
                continue
            if "data/out/sessions" in artifact.text or "data/sessions" in artifact.text:
                lines.append(
                    f"- {record.display}: referencia histórica a rutas no activas en `{as_display_path(artifact.path)}`."
                )
                break
    return lines or ["- No se detectaron carpetas activas `microciclo/` ni `mesociclo/` sin guion."]


def _fallback_or_none(items: list[str], fallback: str) -> list[str]:
    return items if items else [f"- {fallback}"]


def _bulletize(items: list[str]) -> str:
    if not items:
        return "- ninguno"
    return "\n".join(item if item.startswith("- ") else f"- {item}" for item in items)


def _build_prognosis(records: list[SessionRecord], mesocycle_status: MesocycleStatus | None) -> str:
    incomplete = [line for line in _missing_or_incomplete_lines(records) if line != "- ninguna"]
    if mesocycle_status and mesocycle_status.can_produce:
        next_topic = "Abrir diagnóstico de mesociclo S65-S94"
        next_type = "necesidad real"
        next_justification = "Ya existen tres microciclos continuos y el mesociclo debe consumir esos diagnósticos, no 30 sesiones crudas."
        next_evidence = "Microciclos disponibles y continuos: " + ", ".join(ref.display for ref in mesocycle_status.available[-3:])
        next_risk = "El sistema seguirá usando contexto de microciclo de forma manual y perderá la oportunidad de sintetizar decisiones persistentes entre ciclos."
    elif incomplete:
        next_topic = "Reparar artefactos `.md.json` inválidos o incompletos del ciclo"
        next_type = "necesidad real"
        next_justification = "Un diagnóstico cíclico pierde autoridad si el staging de sesiones no puede parsearse de forma completa."
        next_evidence = "; ".join(line[2:] for line in incomplete[:2])
        next_risk = "La admisión futura al canon o el reverse podrían rechazar candidatos por errores de serialización ya visibles."
    else:
        next_topic = "Generar los microciclos faltantes previos al mesociclo"
        next_type = "mejora conveniente"
        next_justification = "El microciclo actual ya existe, pero el mesociclo requiere tres microciclos continuos."
        next_evidence = "No hay sesiones incompletas en el rango seleccionado."
        next_risk = "El sistema seguirá dependiendo de lectura cruda para contexto histórico de mayor escala."

    missing = mesocycle_status.missing_ranges if mesocycle_status else []
    if missing:
        missing_text = ", ".join(f"S{start}-S{end}" for start, end in missing)
    else:
        missing_text = "sin faltantes detectados"

    return "\n".join(
        [
            "## Pronóstico operativo",
            "",
            "### Próxima sesión recomendada",
            f"- Tema: {next_topic}",
            f"- Tipo: {next_type}",
            f"- Justificación: {next_justification}",
            f"- Evidencia desde el microciclo: {next_evidence}",
            f"- Riesgo si se ignora: {next_risk}",
            "",
            "### Segunda sesión probable",
            "- Tema: Recuperar o documentar explícitamente la ausencia de staging local para S65-S74",
            "- Tipo: mejora conveniente",
            "- Justificación: El microciclo puede apoyarse en canon admitido, pero la ausencia de `.md.json` locales limita auditorías reversibles desde staging.",
            f"- Evidencia desde el microciclo: Microciclos faltantes o no continuos: {missing_text}; sesiones locales incompletas: {len(incomplete)}.",
            "- Riesgo si se ignora: Futuras auditorías podrían confundir ausencia de staging local con ausencia histórica de sesión.",
            "",
            "### Tercera sesión posible",
            "- Tema: Retomar frentes de integración solo después de cerrar la trazabilidad local del rango",
            "- Tipo: tentación prematura",
            "- Justificación: Un microciclo con sesiones ausentes o incompletas debe estabilizar su evidencia local antes de abrir frentes laterales.",
            "- Evidencia desde el microciclo: El inventario local del rango determina qué sesiones tienen artefactos y cuáles no.",
            "- Riesgo si se ignora: Se confunde avance operativo con acumulación de deuda documental no diagnosticada.",
        ]
    )


def build_microcycle_markdown(
    records: list[SessionRecord],
    thematic_diagnostics: list[Path],
    tag_plan: TagPlan,
    sessions_dir: Path = DEFAULT_SESSIONS_DIR,
    mesocycle_status: MesocycleStatus | None = None,
    include_mesocycle_status: bool = True,
    canon_records: list[SessionRecord] | None = None,
    canon_evidence: list[CanonEvidence] | None = None,
    repository_evidence: list[str] | None = None,
    session_kind: str = "infraestructura-diagnostica",
) -> str:
    if not records:
        raise ValueError("microcycle requires at least one session")
    canon_records = canon_records or []
    canon_evidence = canon_evidence or []
    repository_evidence = repository_evidence or []
    analysis_records = records_for_analysis(records, canon_records)
    start = records[0].identity.number
    end = records[-1].identity.number
    session_range = f"S{start}-S{end}"
    partial_warning = ""
    if len(records) < 10:
        partial_warning = "\n\nAdvertencia: diagnóstico parcial; hay menos de 10 sesiones disponibles."

    thematic_lines = (
        [f"- {as_display_path(path)}" for path in thematic_diagnostics]
        if thematic_diagnostics
        else ["- ninguno"]
    )
    decisions = _collect_section_bullets(analysis_records, "balance", ("Decisiones a conservar", "decisiones_a_conservar", "Objetivos cumplidos", "Producido"))
    confirmed = _collect_section_bullets(analysis_records, "hipotesis", ("Hipótesis confirmadas", "CONFIRMADA", "confirmadas"))
    open_hypotheses = _collect_section_bullets(analysis_records, "hipotesis", ("Hipótesis abiertas", "pendiente", "abiertas"))
    closed_debt = _collect_section_bullets(analysis_records, "balance", ("Deuda técnica cerrada", "Criterios de cierre", "Confirmado", "aciertos"))
    persistent_debt = _collect_section_bullets(analysis_records, "balance", ("Deuda técnica persistente", "riesgos_detectados", "errores", "Riesgos detectados"))
    new_debt = _collect_section_bullets(analysis_records, "balance", ("Deuda técnica nueva", "Deuda técnica introducida", "Deuda técnica identificada", "Riesgos detectados"))
    route_hits = _keyword_hits(analysis_records, ("data/out/local/sessions", "data/sessions", "data/out/sessions", "AGENT_SESSION_ROOT"))
    canon_hits = _keyword_hits(analysis_records, ("canon", "reverse", "strict", "reverse-preflight", "admisión"))
    ci_hits = _keyword_hits(analysis_records, ("CI", "GitHub Actions", "CodeQL", "workflow"))
    security_hits = _keyword_hits(analysis_records, ("secret", "secrets", "CodeQL", ".env", "token", "credentials"))
    agent_hits = _keyword_hits(analysis_records, ("MCP", "remote", "OneDrive", "agente", "mirror"))
    legacy_lines = _legacy_route_lines(analysis_records, sessions_dir)

    mesocycle_lines: list[str] = []
    if mesocycle_status and not mesocycle_status.can_produce:
        mesocycle_lines = [
            "- Mesociclo no producido todavía.",
            f"- Razón: {mesocycle_status.reason}",
            "- Microciclos requeridos:",
        ]
        if mesocycle_status.missing_ranges:
            mesocycle_lines.extend(f"  - S{start_missing}-S{end_missing}" for start_missing, end_missing in mesocycle_status.missing_ranges)
        else:
            mesocycle_lines.append("  - tres diagnósticos continuos de microciclo")
        mesocycle_lines.append("- Microciclos disponibles:")
        if mesocycle_status.available:
            mesocycle_lines.extend(f"  - {item.display}: {as_display_path(item.path)}" for item in mesocycle_status.available)
        else:
            mesocycle_lines.append("  - ninguno")

    tag_lines = [f"- {tag}" for tag in tag_plan.tags]
    new_tag_lines = (
        [f"- {tag}: {reason}" for tag, reason in tag_plan.new_tag_justifications.items()]
        if tag_plan.new_tag_justifications
        else ["- ninguno"]
    )

    sections = [
        f"# Diagnóstico de microciclo {session_range}",
        "",
        "## Tipo de sesión diagnóstica",
        f"{session_kind}: {SESSION_KIND_POLICIES.get(session_kind, 'clasificación no registrada')}.",
        "",
        "## Rango de sesiones analizadas",
        f"{session_range}.{partial_warning}",
        "",
        "## Lista de sesiones incluidas",
        "\n".join(_session_list(analysis_records)),
        "",
        "## Sesiones ausentes o incompletas",
        "\n".join(_missing_or_incomplete_lines(records)),
        "",
        "## Artefactos leídos por sesión",
        "\n".join(_artifact_inventory_lines(analysis_records)),
        "",
        "## Diagnósticos temáticos consultados",
        "\n".join(thematic_lines),
        "",
        "## Evidencia consultada desde canon",
        "\n".join(_canon_evidence_lines(canon_evidence)),
        "",
        "## Evidencia consultada desde repositorio",
        "\n".join(_repo_evidence_lines(repository_evidence)),
        "",
        "## Decisiones estabilizadas",
        _bulletize(_fallback_or_none(decisions, "sin decisiones estabilizadas extraídas automáticamente")),
        "",
        "## Hipótesis confirmadas",
        _bulletize(_fallback_or_none(confirmed, "sin hipótesis confirmadas extraídas automáticamente")),
        "",
        "## Hipótesis abiertas",
        _bulletize(_fallback_or_none(open_hypotheses, "sin hipótesis abiertas extraídas automáticamente")),
        "",
        "## Deuda técnica cerrada",
        _bulletize(_fallback_or_none(closed_debt, "sin deuda cerrada extraída automáticamente")),
        "",
        "## Deuda técnica persistente",
        _bulletize(_fallback_or_none(persistent_debt, "sin deuda persistente extraída automáticamente")),
        "",
        "## Deuda técnica nueva",
        _bulletize(_fallback_or_none(new_debt, "sin deuda nueva extraída automáticamente")),
        "",
        "## Cambios en gobernanza de rutas",
        _bulletize(route_hits + legacy_lines),
        "",
        "## Cambios en canon/reverse",
        _bulletize(_fallback_or_none(canon_hits, "sin señales canon/reverse extraídas automáticamente")),
        "",
        "## Cambios en CI/CD",
        _bulletize(_fallback_or_none(ci_hits, "sin señales CI/CD extraídas automáticamente")),
        "",
        "## Cambios en seguridad",
        _bulletize(_fallback_or_none(security_hits, "sin señales de seguridad extraídas automáticamente")),
        "",
        "## Impacto sobre agentes locales/remotos",
        _bulletize(_fallback_or_none(agent_hits, "sin señales sobre agentes locales/remotos extraídas automáticamente")),
        "",
        "## Patrones repetidos",
        "\n".join(
            [
                "- Local-first: el ciclo vuelve una y otra vez a `data/out/local/` como raíz operativa.",
                "- Staging antes de canon: las sesiones estabilizan evidencia local y posponen admisión canónica directa.",
                "- Endurecimiento incremental: las sesiones alternan entre UX operativa, seguridad, rutas y CI.",
                "- Tests como cierre real: cada estabilización intenta quedar respaldada por pruebas locales o de CI.",
            ]
        ),
        "",
        "## Riesgos actuales",
        "\n".join(
            [
                *_missing_or_incomplete_lines(records),
                "- El mesociclo no debe producirse hasta contar con tres microciclos continuos.",
                "- El trabajo remoto/MCP puede mezclar secretos, red y CI si se retoma antes de cerrar deudas locales.",
            ]
        ),
        "",
        "## Señales de madurez",
        "\n".join(
            [
                "- La raíz `data/out/local/sessions/` aparece como decisión operativa estabilizada.",
                "- El canon local queda protegido contra escritura directa por defecto.",
                "- Los fallos de CI se diagnostican con cadena causal y tests de regresión.",
                "- Las decisiones de seguridad sobre secrets se convierten en guardias y tests.",
            ]
        ),
        "",
        "## Señales de deriva",
        "\n".join(legacy_lines),
        "",
        _build_prognosis(records, mesocycle_status),
        "",
        "## Tags usados y justificación de tags nuevos",
        "Tags usados:",
        "\n".join(tag_lines),
        "",
        "Tags nuevos o instancias nuevas justificadas:",
        "\n".join(new_tag_lines),
    ]
    if include_mesocycle_status and mesocycle_lines:
        sections.extend(["", "## Estado de mesociclo", "\n".join(mesocycle_lines)])
    return "\n".join(sections).rstrip() + "\n"


def build_microcycle_tiddler(
    records: list[SessionRecord],
    tag_plan: TagPlan,
    thematic_diagnostics: list[Path],
    sessions_dir: Path = DEFAULT_SESSIONS_DIR,
    session_origin: str | None = None,
    mesocycle_status: MesocycleStatus | None = None,
    timestamp: str | None = None,
    include_mesocycle_status: bool = True,
    canon_records: list[SessionRecord] | None = None,
    canon_evidence: list[CanonEvidence] | None = None,
    repository_evidence: list[str] | None = None,
    session_kind: str = "infraestructura-diagnostica",
) -> dict[str, Any]:
    if not records:
        raise ValueError("cannot build microcycle tiddler without sessions")
    start = records[0].identity.number
    end = records[-1].identity.number
    created = timestamp or stamp_now()
    title = microcycle_title(start, end)
    text = build_microcycle_markdown(
        records,
        thematic_diagnostics,
        tag_plan,
        sessions_dir,
        mesocycle_status,
        include_mesocycle_status=include_mesocycle_status,
        canon_records=canon_records,
        canon_evidence=canon_evidence,
        repository_evidence=repository_evidence,
        session_kind=session_kind,
    )
    source_path = MICRO_DIAG_DIR / microcycle_filename(records[-1].identity.milestone, start, end)
    tiddler: dict[str, Any] = {
        "created": created,
        "modified": created,
        "title": title,
        "text": text,
        "tags": format_tw_tags(tag_plan.tags),
        "type": "text/vnd.tiddlywiki",
        "source_path": as_display_path(source_path),
    }
    if session_origin:
        tiddler["session_origin"] = session_origin
    return tiddler


def write_tiddler(path: Path, tiddler: dict[str, Any]) -> None:
    try:
        rel_path = path.resolve().relative_to(REPO_ROOT)
    except ValueError:
        rel_path = path.resolve()
    if any(rel_path.match(glob) for glob in CANON_WRITE_GUARD_GLOBS):
        raise ValueError("refusing to write protected canon shard")
    for root in PROHIBITED_SESSION_ROOTS:
        try:
            path.resolve().relative_to(root.resolve())
        except ValueError:
            continue
        raise ValueError(f"refusing to write under prohibited session root: {root}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([tiddler], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_microcycle_filename(path: Path) -> MicrocycleRef | None:
    match = MICRO_FILE_RE.match(path.name)
    if not match:
        return None
    return MicrocycleRef(
        milestone=path.name.split("-", 1)[0],
        start=int(match.group("start")),
        end=int(match.group("end")),
        path=path,
    )


def discover_microcycles(micro_dir: Path = MICRO_DIAG_DIR) -> list[MicrocycleRef]:
    if not micro_dir.is_dir():
        return []
    refs = [ref for path in sorted(micro_dir.glob("*.md.json")) if (ref := parse_microcycle_filename(path))]
    return sorted(refs, key=lambda item: (int(item.milestone[1:]), item.start, item.end))


def load_microdiagnostic(ref: MicrocycleRef) -> MicrodiagnosticLoad:
    artifact = load_tiddler(ref.path, "microdiagnostico")
    if not artifact.valid:
        return MicrodiagnosticLoad(
            ref=ref,
            valid_json=False,
            valid_title=False,
            valid_type=False,
            error=artifact.error,
        )
    expected_title = microcycle_title(ref.start, ref.end)
    return MicrodiagnosticLoad(
        ref=ref,
        valid_json=True,
        valid_title=artifact.title == expected_title,
        valid_type=artifact.type == "text/vnd.tiddlywiki",
        title=artifact.title,
        text=artifact.text,
        type=artifact.type,
        tags=artifact.tags,
        error="" if artifact.title == expected_title else f"title mismatch: expected {expected_title!r}",
    )


def load_microdiagnostics(refs: Iterable[MicrocycleRef]) -> list[MicrodiagnosticLoad]:
    return [load_microdiagnostic(ref) for ref in refs]


def plan_mesocycle(micro_dir: Path = MICRO_DIAG_DIR) -> MesocycleStatus:
    available = discover_microcycles(micro_dir)
    if len(available) < 3:
        missing = _missing_previous_microcycle_ranges(available)
        return MesocycleStatus(
            can_produce=False,
            available=available,
            missing_ranges=missing,
            reason="faltan microciclos suficientes",
        )

    selected = available[-3:]
    continuous = all(left.end + 1 == right.start for left, right in zip(selected, selected[1:]))
    if not continuous:
        missing_ranges: list[tuple[int, int]] = []
        for left, right in zip(selected, selected[1:]):
            if left.end + 1 < right.start:
                missing_ranges.append((left.end + 1, right.start - 1))
        return MesocycleStatus(
            can_produce=False,
            available=available,
            missing_ranges=missing_ranges,
            reason="los últimos tres microciclos no son continuos",
            selected=selected,
        )
    return MesocycleStatus(
        can_produce=True,
        available=available,
        missing_ranges=[],
        reason="tres microciclos continuos disponibles",
        selected=selected,
    )


def _section_body(text: str, heading: str) -> str:
    target = heading.strip().lower()
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line.strip().lower() != target:
            continue
        body: list[str] = []
        for body_line in lines[index + 1 :]:
            if body_line.startswith("## "):
                break
            body.append(body_line)
        return "\n".join(body).strip()
    return ""


def _clean_body_lines(body: str, limit: int) -> list[str]:
    lines: list[str] = []
    for raw in body.splitlines():
        clean = raw.strip()
        if not clean or clean.startswith(("```", "|---", "Tags usados:", "Tags nuevos")):
            continue
        if clean.startswith("###"):
            continue
        if clean.startswith(("- ", "* ")):
            clean = clean[2:].strip()
        elif clean.startswith("|"):
            cells = [cell.strip() for cell in clean.strip("|").split("|")]
            clean = " — ".join(cell for cell in cells if cell)
        if not clean or clean in {"ninguno", "ninguna"}:
            continue
        lines.append(clean)
        if len(lines) >= limit:
            break
    return lines


def _micro_section_lines(load: MicrodiagnosticLoad, headings: tuple[str, ...], limit: int = 4) -> list[str]:
    for heading in headings:
        body = _section_body(load.text, heading)
        if body:
            return _clean_body_lines(body, limit)
    return []


def _meso_collect(
    loads: list[MicrodiagnosticLoad],
    headings: tuple[str, ...],
    fallback: str,
    limit_per_micro: int = 3,
    total_limit: int = 12,
) -> list[str]:
    bullets: list[str] = []
    for load in loads:
        if not load.is_valid:
            continue
        for line in _micro_section_lines(load, headings, limit=limit_per_micro):
            bullets.append(f"- {load.ref.display}: {line} (Fuente principal: microdiagnóstico)")
            if len(bullets) >= total_limit:
                return bullets
    return bullets or [f"- {fallback} (Fuente principal: microdiagnóstico)"]


def _micro_summary_lines(load: MicrodiagnosticLoad) -> list[str]:
    decisions = _micro_section_lines(load, ("## Decisiones estabilizadas",), limit=2)
    risks = _micro_section_lines(load, ("## Riesgos actuales",), limit=2)
    maturity = _micro_section_lines(load, ("## Señales de madurez",), limit=1)
    lines = [
        f"- Fuente principal: microdiagnóstico `{as_display_path(load.ref.path)}`.",
        f"- Validez: {'válido' if load.is_valid else 'inválido'}; título observado: `{load.title}`.",
    ]
    if decisions:
        lines.append(f"- Decisiones dominantes: {'; '.join(decisions)}.")
    if risks:
        lines.append(f"- Riesgos dominantes: {'; '.join(risks)}.")
    if maturity:
        lines.append(f"- Señal de madurez: {'; '.join(maturity)}.")
    return lines


def _microdiagnostic_validity_lines(loads: list[MicrodiagnosticLoad]) -> list[str]:
    lines: list[str] = []
    for load in loads:
        checks = [
            "JSON válido" if load.valid_json else f"JSON inválido ({load.error})",
            "título exacto" if load.valid_title else f"título no exacto ({load.title})",
            "tipo reversible" if load.valid_type else f"tipo inesperado ({load.type})",
        ]
        lines.append(f"- {load.ref.display}: " + "; ".join(checks))
    return lines


def _staging_completeness_lines(loads: list[MicrodiagnosticLoad]) -> list[str]:
    lines: list[str] = []
    for load in loads:
        total_sessions = load.ref.end - load.ref.start + 1
        missing = _micro_section_lines(load, ("## Sesiones ausentes o incompletas",), limit=total_sessions)
        if not missing:
            lines.append(f"- {load.ref.display}: presente según microdiagnóstico. Fuente usada: microdiagnóstico.")
            continue
        missing_local_count = sum(1 for item in missing if "sin artefactos locales" in item)
        if missing_local_count >= total_sessions and all("sin artefactos locales" in item for item in missing):
            status = "depurado o ausente en staging local"
        else:
            status = "parcial en staging local"
        lines.append(
            f"- {load.ref.display}: {status}; señales: {'; '.join(missing[:3])}. "
            "Fuente usada: microdiagnóstico."
        )
    return lines


def _canonical_completeness_lines(start: int, end: int) -> list[str]:
    records, _evidence = discover_canon_session_records(start, end)
    by_number = {record.identity.number: record for record in records}
    lines: list[str] = []
    for number in range(start, end + 1):
        record = by_number.get(number)
        if record is None:
            status = "no encontrada"
            session = f"S{number}"
            count = "0/7"
        else:
            status = "admitida completa" if record.is_complete else "admitida parcial"
            session = f"{record.display} ({record.session_id})"
            count = f"{record.valid_family_count}/{len(REQUIRED_SESSION_FAMILIES)}"
        lines.append(f"- {session}: {status} ({count}). Fuente usada: canon.")
    return lines


def _mesocycle_prognosis() -> str:
    return "\n".join(
        [
            "## Pronóstico operativo",
            "",
            "### Próxima sesión recomendada",
            "- Tema: m04-s98-project-level-diagnostic-readiness",
            "- Tipo: diagnóstico puro",
            "- Clasificación: necesidad real",
            "- Justificación: El mesociclo ya existe y permite evaluar si hay evidencia suficiente para un diagnóstico arquitectónico global sin abrir todavía ese diagnóstico.",
            "- Evidencia desde el mesociclo: Tres microdiagnósticos continuos S65-S94 fueron consumidos como fuente principal y muestran madurez local-first, canon protegido y deuda remota delimitada.",
            "- Riesgo si se ignora: El proyecto podría saltar a diagnóstico global sin verificar antes si la procedencia y completitud sostienen esa escala.",
            "",
            "### Segunda sesión probable",
            "- Tema: m04-s98-remote-agent-dry-run-diagnostic-readiness",
            "- Tipo: sesión mixta",
            "- Clasificación: mejora conveniente",
            "- Justificación: El contrato remoto está declarado, pero conviene probar lectura remota en dry-run antes de permitir cualquier espejo operativo.",
            "- Evidencia desde el mesociclo: S85-S94 acumuló decisiones sobre OneDrive, secrets, CodeQL y raíz `data/out/local/`; S97 conserva `SYNC_DRY_RUN=true` como contención.",
            "- Riesgo si se ignora: Un mirror con `REMOTE_DELETE_EXTRANEOUS=true` puede amplificar errores de ruta si se activa antes de validar paridad y permisos.",
            "",
            "### Tercera sesión posible",
            "- Tema: diagnóstico arquitectónico global del proyecto completo",
            "- Tipo: diagnóstico puro",
            "- Clasificación: tentación prematura",
            "- Justificación: La cadena microciclos → mesociclo ya quedó preparada, pero falta una sesión de readiness que confirme alcance, fuentes y criterios de corte.",
            "- Evidencia desde el mesociclo: Hay memoria cíclica consolidada, pero todavía aparecen staging depurado, S90 incompleto y superficie remota no ejercitada en dry-run real.",
            "- Riesgo si se ignora: El diagnóstico global mezclaría evidencia madura con deuda local no clasificada y produciría conclusiones demasiado amplias.",
        ]
    )


def build_mesocycle_markdown(refs: list[MicrocycleRef], thematic_diagnostics: list[Path], tag_plan: TagPlan) -> str:
    if len(refs) != 3:
        raise ValueError("mesocycle requires exactly 3 microcycle diagnostics")
    loads = load_microdiagnostics(refs)
    invalid = [load for load in loads if not load.is_valid]
    if invalid:
        details = "; ".join(f"{load.ref.display}: {load.error or load.title}" for load in invalid)
        raise ValueError(f"invalid microcycle diagnostics: {details}")
    start = refs[0].start
    end = refs[-1].end
    thematic_lines = (
        [f"- {as_display_path(path)}" for path in thematic_diagnostics]
        if thematic_diagnostics
        else ["- ninguno"]
    )
    consumed_lines = [f"- {ref.display}: {as_display_path(ref.path)}" for ref in refs]
    workflow_path = REPO_ROOT / ".github" / "workflows" / "remote_mirror_out_local.yml"
    auxiliary_lines = [
        "- microdiagnóstico: los tres archivos de `micro-ciclo/` son la fuente principal.",
        "- sessions: `data/out/local/sessions/` se usa para ubicar diagnósticos y staging, no para releer 30 sesiones crudas.",
        "- canon: `data/out/local/tiddlers_*.jsonl` se usa para tags y completitud canónica.",
        "- auditoría: `data/out/local/audit/` queda disponible como apoyo; no se leyó ningún reporte concreto porque no hubo hipótesis de auditoría que validar.",
        "- repositorio: instrucciones, script diagnóstico, tests y workflow remoto.",
    ]
    if workflow_path.is_file():
        auxiliary_lines.append(f"- remoto dry-run: inspección estática de `{as_display_path(workflow_path)}`; no se ejecutó sincronización.")
    tag_lines = [f"- {tag}" for tag in tag_plan.tags]
    new_tag_lines = (
        [f"- {tag}: {reason}" for tag, reason in tag_plan.new_tag_justifications.items()]
        if tag_plan.new_tag_justifications
        else ["- ninguno"]
    )
    return "\n".join(
        [
            f"# Diagnóstico de mesociclo S{start}-S{end}",
            "",
            "## Rango de microciclos analizados",
            f"S{start}-S{end}.",
            "",
            "## Microciclos incluidos",
            "\n".join(f"- {load.ref.display}" for load in loads),
            "",
            "## Archivos de microdiagnóstico leídos",
            "\n".join(consumed_lines),
            "",
            "## Validez de cada microdiagnóstico",
            "\n".join(_microdiagnostic_validity_lines(loads)),
            "",
            "## Fuentes auxiliares consultadas",
            "\n".join(auxiliary_lines),
            "",
            "## Diagnósticos temáticos consultados",
            "\n".join(thematic_lines),
            "",
            "## Gobernanza de procedencia aplicada",
            "\n".join(
                [
                    "- Nivel 1: microdiagnósticos previos específicos como fuente principal del mesociclo.",
                    "- Nivel 2: `data/out/local/sessions/` como staging local y raíz oficial de sesiones.",
                    "- Nivel 3: canon local para completitud durable cuando `sessions/` fue depurado.",
                    "- Nivel 4: auditorías y derivados solo como apoyo para hipótesis concretas.",
                    "- Nivel 5: repositorio para validar scripts, tests, instrucciones y workflow actual.",
                    "- Nivel 6: remoto/OneDrive como paridad operativa, no autoridad superior al canon local.",
                ]
            ),
            "",
            "## Completitud en staging local",
            "\n".join(_staging_completeness_lines(loads)),
            "",
            "## Completitud canónica",
            "\n".join(_canonical_completeness_lines(start, end)),
            "",
            f"## Síntesis de S{refs[0].start}-S{refs[0].end}",
            "\n".join(_micro_summary_lines(loads[0])),
            "",
            f"## Síntesis de S{refs[1].start}-S{refs[1].end}",
            "\n".join(_micro_summary_lines(loads[1])),
            "",
            f"## Síntesis de S{refs[2].start}-S{refs[2].end}",
            "\n".join(_micro_summary_lines(loads[2])),
            "",
            "## Continuidad entre microciclos",
            "\n".join(
                [
                    "- La continuidad principal es local-first: primero canon/admisión/reverse, luego rutas, después remoto/CI. Fuente principal: microdiagnóstico.",
                    "- Los tres ciclos sostienen la separación entre staging, canon local y derivados. Fuente principal: microdiagnóstico.",
                    "- La producción diagnóstica escala de sesiones a microciclos y ahora a mesociclo sin releer 30 sesiones crudas. Fuente principal: microdiagnóstico.",
                ]
            ),
            "",
            "## Cambios de dirección entre microciclos",
            "\n".join(
                [
                    "- S65-S74 estabiliza admisión canónica, reverse y primeras compuertas locales. Fuente principal: microdiagnóstico.",
                    "- S75-S84 gira hacia vocabulario de roles, relaciones, rutas y propagación downstream. Fuente principal: microdiagnóstico.",
                    "- S85-S94 desplaza el foco hacia MCP, `.env`, CI/CodeQL, remoto OneDrive y gobernanza de rutas de sesión. Fuente principal: microdiagnóstico.",
                ]
            ),
            "",
            "## Decisiones estabilizadas",
            "\n".join(
                _meso_collect(
                    loads,
                    ("## Decisiones estabilizadas", "## Cambios en gobernanza de rutas", "## Cambios en canon/reverse"),
                    "sin decisiones estabilizadas extraídas",
                    limit_per_micro=4,
                    total_limit=14,
                )
            ),
            "",
            "## Hipótesis confirmadas",
            "\n".join(_meso_collect(loads, ("## Hipótesis confirmadas",), "sin hipótesis confirmadas extraídas")),
            "",
            "## Hipótesis abiertas",
            "\n".join(_meso_collect(loads, ("## Hipótesis abiertas",), "sin hipótesis abiertas extraídas")),
            "",
            "## Deuda técnica persistente",
            "\n".join(_meso_collect(loads, ("## Deuda técnica persistente", "## Riesgos actuales"), "sin deuda persistente extraída")),
            "",
            "## Deuda técnica cerrada",
            "\n".join(_meso_collect(loads, ("## Deuda técnica cerrada",), "sin deuda cerrada extraída")),
            "",
            "## Deuda técnica nueva",
            "\n".join(_meso_collect(loads, ("## Deuda técnica nueva",), "sin deuda nueva extraída")),
            "",
            "## Riesgos acumulados",
            "\n".join(
                [
                    *_meso_collect(loads, ("## Riesgos actuales",), "sin riesgos actuales extraídos", limit_per_micro=3, total_limit=10),
                    "- Riesgo remoto: `REMOTE_DELETE_EXTRANEOUS=true` y modo mirror requieren dry-run y raíz local correcta antes de cualquier ejecución real. Fuente principal: repositorio.",
                    "- Riesgo de interpretación: `sessions/` depurado no equivale a memoria perdida si canon conserva evidencia. Fuente principal: canon.",
                ]
            ),
            "",
            "## Señales de madurez",
            "\n".join(_meso_collect(loads, ("## Señales de madurez",), "sin señales de madurez extraídas", total_limit=10)),
            "",
            "## Señales de deriva",
            "\n".join(_meso_collect(loads, ("## Señales de deriva",), "sin señales de deriva extraídas", total_limit=10)),
            "",
            "## Impacto sobre canon",
            "\n".join(
                [
                    "- El canon local queda como memoria durable y fuente de completitud cuando el staging fue depurado. Fuente principal: canon.",
                    "- La admisión sigue pasando por compuertas locales; el mesociclo no promueve líneas automáticamente. Fuente principal: repositorio.",
                ]
            ),
            "",
            "## Impacto sobre reverse",
            "\n".join(_meso_collect(loads, ("## Cambios en canon/reverse",), "sin impacto reverse extraído", total_limit=10)),
            "",
            "## Impacto sobre CI/CD",
            "\n".join(_meso_collect(loads, ("## Cambios en CI/CD",), "sin impacto CI/CD extraído", total_limit=10)),
            "",
            "## Impacto sobre seguridad",
            "\n".join(
                [
                    *_meso_collect(loads, ("## Cambios en seguridad",), "sin impacto de seguridad extraído", total_limit=6),
                    "- La revisión remota no imprime tokens ni exige `MSA_REFRESH_TOKEN`; el workflow usa secrets y `SYNC_DRY_RUN=true` por defecto. Fuente principal: repositorio.",
                ]
            ),
            "",
            "## Impacto sobre agente local",
            "\n".join(
                [
                    "- El agente local debe leer primero `data/out/local/`, producir bajo `data/out/local/sessions/` y no escribir `tiddlers_*.jsonl`. Fuente principal: repositorio.",
                    "- Los diagnósticos de ciclo ahora permiten resumir evolución sin reabrir todo el historial crudo. Fuente principal: microdiagnóstico.",
                ]
            ),
            "",
            "## Impacto sobre agente remoto",
            "\n".join(
                [
                    "- El agente remoto debe leer desde `AGENT_PRIMARY_READ_ROOT=data/out/local/`. Fuente principal: repositorio.",
                    "- Debe producir candidatos bajo `AGENT_SESSION_ROOT=data/out/local/sessions/` y respetar `AGENT_DIRECT_CANON_WRITE=false`. Fuente principal: repositorio.",
                    "- Con `SYNC_DRY_RUN=true`, cualquier mirror debe ser simulación o inspección no destructiva. Fuente principal: repositorio.",
                ]
            ),
            "",
            "## Preparación para diagnóstico global del proyecto",
            "\n".join(
                [
                    "- La cadena sesiones → microciclos → mesociclo ya tiene un primer artefacto reversible. Fuente principal: microdiagnóstico.",
                    "- Antes del diagnóstico global conviene abrir una sesión de readiness para fijar corte, fuentes y criterios de escala. Fuente principal: mesociclo.",
                ]
            ),
            "",
            _mesocycle_prognosis(),
            "",
            "## Tags usados y justificación de tags nuevos",
            "Tags usados:",
            "\n".join(tag_lines),
            "",
            "Tags nuevos o instancias nuevas justificadas:",
            "\n".join(new_tag_lines),
        ]
    ) + "\n"


def build_mesocycle_tiddler(
    refs: list[MicrocycleRef],
    tag_plan: TagPlan,
    thematic_diagnostics: list[Path],
    session_origin: str | None = None,
    timestamp: str | None = None,
) -> dict[str, Any]:
    if len(refs) != 3:
        raise ValueError("cannot build mesocycle tiddler without exactly three microcycles")
    start = refs[0].start
    end = refs[-1].end
    created = timestamp or stamp_now()
    title = mesocycle_title(start, end)
    source_path = MESO_DIAG_DIR / mesocycle_filename(refs[-1].milestone, start, end)
    tiddler: dict[str, Any] = {
        "created": created,
        "modified": created,
        "title": title,
        "text": build_mesocycle_markdown(refs, thematic_diagnostics, tag_plan),
        "tags": format_tw_tags(tag_plan.tags),
        "type": "text/vnd.tiddlywiki",
        "source_path": as_display_path(source_path),
    }
    if session_origin:
        tiddler["session_origin"] = session_origin
    return tiddler


def generate_microcycle(
    sessions_dir: Path = DEFAULT_SESSIONS_DIR,
    count: int = 10,
    include_thematic: bool = False,
    session_origin: str | None = None,
    write: bool = False,
    milestone: str = "m04",
    start_session: int | None = None,
    end_session: int | None = None,
    include_mesocycle_status: bool = True,
    include_canon_evidence: bool = True,
    repository_evidence: list[str] | None = None,
    session_kind: str = "infraestructura-diagnostica",
) -> tuple[Path, dict[str, Any], MesocycleStatus]:
    discovered = discover_sessions(sessions_dir)
    canon_records: list[SessionRecord] = []
    canon_evidence: list[CanonEvidence] = []
    if (start_session is None) != (end_session is None):
        raise ValueError("start_session and end_session must be provided together")
    if start_session is not None and end_session is not None:
        records = select_session_range(discovered, milestone=milestone, start=start_session, end=end_session)
        if include_canon_evidence:
            canon_records, canon_evidence = discover_canon_session_records(start_session, end_session)
    else:
        records = select_latest_sessions(discovered, count=count)
        if include_canon_evidence:
            canon_records, canon_evidence = discover_canon_session_records(
                records[0].identity.number,
                records[-1].identity.number,
            ) if records else ([], [])
    if not records:
        raise ValueError(f"no session artifacts found under {as_display_path(sessions_dir)}")
    start = records[0].identity.number
    end = records[-1].identity.number
    milestone = records[-1].identity.milestone
    thematic = discover_thematic_diagnostics(sessions_dir) if include_thematic else []
    existing_tags = load_existing_tags()
    tag_plan = build_cycle_tags(
        milestone=milestone,
        cycle_type="micro-ciclo",
        start=start,
        end=end,
        existing_tags=existing_tags,
        session_origin=session_origin,
    )
    path = MICRO_DIAG_DIR / microcycle_filename(milestone, start, end)
    projected_refs = discover_microcycles(MICRO_DIAG_DIR)
    current_ref = MicrocycleRef(milestone=milestone, start=start, end=end, path=path)
    if all(ref.path != current_ref.path for ref in projected_refs):
        projected_refs.append(current_ref)
    temp_dir = path.parent
    meso_status = _plan_mesocycle_from_refs(sorted(projected_refs, key=lambda item: (int(item.milestone[1:]), item.start, item.end)))
    tiddler = build_microcycle_tiddler(
        records=records,
        tag_plan=tag_plan,
        thematic_diagnostics=thematic,
        sessions_dir=sessions_dir,
        session_origin=session_origin,
        mesocycle_status=meso_status,
        include_mesocycle_status=include_mesocycle_status,
        canon_records=canon_records,
        canon_evidence=canon_evidence,
        repository_evidence=repository_evidence or [],
        session_kind=session_kind,
    )
    if write:
        temp_dir.mkdir(parents=True, exist_ok=True)
        MESO_DIAG_DIR.mkdir(parents=True, exist_ok=True)
        write_tiddler(path, tiddler)
        meso_status = plan_mesocycle(MICRO_DIAG_DIR)
    return path, tiddler, meso_status


def _missing_previous_microcycle_ranges(available: list[MicrocycleRef]) -> list[tuple[int, int]]:
    if not available:
        return []
    latest = available[-1]
    expected = [(latest.start - 20, latest.start - 11), (latest.start - 10, latest.start - 1)]
    available_ranges = {(item.start, item.end) for item in available}
    return [
        (start, end)
        for start, end in expected
        if start > 0 and (start, end) not in available_ranges
    ]


def _plan_mesocycle_from_refs(available: list[MicrocycleRef]) -> MesocycleStatus:
    if len(available) < 3:
        missing = _missing_previous_microcycle_ranges(available)
        return MesocycleStatus(False, available, missing, "faltan microciclos suficientes")
    selected = available[-3:]
    continuous = all(left.end + 1 == right.start for left, right in zip(selected, selected[1:]))
    if continuous:
        return MesocycleStatus(True, available, [], "tres microciclos continuos disponibles", selected)
    missing_ranges: list[tuple[int, int]] = []
    for left, right in zip(selected, selected[1:]):
        if left.end + 1 < right.start:
            missing_ranges.append((left.end + 1, right.start - 1))
    return MesocycleStatus(False, available, missing_ranges, "los últimos tres microciclos no son continuos", selected)


def maybe_generate_mesocycle(
    session_origin: str | None = None,
    include_thematic: bool = False,
    write: bool = False,
) -> tuple[Path | None, dict[str, Any] | None, MesocycleStatus]:
    status = plan_mesocycle(MICRO_DIAG_DIR)
    if not status.can_produce:
        return None, None, status
    refs = status.selected
    start = refs[0].start
    end = refs[-1].end
    milestone = refs[-1].milestone
    thematic = discover_thematic_diagnostics(DEFAULT_SESSIONS_DIR) if include_thematic else []
    tag_plan = build_cycle_tags(
        milestone=milestone,
        cycle_type="meso-ciclo",
        start=start,
        end=end,
        existing_tags=load_existing_tags(),
        session_origin=session_origin,
        source_microcycles=True,
        diagnostic_provenance=True,
        remote_read_root=True,
    )
    path = MESO_DIAG_DIR / mesocycle_filename(milestone, start, end)
    tiddler = build_mesocycle_tiddler(refs, tag_plan, thematic, session_origin=session_origin)
    if write:
        write_tiddler(path, tiddler)
    return path, tiddler, status


def _summary(path: Path, tiddler: dict[str, Any], meso_status: MesocycleStatus) -> dict[str, Any]:
    title = str(tiddler["title"])
    range_match = re.search(r"S(\d+)-S(\d+)", title)
    return {
        "microcycle_path": as_display_path(path),
        "microcycle_title": title,
        "microcycle_range": f"S{range_match.group(1)}-S{range_match.group(2)}" if range_match else "",
        "mesocycle_can_produce": meso_status.can_produce,
        "mesocycle_reason": meso_status.reason,
        "mesocycle_available": [ref.display for ref in meso_status.available],
        "mesocycle_missing_ranges": [f"S{start}-S{end}" for start, end in meso_status.missing_ranges],
    }


def _meso_summary(path: Path | None, tiddler: dict[str, Any] | None, meso_status: MesocycleStatus) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "mesocycle_can_produce": meso_status.can_produce,
        "mesocycle_reason": meso_status.reason,
        "mesocycle_available": [ref.display for ref in meso_status.available],
        "mesocycle_missing_ranges": [f"S{start}-S{end}" for start, end in meso_status.missing_ranges],
    }
    if path is not None:
        summary["mesocycle_path"] = as_display_path(path)
    if tiddler is not None:
        summary["mesocycle_title"] = tiddler["title"]
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sessions-dir", type=Path, default=DEFAULT_SESSIONS_DIR)
    parser.add_argument("--count", type=int, default=10)
    parser.add_argument("--milestone", default="m04")
    parser.add_argument("--start-session", type=int, default=None)
    parser.add_argument("--end-session", type=int, default=None)
    parser.add_argument("--session-origin", default=None)
    parser.add_argument("--include-thematic", action="store_true")
    parser.add_argument("--omit-meso-status", action="store_true")
    parser.add_argument("--no-canon-evidence", action="store_true")
    parser.add_argument("--repo-evidence", action="append", default=[])
    parser.add_argument("--session-kind", choices=sorted(SESSION_KIND_POLICIES), default="infraestructura-diagnostica")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--produce-meso", action="store_true")
    parser.add_argument("--meso-only", action="store_true")
    args = parser.parse_args(argv)

    if args.meso_only:
        meso_path, meso_tiddler, meso_status = maybe_generate_mesocycle(
            session_origin=args.session_origin,
            include_thematic=args.include_thematic,
            write=args.write,
        )
        print(json.dumps(_meso_summary(meso_path, meso_tiddler, meso_status), ensure_ascii=False, indent=2))
        return 0 if meso_status.can_produce else 2

    path, tiddler, meso_status = generate_microcycle(
        sessions_dir=args.sessions_dir,
        count=args.count,
        include_thematic=args.include_thematic,
        session_origin=args.session_origin,
        write=args.write,
        milestone=args.milestone,
        start_session=args.start_session,
        end_session=args.end_session,
        include_mesocycle_status=not args.omit_meso_status,
        include_canon_evidence=not args.no_canon_evidence,
        repository_evidence=args.repo_evidence,
        session_kind=args.session_kind,
    )

    meso_path = None
    if args.produce_meso:
        meso_path, _meso_tiddler, meso_status = maybe_generate_mesocycle(
            session_origin=args.session_origin,
            include_thematic=args.include_thematic,
            write=args.write,
        )

    summary = _summary(path, tiddler, meso_status)
    if meso_path is not None:
        summary["mesocycle_path"] = as_display_path(meso_path)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
