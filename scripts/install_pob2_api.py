"""Install a reversible, opt-in PoB2 TCP API hook. Does not restart PoB."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys

API_FILES = ("BuildOps.lua", "Handlers.lua", "TcpServer.lua", "Server.lua", "GemEvaluator.lua", "ItemEvaluator.lua", "TreeEvaluator.lua", "XmlSemantics.lua")
STATE_NAME = ".poe2-mcp-install.json"
BEGIN = "-- [poe2-mcp API begin]"
END = "-- [poe2-mcp API end]"
HOOK = """\t-- [poe2-mcp API begin]
\tlocal apiBase = (GetScriptPath and GetScriptPath()) or '.'
\tlocal apiLog = io.open(apiBase .. '/API/startup.log', 'w')
\tlocal function apiStatus(message)
\t\tif apiLog then apiLog:write(message .. '\\n'); apiLog:flush() end
\tend
\tapiStatus('Enabled: ' .. tostring(os.getenv('POB_API_TCP')))
\tif os.getenv('POB_API_TCP') == '1' then
\t\tlocal okApi, api = pcall(dofile, apiBase .. '/API/Handlers.lua')
\t\tlocal okServer, server = pcall(dofile, apiBase .. '/API/TcpServer.lua')
\t\tapiStatus('Handlers: ' .. tostring(okApi) .. ' ' .. tostring(api))
\t\tapiStatus('TCP: ' .. tostring(okServer) .. ' ' .. tostring(server))
\t\tif okServer then apiStatus('Socket: ' .. tostring(server.available) .. ' ' .. tostring(server.unavailableReason)) end
\t\tif okApi and okServer and server.available then
\t\t\tlocal port = tonumber(os.getenv('POB_API_TCP_PORT')) or 59166
\t\t\tlocal initOk, started = pcall(server.init, api.handlers, port)
\t\t\tapiStatus('Init: ' .. tostring(initOk) .. ' ' .. tostring(started) .. ' ' .. tostring(server.lastError))
\t\t\tif initOk and started then
\t\t\t\tapiStatus('Listening: ' .. tostring(port))
\t\t\t\tself.onFrameFuncs['PoB2TcpApi'] = function() server.pump() end
\t\t\t\tConPrintf('[PoB2 API] Listening on loopback port %d', port)
\t\t\tend
\t\telse
\t\t\tConPrintf('[PoB2 API] Load failed: %s / %s', tostring(api), tostring(server))
\t\tend
\tend
\tif apiLog then apiLog:close() end
\t-- [poe2-mcp API end]
"""

def sha(data):
    return hashlib.sha256(data).hexdigest()

def atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".poe2-tmp")
    temporary.write_bytes(data)
    os.replace(temporary, path)

def read_state(install):
    path = install / "API" / STATE_NAME
    return json.loads(path.read_text()) if path.exists() else None

def patch_main(original):
    text = original.decode("utf-8")
    if BEGIN in text or "-- [pob-mcp TCP API patch]" in text:
        raise ValueError("An existing API hook must be managed with its recorded backup")
    boundary = re.compile(r"(?m)^end(\r?\n(?:\r?\n)*)(?=function main:DetectUnicodeSupport\(\))")
    if len(list(boundary.finditer(text))) != 1 or "function main:Init()" not in text:
        raise ValueError("PoB2 Main.lua layout is incompatible; no files were patched")
    hook = HOOK.replace("\n", "\r\n") if "\r\n" in text else HOOK
    return boundary.sub(lambda m: hook + "end" + m.group(1), text).encode("utf-8")

def write_transaction(writes, removals=()):
    paths = list(dict.fromkeys([*writes, *removals]))
    previous = {path: path.read_bytes() if path.exists() else None for path in paths}
    changed = []
    try:
        for path, data in writes.items():
            changed.append(path)
            atomic_write(path, data)
        for path in removals:
            changed.append(path)
            path.unlink(missing_ok=True)
    except Exception:
        for path in reversed(changed):
            if previous[path] is None:
                path.unlink(missing_ok=True)
            else:
                atomic_write(path, previous[path])
        raise


def relative_target(root, value):
    if not isinstance(value, str) or not value or "\\" in value or ":" in value:
        raise ValueError("Invalid calculator patch path")
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("Calculator patch path escapes installation")
    target = root / relative
    if not target.resolve().is_relative_to(root.resolve()):
        raise ValueError("Calculator patch path escapes installation")
    return target


def apply_calculator_patch(original, definition):
    patch_id = definition.get("id")
    if not isinstance(patch_id, str) or not re.fullmatch(r"[a-z0-9-]+", patch_id):
        raise ValueError("Invalid calculator patch id")
    expected_before = definition.get("original_sha256")
    expected_after = definition.get("patched_sha256")
    if expected_before and sha(original) not in (expected_before, expected_after):
        raise ValueError(f"Unsupported calculator revision for {patch_id}; no files were patched")
    text = original.decode("utf-8")
    newline = "\r\n" if "\r\n" in text else "\n"
    replacements = definition.get("replacements")
    if not isinstance(replacements, list) or not replacements:
        raise ValueError("Calculator patch replacements are missing")
    for replacement in replacements:
        old, new = replacement.get("old"), replacement.get("new")
        if not isinstance(old, str) or not old or not isinstance(new, str):
            raise ValueError("Invalid calculator replacement")
        old, new = old.replace("\n", newline), new.replace("\n", newline)
        if new and text.count(new) == 1:
            continue  # A stock update may already contain the exact fix.
        if text.count(old) != 1:
            raise ValueError(f"Calculator layout is incompatible with {patch_id}; no files were patched")
        text = text.replace(old, new, 1)
    if expected_after and sha(text.encode("utf-8")) != expected_after:
        raise ValueError(f"Calculator patch integrity check failed for {patch_id}")
    marker = f"-- [poe2-mcp calculator patch: {patch_id}]" + newline
    if text.startswith("\ufeff"):
        text = "\ufeff" + marker + text[1:]
    else:
        text = marker + text
    return text.encode("utf-8")


def plan_calculator_patches(install, state, definitions):
    api_dir = install / "API"
    previous = (state or {}).get("calculator_patches", {})
    writes, records, requested = {}, {}, set()
    for definition in definitions:
        relative = definition.get("path")
        target = relative_target(install, relative)
        if relative in requested:
            raise ValueError("Duplicate calculator patch target")
        requested.add(relative)
        current = target.read_bytes()
        record = previous.get(relative)
        if record and sha(current) == record["patched_sha256"]:
            original = relative_target(api_dir, record["original_backup"]).read_bytes()
            if sha(original) != record["original_sha256"]:
                raise ValueError("Calculator original backup failed integrity verification")
        else:
            if b"-- [poe2-mcp calculator patch:" in current:
                raise ValueError(f"Calculator file changed or is unowned: {relative}")
            original = current
        patched = apply_calculator_patch(original, definition)
        backup = "backups/" + relative.replace("/", "_") + "." + sha(original)
        writes[api_dir / backup] = original
        writes[target] = patched
        records[relative] = {"id": definition["id"], "original_backup": backup,
                             "original_sha256": sha(original), "patched_sha256": sha(patched)}
    for relative, record in previous.items():
        if relative in requested:
            continue
        target = relative_target(install, relative)
        if sha(target.read_bytes()) != record["patched_sha256"]:
            raise ValueError(f"Calculator file changed; preserving edits: {relative}")
        original = relative_target(api_dir, record["original_backup"]).read_bytes()
        if sha(original) != record["original_sha256"]:
            raise ValueError("Calculator backup failed integrity verification")
        writes[target] = original
    return writes, records


def load_calculator_patches(path=None):
    path = Path(path) if path else Path(__file__).with_name("poe2_calculator_patches.json")
    if not path.exists():
        raise ValueError(f"Calculator patch manifest is missing: {path}")
    document = json.loads(path.read_text())
    if document.get("schema_version") != 1 or not isinstance(document.get("patches"), list):
        raise ValueError("Unsupported calculator patch manifest")
    return document["patches"]


def install_api(install, source, calculator_patches=None):
    install, source = Path(install), Path(source)
    if not (install / "Path of Building-PoE2.exe").is_file():
        raise ValueError("Expected a Windows Path of Building 2 installation")
    payloads = {name: (source / name).read_bytes() for name in API_FILES}
    main = install / "Modules/Main.lua"
    current = main.read_bytes()
    state = read_state(install)
    api_dir = install / "API"
    if BEGIN.encode() in current:
        if not state or sha(current) != state.get("patched_sha256"):
            raise ValueError("Patched Main.lua changed outside the installer; preserve and review edits first")
        original = (api_dir / state["original_backup"]).read_bytes()
        if sha(original) != state["original_sha256"]:
            raise ValueError("Original Main.lua backup failed integrity verification")
    else:
        original = current
    patched = patch_main(original)
    for name in API_FILES:
        destination = api_dir / name
        if destination.exists():
            expected = (state or {}).get("files", {}).get(name)
            if expected is None or sha(destination.read_bytes()) != expected:
                raise ValueError(f"Refusing to overwrite unowned or modified API file: {name}")
    definitions = load_calculator_patches() if calculator_patches is None else calculator_patches
    calculator_writes, calculator_records = plan_calculator_patches(install, state, definitions)
    backup = f"backups/Main.{sha(original)}.lua"
    next_state = {
        "schema_version": 1, "game": "poe2", "original_backup": backup,
        "original_sha256": sha(original), "patched_sha256": sha(patched),
        "files": {name: sha(data) for name, data in payloads.items()},
        "calculator_patches": calculator_records,
    }
    # Validate all target layouts and backups before writing any file. Main is last.
    writes = {api_dir / backup: original, **calculator_writes}
    writes.update({api_dir / name: data for name, data in payloads.items()})
    writes[api_dir / STATE_NAME] = (json.dumps(next_state, indent=2) + "\n").encode()
    writes[main] = patched
    write_transaction(writes)
    return next_state

def uninstall_api(install):
    install = Path(install)
    state = read_state(install)
    if not state:
        raise ValueError("No owned PoB2 API installation is recorded")
    api_dir = install / "API"
    main = install / "Modules/Main.lua"
    if sha(main.read_bytes()) != state["patched_sha256"]:
        raise ValueError("Main.lua has changed; uninstall will not overwrite later edits")
    original = (api_dir / state["original_backup"]).read_bytes()
    if sha(original) != state["original_sha256"]:
        raise ValueError("Original backup failed integrity verification")
    for name, expected in state["files"].items():
        target = api_dir / name
        if target.exists() and sha(target.read_bytes()) != expected:
            raise ValueError(f"API file changed; preserving later edits: {name}")
    writes = {main: original}
    for relative, record in state.get("calculator_patches", {}).items():
        target = relative_target(install, relative)
        if sha(target.read_bytes()) != record["patched_sha256"]:
            raise ValueError(f"Calculator file changed; preserving later edits: {relative}")
        previous = relative_target(api_dir, record["original_backup"]).read_bytes()
        if sha(previous) != record["original_sha256"]:
            raise ValueError("Calculator original backup failed integrity verification")
        writes[target] = previous
    removals = [api_dir / name for name in state["files"]] + [api_dir / STATE_NAME]
    write_transaction(writes, removals)
    return {"restored": True, "original_sha256": state["original_sha256"]}


def installation_status(install, source=None):
    install = Path(install)
    state = read_state(install)
    result = {"installed": bool(state), "path": str(install), "main_matches": False,
              "api_matches": False, "calculator_matches": False, "mismatched_files": []}
    if not state:
        return result
    def matches(path, expected):
        return path.is_file() and sha(path.read_bytes()) == expected
    result["main_matches"] = matches(install / "Modules/Main.lua", state["patched_sha256"])
    if not result["main_matches"]:
        result["mismatched_files"].append("Modules/Main.lua")
    api_mismatches = [name for name, expected in state["files"].items()
                      if not matches(relative_target(install / "API", name), expected)]
    calculator_mismatches = [name for name, record in state.get("calculator_patches", {}).items()
                             if not matches(relative_target(install, name), record["patched_sha256"])]
    result["api_matches"] = not api_mismatches
    result["calculator_matches"] = not calculator_mismatches
    result["mismatched_files"] += ["API/" + name for name in api_mismatches] + calculator_mismatches
    result["installed_integrity_verified"] = not result["mismatched_files"]
    backups = [(state["original_backup"], state["original_sha256"])] + [
        (record["original_backup"], record["original_sha256"])
        for record in state.get("calculator_patches", {}).values()]
    result["restore_backups_verified"] = all(
        matches(relative_target(install / "API", name), expected) for name, expected in backups)
    if source is not None:
        source = Path(source)
        result["api_matches_source"] = all(
            (source / name).is_file() and state["files"].get(name) == sha((source / name).read_bytes())
            for name in API_FILES)
    return result

def host_path(value):
    if os.name != "nt" and re.match(r"^[A-Za-z]:[\\/]", value):
        return Path("/mnt/" + value[0].lower() + "/" + value[3:].replace("\\", "/"))
    return Path(value)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["install", "uninstall", "status"])
    parser.add_argument("--install-dir", required=True, type=host_path)
    parser.add_argument("--api-source", type=host_path, default=Path(__file__).resolve().parents[1] / "PathOfBuilding/src/API")
    parser.add_argument("--calculator-patches", type=host_path, help="Override the bundled calculator patch manifest")
    args = parser.parse_args()
    if args.action == "install":
        result = install_api(args.install_dir, args.api_source, load_calculator_patches(args.calculator_patches))
        print(json.dumps({"installed": True, "game": result["game"], "path": str(args.install_dir)}))
    elif args.action == "uninstall":
        print(json.dumps(uninstall_api(args.install_dir)))
    else:
        result = installation_status(args.install_dir, args.api_source)
        expected = load_calculator_patches(args.calculator_patches)
        installed = (read_state(args.install_dir) or {}).get("calculator_patches", {})
        pending = []
        for patch in expected:
            record = installed.get(patch["path"])
            try:
                if not record or record.get("id") != patch["id"]:
                    raise ValueError("Patch is not installed")
                original = relative_target(args.install_dir / "API", record["original_backup"]).read_bytes()
                if sha(original) != record["original_sha256"] or sha(apply_calculator_patch(original, patch)) != record["patched_sha256"]:
                    raise ValueError("Patch differs from the current source")
            except (ValueError, OSError):
                pending.append(patch["id"])
        result["pending_calculator_patches"] = pending
        print(json.dumps(result))

if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
