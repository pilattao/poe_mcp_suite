# PoE2 port

This branch is an active port of the upstream suite. Full restoration is not yet
verified. A successful tools/list call is not evidence that every tool works.
See [scope](PORT_SCOPE.md), [plan](PLAN.md) and [tool coverage](tool-coverage.json).

## Runtime and configuration

The template `.mcp.json.example` starts three servers. Adapt every path to the
client host: `.venv/Scripts/python.exe` on Windows, `.venv/bin/python` on Linux;
use `/mnt/c/...` paths for Windows files read by a Linux process. Public sources
need no account cookie. The core trade integration is enabled in the template
after native metadata, ordinary searches, fetched listings and currency units
were checked. Anonymous weighted queries currently hit GGG's reported complexity
limit; authenticated weighted execution remains unverified. The separate trade
server also exposes PoE2 trade and economy tools.

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

Full optimizer/handler coverage, real OAuth authorization, protected stash access,
legacy PoE1-only features and complete end-to-end client deployment remain under
review. Unsupported messages are recorded as gaps, never as restored functionality.
The public character source remains the default. The OAuth character client is
implemented and tested offline; no real token or account request was used.
See `poe-trade-mcp/OAUTH_REPORT.md` for exact live-check requirements. Personal evidence and
account/build snapshots stay outside version control.

## Sources

- Native definitions and ABI: installed Path of Building Community (PoE2),
  [upstream source](https://github.com/PathOfBuildingCommunity/PathOfBuilding-PoE2).
- [PoE2 economy](https://poe.ninja/poe2/economy): its PoE2 index-state and
  exchange/stash response schemas were inspected directly on 2026-09-15.
- [PoE2DB](https://poe2db.tw/us/) and [PoE2 Wiki](https://www.poe2wiki.net/wiki/Path_of_Exile_2_Wiki).

## Previous published checkpoint (2026-09-15)

- TypeScript: 943 passed, 39 skipped; a separate opt-in native/live selection
  passed 18 checks. Skipped cases are not counted as restored capabilities.
- Python: 92 Lua/installer/source checks, 54 data-server checks, 74 trade/OAuth checks.
- All 1,074 checked-out PoB2 Lua files compile with stock LuaJIT. Source/release
  fixture differences are explicit. The fork normalizes source syntax without
  changing the tested native calculator's numerical behavior.
- API 1.2 confirms queued build opens by request ID. Eight native PoE2
  class/ascendancy creation pairs and restoration to the original test build passed.
- Live config reads/writes, zero values, rejected batches and game-scoped preset
  patches passed through MCP, followed by restoring XML/config/stats.
- PoE2 atlas: RePoE export version 4.5.5.2, 575 nodes, 586 edges and seven components.
  Paths describe graph distance; selector effects and actual allocation remain unknown.
- Core crafting: plain one-step exalt/augment/regal estimates from a validated CoE
  cache. PoB2 eligibility flags are never used as probability weights. Repeated
  attempts, costs, special effects and unsupported operations remain unmodeled.
- Context usage now requires an explicit client/session source; no automatic
  history scanning. Recorded token usage is separate from current context occupancy.

A clean remote clone resolved every updated submodule, installed Python
requirements and built TypeScript. The same 943 TypeScript and 220 Python tests
passed there. This establishes reproducible setup for the verified checkpoint;
it does not close the remaining per-tool and external-access gaps.

## Current verified checkpoint: API 1.3

- [Native gem evaluation](NATIVE_GEM_EVALUATION.md): six native cases passed,
  including a 48-trial support search and independent rollback checks.
- Core MCP gem comparison, support ranking, leveling, shopping and budget planning
  passed against the dedicated runtime with full XML/stat/skill/config preservation.
- Currency valuations use actual source denominations and explicit conversion.
  Ordinary trade searches, query-bound listing comparisons, metadata and invalid
  PoE1-filter rejection passed through the configured Windows-to-WSL launcher.
- Shopping uses actual selected sets, rune/skill separation, explicit budgets and
  live listings. Armour Spirit is a flat modifier constraint; weapon Spirit is a
  displayed property. The two must not share an unconditional equipment filter.
- Defense reports read actual hybrid pools and native configuration. Leveling
  uses PoE2 class, gem and campaign definitions. Crafting uses native modifier
  eligibility, sourced operations and supported conditional CoE probabilities.
- Budget planning allocates observed candidates within an explicit purchase
  allowance. Whole-build replacement outcomes and complete item evaluation are
  still under development; possessions are not assigned invented prices.

The remaining full-port gaps still apply. In particular, aggregate currency
valuations do not establish executable arbitrage, anonymous weighted search is
limited by the source, and authenticated account access remains unverified.

The published code checkpoint `0f250bf` was checked out from the remote in a
clean verification clone. It resolved all submodules, installed the Node lockfile,
built TypeScript and passed **1,251 TypeScript tests (54 skipped)**,
**121 Lua/installer/source tests**, **54 data-server tests**, and
**74 trade/OAuth tests**. Python dependency validation passed. Skipped tests and
remaining external-access gaps are not counted as restored capabilities.

Pinned code: core `01ac3b3`, native API `722f09a`. Subsequent documentation-only
updates do not change that tested code state.
