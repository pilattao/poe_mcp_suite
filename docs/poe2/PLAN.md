# PoE2 Suite Implementation Plan

**Goal:** Restore the complete suite for PoE2 with the actual PoB2 engine and reproducible local installation.

**Architecture:** Preserve independent MCP servers. Introduce shared game/profile and filesystem boundaries; port the Lua API to PoB2; use installed PoB2 data for local lookups and explicit PoE2 remote sources. Keep per-tool evidence rather than counting imports as functionality.

**Tech stack:** TypeScript/Node MCP, Python MCP, Lua PoB2 API, Windows PoB2 GUI, WSL development.

**Spec:** PORT_SCOPE.md.

## Global constraints

All ten acceptance requirements in PORT_SCOPE.md apply to each task. Work is already authorised by the user's full-port goal. Preserve existing builds and do destructive simulations only on dedicated test copies.

## 1. File and local data contracts

Files: pob-mcp/src/services/buildService.ts, src/utils/pathSanitizer.ts, src/services/pobTreeDataLoader.ts, src/types.ts; corresponding tests/unit.

- [ ] Test a real-shaped PathOfBuilding2 fixture with independent SkillSet/ItemSet, two weapons, charms, runes and WeaponSet1/2 node lists. Assert selected groups and round-trip retention.
- [ ] Test extensionless build names, .xml suffix, nested paths, Windows separators and traversal rejection.
- [ ] Introduce a shared XML root reader used by all handlers, retaining the original game root on writes.
- [ ] Resolve installed root and source root layouts; normalize PoB2 connections and explicit numeric Lua tables to usable arrays.
- [ ] Assert the real installed 0_5 tree finds existing character nodes and paths; never select PoE1 tree as fallback.
- [ ] Run baseline regressions and new contract tests; commit this independently.

## 2. Real PoB2 backend

Files: PathOfBuilding/src/API/{BuildOps,Handlers,TcpServer,Server}.lua, installer/launcher scripts and pob-mcp/src/pobLuaBridge.ts.

- [ ] Fork PoB2 source and graft the adapter with upstream provenance.
- [ ] Compare every adapter call signature to installed PoB2 classes (especially ImportFromNodeList, character import, skills, item slots and allocation counts).
- [ ] Add a reversible parameterized installer supporting the supplied path and source/install directory layouts.
- [ ] Start an isolated API-enabled PoB2 instance on a dedicated loopback port; verify ping, version, read build and calculated stats.
- [ ] Exercise item, gem, config, level and weapon-specialisation changes; restore and compare complete original XML and calculated baseline.
- [ ] Verify error recovery, timeouts, reconnect, backup/uninstall and update behaviour.

## 3. PoB handlers and simulations

Files: pob-mcp/src/handlers/*, services/*, server/{toolSchemas,toolRouter,toolGate}.ts.

- [ ] Reconcile actual registrations with tool-coverage.json; add per-handler acceptance cases.
- [ ] Remove PoE1 assumptions from character classes, flasks, support categories, passives, jewels, damage/defence reports and quest configuration.
- [ ] Use live state for live tools and preserve separate skill/item/tree sets in both backends.
- [ ] Verify each optimizer against actual PoB2 recalculation and exact rollback.
- [ ] Audit upstream bugs listed in ISSUES.md; add regression evidence.

## 4. Data and economy server

Files: poe-data-mcp/poe_data_mcp/sources/* and server.py.

- [ ] Add explicit game/league/source selection and installed PoB2 data path.
- [ ] Test gems, supports, uniques, base items, mods, trees, atlas and crafting using PoE2 exemplars.
- [ ] Port PoB parsing and comparisons to PathOfBuilding2.
- [ ] Test prices and currencies against supported PoE2 economy responses and selected league.
- [ ] Preserve research utilities; verify MCP startup and tools/list covers all intended functions.

## 5. Trade, character, stash and filters

Files: poe-trade-mcp/{poe_lib,poe_char,poe_trade,poe_market,poe_pricer,poe_stash,rare_scorer,poe_filter,poe_oauth,poe_all}.py.

- [ ] Test PoE2 query schemas, item categories, stat IDs, currency units, realm and league selection.
- [ ] Integrate the already-working public character browser export as a dated snapshot source; preserve official OAuth character access as a separate source.
- [ ] Validate protected inventory/stash paths against current official capability; identify exact access requirements before asking the user.
- [ ] Port local scorer and cache schemas to PoE2 items.
- [ ] Round-trip PoE2 loot filters and exercise all editing operations on test files.
- [ ] Surface registration/import errors instead of silently dropping modules.

## 6. Install, forks and complete acceptance

Files: config examples, INSTALL.md, TOOLS.md, playbooks, verification scripts, tool-coverage.json.

- [ ] Configure all servers for the user's Windows/WSL paths, correct game and league.
- [ ] Verify actual MCP protocol discovery/calls; compare inventory names with source and router coverage.
- [ ] Run representative end-to-end workflows through MCP: import → analyse → simulate → revert → price/search → export.
- [ ] Push child fork commits before suite pointers; verify a clean clone can reproduce setup.
- [ ] Complete requirement-by-requirement audit; keep goal active for every missing or unverified capability.
