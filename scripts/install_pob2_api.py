"""Install a reversible, opt-in PoB2 TCP API hook. Does not restart PoB."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys

API_FILES = ("BuildOps.lua", "Handlers.lua", "TcpServer.lua", "Server.lua")
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

def install_api(install, source):
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
    backup = f"backups/Main.{sha(original)}.lua"
    next_state = {
        "schema_version": 1, "game": "poe2", "original_backup": backup,
        "original_sha256": sha(original), "patched_sha256": sha(patched),
        "files": {name: sha(data) for name, data in payloads.items()},
    }
    # Validate everything before writing. Main.lua is switched last.
    atomic_write(api_dir / backup, original)
    atomic_write(api_dir / STATE_NAME, (json.dumps(next_state, indent=2) + "\n").encode())
    for name, data in payloads.items():
        atomic_write(api_dir / name, data)
    atomic_write(main, patched)
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
    atomic_write(main, original)
    for name in state["files"]:
        (api_dir / name).unlink(missing_ok=True)
    (api_dir / STATE_NAME).unlink()
    return {"restored": True, "original_sha256": state["original_sha256"]}

def host_path(value):
    if os.name != "nt" and re.match(r"^[A-Za-z]:[\\/]", value):
        return Path("/mnt/" + value[0].lower() + "/" + value[3:].replace("\\", "/"))
    return Path(value)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["install", "uninstall", "status"])
    parser.add_argument("--install-dir", required=True, type=host_path)
    parser.add_argument("--api-source", type=host_path, default=Path(__file__).resolve().parents[1] / "PathOfBuilding/src/API")
    args = parser.parse_args()
    if args.action == "install":
        result = install_api(args.install_dir, args.api_source)
        print(json.dumps({"installed": True, "game": result["game"], "path": str(args.install_dir)}))
    elif args.action == "uninstall":
        print(json.dumps(uninstall_api(args.install_dir)))
    else:
        state = read_state(args.install_dir)
        valid = bool(state) and sha((args.install_dir / "Modules/Main.lua").read_bytes()) == state["patched_sha256"]
        print(json.dumps({"installed": bool(state), "main_matches": valid, "path": str(args.install_dir)}))

if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
