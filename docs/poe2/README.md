# PoE2 port

This branch is an active port of the upstream suite. Full restoration is not yet
verified. A successful tools/list call is not evidence that every tool works.
See [scope](PORT_SCOPE.md), [plan](PLAN.md) and [tool coverage](tool-coverage.json).

## Runtime and configuration

The template `.mcp.json.example` starts three servers. Adapt every path to the
client host: `.venv/Scripts/python.exe` on Windows, `.venv/bin/python` on Linux;
use `/mnt/c/...` paths for Windows files read by a Linux process. Public sources
need no account cookie. The core server's older trade integration remains disabled
in the template while its game-specific handlers are audited; the separately
ported trade server exposes trade and economy tools. This is an explicit gap.

Use Python 3.10+ with MCP SDK 1.x (`mcp>=1.26,<2`) and Node.js 20+.
MCP SDK 2 renamed FastMCP and changed low-level registration APIs, so an unbounded
`pip install mcp` is not compatible with these servers.

- Install Python dependencies in a project virtual environment.
- Install `poe-data-mcp` in editable mode; its local data reader requires `lupa`.
- For public browser character snapshots, install
  `poe-trade-mcp/requirements-character.txt` and a Chromium browser;
  `POE2_CHROME_PATH` can select an existing Chrome installation.
- Install/build `pob-mcp` with `npm ci` and `npm run build`.
- Set `POE_GAME=poe2` and `POE_LEAGUE` explicitly. Concurrent leagues are not
  interchangeable. League names and poe.ninja URL slugs are separate fields.
- Set `POB_INSTALL_DIR` to the complete PoB2 installation. Both the installed
  `Data/` and source `src/Data/` layouts are supported by the player data reader.
- Set `POB_DIRECTORY` to the directory containing the build XML files. A standard
  installation stores them in the `Builds` child directory of the user's PoB2
  documents directory.
- `POB_MAX_RESPONSE_CHARS=0` disables the core server's legacy output truncation.

## Optional native calculation API

First test in an isolated portable copy of PoB2 with its own settings/builds.
The API installer never restarts PoB or changes the selected build itself:

```text
python scripts/install_pob2_api.py install --install-dir "<PoB2 directory>"
python scripts/install_pob2_api.py status --install-dir "<PoB2 directory>"
python scripts/install_pob2_api.py uninstall --install-dir "<PoB2 directory>"
```

The installer backs up Main.lua and records hashes for exact rollback. Later
user edits are preserved rather than overwritten. Run it again after PoB2 updates.
Start the chosen PoB2 instance with `POB_API_TCP=1`; set `POB_API_TCP_PORT` to the
same loopback port in both PoB2 and the MCP client. Default: 59166. Choose another
free port if needed. The API remains bound to 127.0.0.1.

## Demonstrated in this port

- PoB2 XML preservation across file round trips, independent item/skill sets,
  charms, jewels and both weapon specialisations.
- Real installed PoB2 0.23.1: native stats/tree/XML reads; same-tree round trip,
  level mutation and exact rollback on a dedicated test build.
- PoE2 0_5 passive accounting with shared/per-weapon point budgets and free
  ascendancy nodes. Quest completion and unobserved extra points remain explicit.
- Player definitions from installed PoB2; unique variants remain separate.
- PoE2DB gem tooltips; PoE2 wiki article and Cargo reads.
- Actual PoE2 exchange and stash economy schemas, including unique prices.
  `primaryValue` is measured in `core.primary`; conversions use `core.rates`
  from that same response. Exchange volume is not a listing count.
- Complete response transmission across partial non-blocking writes in the
  Lua transport contract test (600 KB) and the native runtime (650 KB XML).
- Real Spark-level/configuration/item/charm changes, rejected invalid config
  batch, and complete semantic XML plus numeric-stat rollback.
  `scripts/verify_pob2_api.py` reproduces this on an explicitly named disposable
  build. Serialized map order and encoded tree-node order are canonicalized;
  values and decoded tree-link contents must remain identical.

## Limitations under active work

Full handler/mutation/optimizer coverage, protected account APIs, PoE2-only
crafting semantics, legacy PoE1-only features, atlas sources, full installation
flow and a clean-clone acceptance run are not yet complete. Unsupported messages
are recorded as gaps, never as restored functionality. Personal evidence and
account/build snapshots stay outside version control.

## Sources

- Native definitions and ABI: installed Path of Building Community (PoE2),
  [upstream source](https://github.com/PathOfBuildingCommunity/PathOfBuilding-PoE2).
- [PoE2 economy](https://poe.ninja/poe2/economy): its PoE2 index-state and
  exchange/stash response schemas were inspected directly on 2026-09-15.
- [PoE2DB](https://poe2db.tw/us/) and [PoE2 Wiki](https://www.poe2wiki.net/wiki/Path_of_Exile_2_Wiki).
