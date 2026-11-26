# Read workflow and UI definitions from YAML and resolve their IDs for API and runtime callers.
from pathlib import Path
import hashlib, os, re, shutil, zipfile, yaml

# Resolve this module's location so definition paths work regardless of the current working directory.
APP_DIR = Path(__file__).resolve().parents[1]
# Set the core directory under which editable YAML and XML live.
DEFINITIONS = APP_DIR / "definitions"
UI_DIR = DEFINITIONS / "ui"
FLOW_DIR = DEFINITIONS / "flows"
SCHEMA_DIR = DEFINITIONS / "schemas"
WORKFLOW_DIR = DEFINITIONS / "workflows"
TEMPLATE_DIR = DEFINITIONS / "templates"
COMMON_UI_ID = "common-ui"
COMMON_UI_PATH = "ui/common-ui.yaml"

# ---- Definition packs (.jar / .zip) -------------------------------------------------
# A pack mirrors the layout of backend/app/definitions/ and may add or override flows,
# UIs and XML templates. Packs contain data only (YAML/XML); no code is ever executed.
# Later packs (alphabetical) override earlier packs, and every pack overrides the core files.
# Read the optional pack location from the environment and otherwise use the backend packs directory.
PACKS_DIR = Path(os.getenv("WORKFLOW_PACKS_DIR") or APP_DIR.parent / "packs")
PACK_CACHE_DIR = APP_DIR.parent / ".pack-cache"
PACK_SUFFIXES = {".jar", ".zip"}
# Limit extracted pack data to YAML and XML extensions.
PACK_ALLOWED_SUFFIXES = {".yaml", ".yml", ".xml"}
# Keep archive files from overriding the core schema directory.
PACK_PROTECTED = ("schemas/",)
# Limit entry count, individual file size, and total uncompressed bytes.
PACK_MAX_ENTRIES, PACK_MAX_FILE, PACK_MAX_TOTAL = 500, 500_000, 20_000_000


# Receive a pack archive path and destination, then unpack its workflow definitions.
def _extract_pack(jar: Path, target: Path) -> None:
    # Stage the extraction in a sibling directory before publishing the cache entry.
    tmp = target.with_name(target.name + ".tmp")
    # Remove staging files that may remain from an earlier interrupted extraction.
    if tmp.exists(): shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    total = 0
    # Read JAR and ZIP packs with the same standard-library archive reader.
    with zipfile.ZipFile(jar) as archive:
        # Count files only because directories are created as needed.
        infos = [i for i in archive.infolist() if not i.is_dir()]
        if len(infos) > PACK_MAX_ENTRIES: raise ValueError(f"{jar.name}: too many entries")
        for info in infos:
            # Normalize archive separators before treating the name as a filesystem path.
            rel = Path(info.filename.replace("\\", "/"))
            parts = list(rel.parts)
            # Accept packs that include an optional top-level definitions folder.
            if parts and parts[0] == "definitions": parts = parts[1:]
            # Skip empty paths, absolute paths, and parent traversal.
            if not parts or rel.is_absolute() or ".." in rel.parts: continue
            # Skip archive metadata and files outside the allowed data formats.
            if parts[0] == "META-INF" or Path(*parts).suffix.lower() not in PACK_ALLOWED_SUFFIXES: continue
            # Build a slash-delimited path for matching protected roots and reporting errors.
            posix = "/".join(parts)
            if any(posix == name or posix.startswith(name) for name in PACK_PROTECTED): continue
            if info.file_size > PACK_MAX_FILE: raise ValueError(f"{jar.name}: {posix} exceeds 500 KB")
            # Accumulate each allowed entry's declared uncompressed size.
            total += info.file_size
            if total > PACK_MAX_TOTAL: raise ValueError(f"{jar.name}: pack is too large")
            # Resolve a concrete destination before writing the archive member.
            out = (tmp / Path(*parts)).resolve()
            # Skip any resolved target outside the staging directory.
            if tmp.resolve() not in out.parents: continue
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(archive.read(info))
    if target.exists(): shutil.rmtree(target)
    # Publish the extracted pack at the cache path after extraction finishes.
    tmp.rename(target)


# Refresh locally available definition packs and return information about them.
def sync_packs() -> list[dict]:
    """Extract new or changed packs into the cache; drop cache entries of removed packs."""
    # Collect response metadata and remember cache directories used by current packs.
    rows, keep = [], set()
    # Find known archive extensions and sort packs by path for consistent precedence.
    jars = sorted(p for p in PACKS_DIR.glob("*") if p.is_file() and p.suffix.lower() in PACK_SUFFIXES) if PACKS_DIR.exists() else []
    for jar in jars:
        stat = jar.stat()
        # Use the name, timestamp, and size as a cache key. This hash identifies a cached version.
        key = hashlib.sha1(f"{jar.name}:{stat.st_mtime_ns}:{stat.st_size}".encode()).hexdigest()[:10]
        target = PACK_CACHE_DIR / f"{jar.stem}-{key}"
        row = {"name": jar.name, "size": stat.st_size, "modified": int(stat.st_mtime), "loaded": False, "error": None}
        try:
            # Reuse existing cache contents for an unchanged archive.
            if not target.exists(): _extract_pack(jar, target)
            keep.add(target.name); row["loaded"] = True; row["_dir"] = target
        except Exception as exc:  # a broken pack must not take the backend down
            # Report an individual pack failure while continuing with the remaining packs.
            row["error"] = str(exc)
        rows.append(row)
    # Find cache directories no longer associated with a loaded pack.
    if PACK_CACHE_DIR.exists():
        for child in PACK_CACHE_DIR.iterdir():
            if child.is_dir() and child.name not in keep: shutil.rmtree(child, ignore_errors=True)
    return rows


# Return locations searched for workflow definitions.
def definition_roots() -> list[Path]:
    """Search order: newest pack first ... oldest pack, then the core definitions folder."""
    # Reverse pack order so later alphabetical packs are searched first.
    roots = [row["_dir"] for row in reversed(sync_packs()) if row.get("_dir")]
    # Search core files after packs, so the first resolved pack definition takes precedence.
    return roots + [DEFINITIONS]


# Return metadata for the available workflow packs.
def list_packs() -> list[dict]:
    # Return public metadata without exposing the internal cache path field.
    return [{k: v for k, v in row.items() if k != "_dir"} for row in sync_packs()]

# Validate the ID used to locate a definition.
def _safe_id(value: str) -> str:
    # Accept lowercase alphanumeric groups separated by single hyphens.
    if not isinstance(value, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", value):
        raise ValueError("Definition ID must be lowercase kebab-case")
    return value

# Read and parse the YAML stored at a definition path.
def _read(path: Path):
    if not path.is_file(): raise FileNotFoundError(path.name)
    # Parse UTF-8 YAML as data with PyYAML's safe loader.
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict): raise ValueError(f"{path.name}: YAML root must be a mapping")
    return data

# Resolve a UI definition for the supplied workflow ID.
def load_ui(flow_id: str):
    from .workflow_ui import build_workflow_ui

    # Load the core shared UI as the starting point for every generated workflow form.
    template = _read(DEFINITIONS / COMMON_UI_PATH)
    # Return the shared template directly when the caller asks for it.
    if flow_id == COMMON_UI_ID:
        return template
    try:
        flow = load_flow(flow_id)
    except FileNotFoundError:
        if not flow_id.endswith("-ui"):
            raise
        # Retry a legacy UI-style ID as the corresponding workflow ID.
        flow = load_flow(flow_id.removesuffix("-ui"))
    # Generate presentation metadata from the template and workflow definitions.
    return build_workflow_ui(template, flow)

# Find workflow YAML files under the given definition root.
def flow_definition_paths(root: Path) -> list[Path]:
    # Include legacy workflow filenames before adding current workflow layouts.
    paths = list((root / "flows").glob("*-flow.yaml"))
    workflows = root / "workflows"
    paths.extend(workflows.glob("*/flow.yaml"))
    paths.extend(workflows.glob("*.yaml"))
    paths.extend(workflows.glob("*.yml"))
    # Return stable path order and avoid duplicates.
    return sorted(set(paths))

# Find and parse the workflow associated with the requested ID.
def load_flow(flow_id: str):
    # Validate the ID before using it to construct candidate file paths.
    flow_id = _safe_id(flow_id); filename = flow_id if flow_id.endswith("-flow") else f"{flow_id}-flow"
    for root in definition_roots():
        # Try legacy and nested layouts first within each definition root.
        for path in (root / "flows" / f"{filename}.yaml", root / "workflows" / flow_id.removesuffix("-flow") / "flow.yaml"):
            if path.is_file(): return _read(path)
        # Collect flat YAML files whose declared ID matches, independently of filename.
        matches = []
        for path in sorted(
            list((root / "workflows").glob("*.yaml"))
            + list((root / "workflows").glob("*.yml"))
        ):
            try:
                data = yaml.safe_load(path.read_text(encoding="utf-8"))
            except OSError as exc:
                raise ValueError(f"Workflow definition is unavailable: {path.name}") from exc
            except yaml.YAMLError as exc:
                raise ValueError(f"Workflow definition is invalid: {path.name}") from exc
            # Skip a blank YAML file during the flat-file lookup.
            if data is None:
                continue
            if not isinstance(data, dict):
                raise ValueError(f"{path.name}: YAML root must be a mapping")
            if data.get("id") == flow_id:
                matches.append((path, data))
        # Reject ambiguous IDs declared in multiple files of the same root.
        if len(matches) > 1:
            raise ValueError(
                f"Multiple workflow files declare the flow ID {flow_id}: "
                + ", ".join(path.name for path, _ in matches)
            )
        if matches:
            return matches[0][1]
    raise FileNotFoundError(f"{filename}.yaml")

# Return identifiers for the workflows available to the runtime.
def list_flow_ids() -> list[str]:
    ids: set[str] = set()
    for root in definition_roots():
        for path in flow_definition_paths(root):
            try:
                # Use a set to expose each valid ID only once across core and pack roots.
                ids.add(_safe_id(_read(path).get("id")))
            except (OSError, ValueError, yaml.YAMLError):
                continue
    return sorted(ids)

# Build catalog entries for workflows available to the UI.
def list_definitions():
    items=[]
    for flow_id in list_flow_ids():
        try:
            flow=load_flow(flow_id)
            items.append({"id":flow_id,"name":flow.get("name",flow_id),"flow":flow_id,
                          "version":flow.get("version","1.0"),"description":flow.get("description","")})
        except Exception: continue
    return items

# Validate and save a definition under the given kind and ID.
def save_definition(kind: str, definition_id: str, content: str, create: bool=False):
    definition_id=_safe_id(definition_id); directory=UI_DIR if kind=="ui" else FLOW_DIR
    if kind == "ui" and definition_id != COMMON_UI_ID:
        raise ValueError("Edit ui/common-ui.yaml to change the shared UI")
    suffix=".yaml" if kind=="ui" else "-flow.yaml"; path=directory/f"{definition_id}{suffix}"
    # Avoid replacing a definition when the caller requests creation only.
    if create and path.exists(): raise FileExistsError(definition_id)
    parsed=yaml.safe_load(content)
    if not isinstance(parsed,dict) or parsed.get("id") != definition_id:
        raise ValueError("YAML id must match the URL definition ID")
    directory.mkdir(parents=True,exist_ok=True); path.write_text(content,encoding="utf-8")
    return parsed

# Resolve a relative definition path inside the configured directory.
def _safe_definition_path(relative_path: str) -> Path:
    if not isinstance(relative_path, str) or not relative_path.strip(): raise ValueError("File path is required")
    # Normalize separators before checking the relative path.
    rel=Path(relative_path.replace("\\", "/"))
    if rel.is_absolute() or ".." in rel.parts: raise ValueError("Invalid definition file path")
    if rel.suffix.lower() not in {".yaml", ".yml", ".xml"}: raise ValueError("Only YAML and XML files are allowed")
    base=DEFINITIONS.resolve(); target=(base/rel).resolve()
    # Check the resolved target stays within the definitions directory.
    if base not in target.parents: raise ValueError("File path escapes definitions directory")
    return target

# Return file information for the studio definition browser.
def list_files():
    rows=[]
    if DEFINITIONS.exists():
        # Walk definition files in predictable order for the studio.
        for path in sorted(DEFINITIONS.rglob("*")):
            if path.is_file() and path.suffix.lower() in {".yaml", ".yml", ".xml"}:
                rows.append({"path":path.relative_to(DEFINITIONS).as_posix(),"type":path.suffix.lower()[1:],"size":path.stat().st_size})
    return rows

# Read a definition selected by its relative path.
def read_file(relative_path: str):
    path=_safe_definition_path(relative_path)
    if not path.is_file(): raise FileNotFoundError(relative_path)
    return {"path":relative_path,"content":path.read_text(encoding="utf-8"),"type":path.suffix.lower()[1:]}


# Save generated YAML under its workflow ID and return its relative path.
def save_generated_workflow(flow_id: str, content: str) -> str:
    flow_id = _safe_id(flow_id)
    if len(flow_id) > 100:
        raise ValueError("Workflow ID must be 100 characters or fewer.")
    if flow_id in list_flow_ids():
        raise FileExistsError(flow_id)
    # Use the declared workflow ID as the generated YAML filename.
    path = f"workflows/{flow_id}.yaml"
    write_file(path, content, create_only=True)
    return path

# Persist definition text at a relative path and honor the create-only flag.
def write_file(relative_path: str, content: str, create_only: bool=False):
    path=_safe_definition_path(relative_path)
    # Classify the target using its location relative to definitions.
    relative = path.relative_to(DEFINITIONS.resolve())
    if path.suffix in {".yaml", ".yml"} and (relative.parts[0] == "ui" or path.stem.endswith("-ui") or path.stem == "ui"):
        if relative.as_posix() != COMMON_UI_PATH:
            raise ValueError("Edit ui/common-ui.yaml to change the shared UI")
        from .workflow_validation import validate_ui
        # Parse and validate the shared UI before writing it.
        validate_ui(yaml.safe_load(content))
    if len(content) > 500_000: raise ValueError("File exceeds 500 KB")
    if path.suffix.lower() in {".yaml", ".yml"}:
        parsed=yaml.safe_load(content)
        if parsed is None: raise ValueError("YAML file cannot be empty")
    path.parent.mkdir(parents=True,exist_ok=True)
    # Use exclusive creation for a new file and write mode for an update.
    with path.open("x" if create_only else "w", encoding="utf-8") as file:
        file.write(content)
    return {"saved":True,"path":relative_path,"size":path.stat().st_size}
