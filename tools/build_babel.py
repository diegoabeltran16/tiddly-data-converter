#!/usr/bin/env python3
"""TDC Babel -- static surface generator (build-time only, stdlib only).

    filesystem -> discovery -> Babel model -> render -> index.html + babel/0_pgs-index/

Babel is a derived, non-authoritative navigation surface. It works only with
file names and paths under babel/: it never opens, parses or modifies the
TiddlyWiki HTML files it links to, and it never touches Canon.

Surfaces (identical in local and staging builds, only the location differs):
    index.html                 language selector
    babel/0_pgs-index/<code>/index.html   filesystem view, only for languages with >1 html

Babel writes ONLY <root>/index.html and <root>/babel/0_pgs-index/**; babel/<lang>/** is human-owned.

Usage:
    python3 tools/build_babel.py            # write surfaces under <root>
    python3 tools/build_babel.py --check    # fail if any surface is stale (writes nothing)
    python3 tools/build_babel.py --site DIR # write the same surfaces under DIR (staging)
    python3 tools/build_babel.py --root DIR # use another repository root
"""

from __future__ import annotations

import argparse
import html
import os
import re
import sys
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote, unquote

BABEL_DIR = "babel"
MASCOT = "ux/assets/Open eyes.PNG"
FAVICON = "ux/assets/open eye.png"
FLAGS_DIR = "ux/assets/flags"
OUTPUT = "index.html"
RESERVED_BABEL_DIRS = {"0_pgs-index"}  # babel/0_pgs-index/ is derived output, never a language
DERIVED_INDEX_DIR = f"{BABEL_DIR}/0_pgs-index"  # Babel owns <DERIVED_INDEX_DIR>/<code>/index.html and nothing else
LANG_PREFIX = "../" * len(f"{DERIVED_INDEX_DIR}/<code>".split("/"))  # depth of babel/0_pgs-index/<code>/index.html

# Presentation metadata ONLY. Whether a language exists is decided by the
# babel/<code>/ directory, never by this table. Flags are asset codes
# (ux/assets/flags/<code>.svg). Order = display order for known languages;
# unknown ones follow alphabetically, without flags.
PRESENTATION = {
    "es": ("Español", "ES", ("es", "co", "mx", "ar", "cl")),
    "en": ("English", "EN", ("us", "gb", "ca", "au", "nz")),
    "fr": ("Français", "FR", ("fr", "ca", "be", "ch")),
    "pt": ("Português", "PT", ("pt", "br")),
}
LANG_TAG = re.compile(r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*$")
FLAG_CODE = re.compile(r"^[a-z0-9-]+$")


class BuildError(Exception):
    """The build cannot produce a valid surface."""


# --- Babel model -----------------------------------------------------------

@dataclass(frozen=True)
class Artifact:
    rel: str  # POSIX path relative to babel/<lang>/, e.g. "dominio/a.html"

    def href(self, lang: str, prefix: str = "./") -> str:
        return prefix + quote(f"{BABEL_DIR}/{lang}/{self.rel}", safe="/")


@dataclass(frozen=True)
class Language:
    code: str
    name: str
    visible: str
    flags: tuple[str, ...]
    artifacts: tuple[Artifact, ...]

    @property
    def tag(self) -> str | None:
        """BCP 47-shaped code usable in lang/hreflang, else None."""
        return self.code if LANG_TAG.match(self.code) else None

    @property
    def page_path(self) -> str:
        """Site-relative path of the derived filesystem view (used when there are several html)."""
        return f"{DERIVED_INDEX_DIR}/{self.code}/index.html"

    @property
    def page_href(self) -> str:
        return f"./{DERIVED_INDEX_DIR}/{quote(self.code, safe='')}/index.html"


def _flag_src(code: str, prefix: str) -> str:
    return f"{prefix}{FLAGS_DIR}/{code}.svg"


def _favicon_href(prefix: str) -> str:
    return prefix + quote(FAVICON, safe="/")


# --- Discovery adapter (filesystem -> model). Names/paths only. ------------

def discover(root: Path) -> list[Language]:
    babel = root / BABEL_DIR
    if babel.is_symlink() or not babel.is_dir():
        raise BuildError(f"{BABEL_DIR}/ does not exist or is not a directory: {babel}")
    real_babel = babel.resolve()

    languages = []
    try:
        entries = sorted(os.scandir(babel), key=lambda e: e.name)
    except OSError as exc:
        raise BuildError(f"cannot inspect {babel}: {exc}") from exc
    for entry in entries:
        if entry.name.startswith(".") or entry.name in RESERVED_BABEL_DIRS:
            continue
        if entry.is_symlink() or not entry.is_dir(follow_symlinks=False):
            continue
        artifacts = _scan_language(Path(entry.path), real_babel)
        name, visible, flags = PRESENTATION.get(entry.name, (entry.name, entry.name.upper(), ()))
        languages.append(Language(entry.name, name, visible, flags, artifacts))

    known = list(PRESENTATION)
    languages.sort(key=lambda l: (known.index(l.code) if l.code in known else len(known), l.code))
    return languages


def _scan_language(lang_dir: Path, real_babel: Path) -> tuple[Artifact, ...]:
    found = []
    # followlinks=False + skipping symlinked files: nothing outside babel/ is reachable.
    for dirpath, dirnames, filenames in os.walk(lang_dir, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        for fname in filenames:
            path = Path(dirpath) / fname
            if not fname.lower().endswith(".html") or path.is_symlink() or not path.is_file():
                continue
            try:
                path.resolve().relative_to(real_babel)
            except ValueError as exc:
                raise BuildError(f"path escapes {BABEL_DIR}/: {path}") from exc
            found.append(Artifact(path.relative_to(lang_dir).as_posix()))
    return tuple(sorted(found, key=lambda a: (a.rel.casefold(), a.rel)))


# --- HTML renderer adapter (model -> text) ---------------------------------

def _t(text: str) -> str:
    return html.escape(text, quote=True)


def _lang_attr(tag: str | None, attr: str = "lang") -> str:
    return f' {attr}="{_t(tag)}"' if tag else ""


BASE_CSS = """\
:root{--bg:#100F0F;--surface:#1C1B1A;--text:#CECDC3;--muted:#878580;--border:#343331;--cyan:#3AA99F;--magenta:#CE5D97}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:1rem/1.5 ui-monospace,SFMono-Regular,Menlo,Consolas,"Liberation Mono",monospace;color-scheme:dark}
main{max-width:44rem;margin:0 auto;padding:4rem 1rem}
h1{margin:0;font-size:clamp(2rem,8vw,3rem);letter-spacing:.05em}
h1 .c{color:var(--cyan)}h1 .m{color:var(--magenta)}h1 .sep{color:var(--muted);font-weight:400;padding:0 .25em}
a:focus-visible{outline:2px solid var(--magenta);outline-offset:3px}
.flags{display:flex;justify-content:center;align-items:center;gap:.4rem;min-height:1.1rem}
.flags img{width:1.5rem;height:auto;display:block}
.code{color:var(--muted)}
"""

# Hexagon = clipped element (ring colour) + inset ::before (surface). clip-path
# also clips outlines, so hover/focus change the ring colour and thickness.
INDEX_CSS = """\
header{display:flex;flex-direction:column;align-items:center;gap:1.5rem;margin-bottom:4rem}
header img{width:min(8rem,40vw);height:auto}
nav{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:1.5rem}
.hex{--ring:var(--border);--inset:2px;position:relative;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:.5rem;width:100%;max-width:15rem;aspect-ratio:1/1.1547;justify-self:center;padding:0 1rem;background:var(--ring);clip-path:polygon(50% 0,100% 25%,100% 75%,50% 100%,0 75%,0 25%);color:inherit;text-decoration:none;text-align:center}
.hex::before{content:"";position:absolute;inset:var(--inset);background:var(--surface);clip-path:inherit}
.hex>*{position:relative}
.hex .flags{margin-bottom:.75rem}
.hex .name{font-size:1.25rem;font-weight:700}
a.hex:hover{--ring:var(--cyan)}
a.hex:focus-visible{--ring:var(--magenta);--inset:5px;outline:none}
a.hex:hover .name,a.hex:focus-visible .name{text-decoration:underline}
.empty{opacity:.45}
@media (max-width:34rem){nav{grid-template-columns:minmax(0,1fr)}}
"""

# Filesystem view: connectors are text glyphs (guaranteed to render, hidden
# from assistive tech); the hierarchy itself is nested <ul>.
LANG_CSS = """\
.back{color:var(--muted);text-decoration:none}
.back:hover,.back:focus-visible{color:var(--text);text-decoration:underline}
header{display:flex;flex-direction:column;align-items:center;margin:2rem 0 3rem;text-align:center}
header .flags{margin-bottom:1rem}
h1{font-size:1.5rem;letter-spacing:0}
ul{margin:0;padding:0;list-style:none;line-height:1.35}
nav>ul>li{margin-bottom:1.75rem}
.t{color:var(--muted);white-space:pre}
.d{color:var(--cyan);white-space:pre-wrap;overflow-wrap:anywhere}
li a{color:var(--text);white-space:pre-wrap;overflow-wrap:anywhere;text-decoration:none}
li a:hover,li a:focus-visible{color:var(--magenta);text-decoration:underline}
@media (max-width:34rem){nav{font-size:.875rem}}
"""


def _page(title: str, lang: str, css: str, body: str, favicon_href: str) -> str:
    return f"""<!doctype html>
<html lang="{_t(lang)}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="dark">
<title>{_t(title)}</title>
<link rel="icon" type="image/png" href="{_t(favicon_href)}">
<style>
{BASE_CSS}{css}</style>
</head>
<body>
<main>
{body}
</main>
</body>
</html>
"""


def _flags_html(lang: Language, prefix: str) -> str:
    imgs = "".join(
        f'<img src="{_t(_flag_src(c, prefix))}" alt="" width="60" height="40">' for c in lang.flags
    )
    return f'<span class="flags" aria-hidden="true">{imgs}</span>'


def _render_language(lang: Language) -> str:
    inner = (
        f'{_flags_html(lang, "./")}\n'
        f'    <span class="name"{_lang_attr(lang.tag)}>{_t(lang.name)}</span>\n'
        f'    <span class="code">{_t(lang.visible)}</span>'
    )
    if not lang.artifacts:  # language dir exists, nothing to open yet
        return f'  <div class="hex empty">\n    {inner}\n  </div>'
    # One HTML: straight to the TiddlyWiki. Several: to the derived filesystem view.
    href = lang.artifacts[0].href(lang.code) if len(lang.artifacts) == 1 else lang.page_href
    return f'  <a class="hex" href="{_t(href)}"{_lang_attr(lang.tag, "hreflang")}>\n    {inner}\n  </a>'


def render_index(languages: list[Language]) -> str:
    cards = "\n".join(_render_language(l) for l in languages)
    return _page("tdc", "en", INDEX_CSS, f"""<header>
  <img src="./{_t(quote(MASCOT, safe="/"))}" alt="TDC Babel mascot: a black cat face with green eyes" width="512" height="512">
  <h1><span class="c">TDC</span><span class="sep" aria-hidden="true">|</span><span class="m">BABEL</span></h1>
</header>
<nav aria-label="Languages">
{cards}
</nav>""", _favicon_href("./"))


def _tree(artifacts: tuple[Artifact, ...]) -> dict:
    """Physical hierarchy only: dict = directory, Artifact = file."""
    root: dict = {}
    for art in artifacts:
        *dirs, name = art.rel.split("/")
        node = root
        for d in dirs:
            node = node.setdefault(d, {})
        node[name] = art
    return root


def _tree_html(node: dict, lang: Language, lead: str = "", top: bool = True) -> str:
    """Directories first, then files, each casefolded. `lead` = ancestors' guide glyphs."""
    items = sorted(node.items(), key=lambda kv: (not isinstance(kv[1], dict), kv[0].casefold(), kv[0]))
    lines = []
    for i, (name, child) in enumerate(items):
        last = i == len(items) - 1
        glyph = "" if top else ("└── " if last else "├── ")
        pre = f'<span class="t" aria-hidden="true">{lead}{glyph}</span>' if not top else ""
        if isinstance(child, dict):
            inner = _tree_html(child, lang, lead + ("" if top else "    " if last else "│   "), False)
            lines.append(f'<li>{pre}<span class="d">{_t(name)}/</span>\n{inner}</li>')
        else:
            href = _t(child.href(lang.code, LANG_PREFIX))
            lines.append(f'<li>{pre}<a href="{href}"{_lang_attr(lang.tag, "hreflang")}>{_t(name)}</a></li>')
    return "<ul>\n" + "\n".join(lines) + "\n</ul>\n"


def render_language_page(lang: Language) -> str:
    return _page(f"{lang.name} | tdc", lang.tag or "en", LANG_CSS, f"""<a class="back" href="{LANG_PREFIX}{OUTPUT}"><span aria-hidden="true">←</span> TDC | BABEL</a>
<header>
  {_flags_html(lang, LANG_PREFIX)}
  <h1{_lang_attr(lang.tag)}>{_t(lang.name)}</h1>
  <span class="code">{_t(lang.visible)}</span>
</header>
<nav aria-label="{_t(lang.name)}">
{_tree_html(_tree(lang.artifacts), lang)}</nav>""", _favicon_href(LANG_PREFIX))


def render_surfaces(languages: list[Language]) -> dict[str, str]:
    """The single renderer for local, staging and --check: site-relative path -> HTML."""
    surfaces = {OUTPUT: render_index(languages)}
    for l in languages:
        if len(l.artifacts) > 1:
            surfaces[l.page_path] = render_language_page(l)
    return surfaces


# --- Validation ------------------------------------------------------------

class _Audit(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []
        self.srcs: list[str] = []
        self.icons: list[str] = []
        self.problems: list[str] = []

    def handle_starttag(self, tag, attrs):
        adict = dict(attrs)
        if tag == "link":
            # Only a local favicon <link> is allowed; anything else (stylesheet,
            # manifest, preload, ...) stays forbidden.
            if adict.get("rel") != "icon":
                self.problems.append(f"forbidden <link rel={adict.get('rel')!r}>")
            else:
                self.icons.append(adict.get("href") or "")
        elif tag in {"script", "iframe", "object", "embed", "form"}:
            self.problems.append(f"forbidden element <{tag}>")
        for key, value in attrs:
            if key.startswith("on"):
                self.problems.append(f"inline event handler {key}")
            if key == "href" and tag == "a":
                self.hrefs.append(value or "")
            elif key == "src":
                self.srcs.append(value or "")
            elif key in {"href", "src", "action"} and re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", value or ""):
                self.problems.append(f"absolute URL in {tag}[{key}]")


def _audit(page: str) -> _Audit:
    audit = _Audit()
    audit.feed(page)
    if audit.problems:
        raise BuildError("generated page is not passive: " + "; ".join(audit.problems))
    return audit


def validate(root: Path, languages: list[Language], surfaces: dict[str, str]) -> None:
    """Structure of the surfaces vs. the discovered model (source-side checks)."""
    if not languages:
        raise BuildError(f"no language directories under {BABEL_DIR}/")
    if not any(l.artifacts for l in languages):
        raise BuildError(f"no .html artifacts under {BABEL_DIR}/<lang>/")

    # flag assets referenced by presentation metadata: fail fast, no broken <img>
    flags_root = root / FLAGS_DIR
    for l in languages:
        for code in l.flags:
            svg = flags_root / f"{code}.svg"
            if not FLAG_CODE.match(code) or svg.is_symlink() or not svg.is_file():
                raise BuildError(f"flag asset missing or invalid for {l.code!r}: {FLAGS_DIR}/{code}.svg")

    # favicon: fail fast, no broken <link rel="icon">
    favicon = root / FAVICON
    if favicon.is_symlink() or not favicon.is_file():
        raise BuildError(f"favicon missing or invalid: {FAVICON}")

    # index.html: one link per non-empty language -- the TiddlyWiki itself
    # (exactly 1 html) or the derived filesystem view (several). Nothing else.
    hrefs = [
        l.artifacts[0].href(l.code) if len(l.artifacts) == 1 else l.page_href
        for l in languages if l.artifacts
    ]
    srcs = ["./" + quote(MASCOT, safe="/")] + [_flag_src(c, "./") for l in languages for c in l.flags]
    audit = _audit(surfaces[OUTPUT])
    if (sorted(audit.hrefs) != sorted(hrefs) or sorted(audit.srcs) != sorted(srcs)
            or audit.icons != [_favicon_href("./")]):
        raise BuildError("index.html links differ from the discovered model")

    # filesystem views: back link + every artifact of that language + its flags.
    wanted = {OUTPUT} | {l.page_path for l in languages if len(l.artifacts) > 1}
    if set(surfaces) != wanted:
        raise BuildError("rendered surfaces differ from the expected set")
    for l in (l for l in languages if len(l.artifacts) > 1):
        audit = _audit(surfaces[l.page_path])
        want = [a.href(l.code, LANG_PREFIX) for a in l.artifacts] + [LANG_PREFIX + OUTPUT]
        if (sorted(audit.hrefs) != sorted(want)
                or sorted(audit.srcs) != sorted(_flag_src(c, LANG_PREFIX) for c in l.flags)
                or audit.icons != [_favicon_href(LANG_PREFIX)]):
            raise BuildError(f"filesystem view for {l.code!r} does not match its artifacts")

    if render_surfaces(languages) != surfaces:
        raise BuildError("render is not deterministic")


def check_links(base: Path, surfaces: dict[str, str]) -> None:
    """Every href/src of every surface must resolve to a regular file under `base`."""
    for rel, page in surfaces.items():
        audit = _audit(page)
        for link in audit.hrefs + audit.srcs + audit.icons:
            target = Path(os.path.normpath((base / rel).parent / unquote(link)))
            if not target.is_file():
                raise BuildError(f"{rel}: link does not resolve: {link!r}")


def _snapshot(languages: list[Language], root: Path) -> dict[Path, tuple[int, int]]:
    snap = {}
    for l in languages:
        for a in l.artifacts:
            st = (root / BABEL_DIR / l.code / a.rel).stat()
            snap[Path(l.code) / a.rel] = (st.st_size, st.st_mtime_ns)
    return snap


# --- Derived-surface writer (only touches <base>/index.html and <base>/babel/0_pgs-index/) ---

def _stale_derived(base: Path, wanted: set[str]) -> list[Path]:
    """Managed dirs under <base>/babel/0_pgs-index/ no longer expected.

    babel/0_pgs-index/ may only contain <code>/index.html; anything else is not ours,
    so the build refuses instead of deleting it.
    """
    derived = base / DERIVED_INDEX_DIR
    if not os.path.lexists(derived):
        return []
    if derived.is_symlink() or not derived.is_dir():
        raise BuildError(f"{DERIVED_INDEX_DIR}/ is not a plain directory: {derived}")
    stale = []
    for entry in sorted(os.scandir(derived), key=lambda e: e.name):
        if entry.is_symlink() or not entry.is_dir(follow_symlinks=False):
            raise BuildError(f"unmanaged entry in {DERIVED_INDEX_DIR}/: {entry.name}")
        for inner in os.scandir(entry.path):
            if inner.name != "index.html" or inner.is_symlink() or not inner.is_file(follow_symlinks=False):
                raise BuildError(f"unmanaged entry in {DERIVED_INDEX_DIR}/{entry.name}/: {inner.name}")
        if entry.name not in wanted:
            stale.append(Path(entry.path))
    return stale


def _guard_base(root: Path, base: Path) -> None:
    real_babel = (root / BABEL_DIR).resolve()
    if base == real_babel or real_babel in base.parents:
        raise BuildError(f"--site must not be inside {BABEL_DIR}/: {base}")


def _assert_managed(base: Path, rel: str) -> None:
    """Write boundary: only <base>/index.html and <base>/babel/0_pgs-index/**."""
    parts = Path(rel).parts
    if rel != OUTPUT and (parts[:2] != tuple(DERIVED_INDEX_DIR.split("/")) or ".." in parts):
        raise BuildError(f"refusing to write outside the managed surface: {rel}")
    if rel != OUTPUT and (base / DERIVED_INDEX_DIR).resolve() not in (base / rel).resolve().parents:
        raise BuildError(f"managed path escapes {DERIVED_INDEX_DIR}/: {rel}")


def _write(base: Path, surfaces: dict[str, str], stale: list[Path]) -> None:
    for rel in surfaces:
        _assert_managed(base, rel)
    for d in stale:
        _assert_managed(base, (d / "index.html").relative_to(base).as_posix())
    for rel, page in surfaces.items():
        target = base / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(page, encoding="utf-8", newline="\n")
    for d in stale:
        (d / "index.html").unlink(missing_ok=True)
        d.rmdir()
    derived = base / DERIVED_INDEX_DIR
    if derived.is_dir() and not any(derived.iterdir()):
        derived.rmdir()


def _verify_written(base: Path, surfaces: dict[str, str], stale: list[Path]) -> None:
    problems = [f"{rel} is missing or stale" for rel, page in surfaces.items()
                if not (base / rel).is_file() or (base / rel).read_text(encoding="utf-8") != page]
    problems += [f"obsolete derived surface: {d.relative_to(base).as_posix()}/" for d in stale]
    if problems:
        raise BuildError("; ".join(problems))


# --- Orchestration ---------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--check", action="store_true", help="write nothing; fail if any surface is stale")
    parser.add_argument("--site", type=Path, help="write the same surfaces under this staging dir instead of <root>")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    base = args.site.resolve() if args.site else root

    try:
        _guard_base(root, base)
        languages = discover(root)
        before = _snapshot(languages, root)
        surfaces = render_surfaces(languages)
        validate(root, languages, surfaces)
        stale = _stale_derived(base, {l.code for l in languages if len(l.artifacts) > 1})
        if args.check:
            _verify_written(base, surfaces, stale)
        else:
            _write(base, surfaces, stale)
        check_links(base, surfaces)
        if _snapshot(languages, root) != before:
            raise BuildError("an artifact under babel/ changed during the build")
    except (BuildError, OSError) as exc:
        print(f"build_babel: error: {exc}", file=sys.stderr)
        return 1

    for l in languages:
        print(f"build_babel: {l.code}: {len(l.artifacts)} html")
    verb = "checked" if args.check else "wrote"
    print(f"build_babel: {verb} {', '.join(sorted(surfaces))}" + (f" (removed {len(stale)} obsolete)" if stale and not args.check else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
