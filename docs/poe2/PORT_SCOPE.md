# PoE2 port — scope and acceptance

## User objective

Restore the full functionality of charleslucas/poe_mcp_suite in Path of Exile 2, preferably through forks, using the user's PoB2 installation and build directory. A working XML reader alone, a reduced tool subset, or successful mocked tests do not satisfy the goal.

## Target environment

- PoB2: %APPDATA%/Path of Building Community (PoE2)
- Builds root: %USERPROFILE%/Documents/Path of Building (PoE2)
- XML files are under the Builds child directory.
- Development workspace: the suite checkout
- WSL can access both through /mnt/c; Windows Node is available.
- Current game context: PoE2, Forbidden Rites, 0.5.5b.
- Public character snapshots from poe.ninja are accepted with explicit source age.

## Required outcome

1. Reproducible fork/branches with reachable submodule commits and installation instructions.
2. File tools correctly read, preserve and write PathOfBuilding2 XML, including item sets, both weapon specialisations, independent gem/support groups, charms, runes and passive overrides.
3. PoB2 calculation backend: real live stats, configuration, items/gems/tree mutations and A/B simulations, with full rollback verified on test builds. Calculated changes must come from the real PoB2 engine.
4. Full tool inventory reconciled with actual MCP tools/list and router handlers. Initial source scan identifies at least 195 schemas/functions: 135 pob, 34 trade, 26 data. No silent missing tools or accidental registration omissions.
5. PoE2 sources for skill/tree/item/crafting data, wiki, prices, league selection, market queries and character imports. No silent fallback to PoE1.
6. Stash, inventory, authorisation and protected operations evaluated against the actual PoE2 API surface. Missing external access remains an explicit incomplete verification item; a fabricated empty result or stub is not a pass.
7. Loot filters, snapshots, exports, profile constraints, character cache, watchers and comparison workflows operate against the correct game and paths.
8. Every game-specific upstream feature gets an explicit semantic audit. Genuine PoE1-only concepts must be identified and mapped to an actual PoE2 counterpart where one exists. Returning unsupported does not count as restored functionality.
9. User-facing installation/configuration works in this Windows/WSL setup. Existing user builds and credentials remain intact. Secrets and personal data never enter published forks.
10. Unit tests, contract tests, real PoB2 integration and representative live source checks, with evidence per capability in tool-coverage.json and explicit remaining gaps.

## Working rules

Use the current installed PoB2 as the integration target, and a PoB2 source fork for the portable calculation backend. The old PoB1 API supplies adapter code only. First validate patches against a separate runtime/test build; do not close the running user PoB or overwrite their open build. Maintain reversible install/uninstall and backup checks.

Trade/crafting changes must be driven by PoE2 definitions, not endpoint-string replacement alone. Respect source rate limits. Do not collect existing application credentials as a shortcut; request required access only after a concrete integration needs it.

## Completion gate

The active goal remains open until each item above is demonstrated by current evidence. Source checks, skipped tests and documentation updates are progress but not full completion.
