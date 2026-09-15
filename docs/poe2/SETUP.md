# PoE2 setup

This branch is an active port. Use the [coverage inventory](tool-coverage.json)
and [verified checkpoints](README.md) for current limits.

## Install the repository

From Linux or Ubuntu WSL with Python 3.10+ and Node.js 20+:

```sh
git clone --branch poe2-port --recurse-submodules https://github.com/pilattao/poe_mcp_suite.git
cd poe_mcp_suite
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt -r poe-trade-mcp/requirements-character.txt
npm ci --prefix pob-mcp
npm run build --prefix pob-mcp
.venv/bin/python -m pip check
```

The character reader additionally needs Chromium/Chrome. Set `POE2_CHROME_PATH`
to an existing browser, or install the Playwright Chromium browser. Public
poe.ninja character snapshots and ordinary trade queries need no account cookie.

## Choose the calculation runtime

Use a separate portable PoB2 installation first. A portable copy keeps its user
settings/builds in its own directory; copying an installed folder together with
`installed.cfg` can instead select the normal user's document directory.
The API installer itself does not start, close or select a build.

```sh
.venv/bin/python scripts/install_pob2_api.py install --install-dir '<portable PoB2 directory>'
.venv/bin/python scripts/install_pob2_api.py status --install-dir '<portable PoB2 directory>'
```

Start that PoB2 process with `POB_API_TCP=1` and an unused
`POB_API_TCP_PORT`. Configure the same port in the MCP client. The listener
is loopback-only. Use `POB_INSTALL_DIR` for this same runtime's definitions,
including its installed calculator fixes. `POB_DIRECTORY` is the directory of
build XML files, normally the `Builds` child of the PoB2 documents directory.

Installation records hashes and backs up original bytes. The bundled calculator
manifest currently supplies the verified stock Ward backport and quest-choice
whitespace fix. A matching displayed version number alone does not prove patch
compatibility: unsupported hashes/layouts fail before writes. Status separates
installed-file integrity, backup integrity and whether the current source matches.

```sh
.venv/bin/python scripts/install_pob2_api.py uninstall --install-dir '<portable PoB2 directory>'
```

Uninstall restores owned calculator files and Main.lua; later edits are preserved
by refusing to overwrite changed files. The installer also rolls back a caught
write failure. Keep the original backup files until the installation is removed.

## Configure a client

Start with `.mcp.json.example`. The three servers are independent:

- `pob-mcp/build/index.js` — native and saved builds, calculations, trade and plans.
- `poe-trade-mcp/poe_all.py` — characters, prices, trade and local filters.
- `poe-data-mcp/server.py` — native definitions, wiki and crafting sources.

Set `POE_GAME=poe2` and an explicit league. Concurrent leagues are separate.
Use `POE_NINJA_LEAGUE_SLUG` only where a URL slug is needed. Keep the exact league
name in market tool arguments. For local filter work, set `POE_FILTER_PATH` to an
explicit working `.filter` file; creation tools require an explicit output path.

For a Windows client starting servers in Ubuntu WSL, use `wsl.exe` with arguments
`-d Ubuntu --cd <Linux suite path> --exec <Linux executable> <Linux server path>`.
Forward each configured environment key through `WSLENV`. Use `/mnt/c/...` for
Windows files that the Linux process reads. A successful direct STDIO handshake
is separate from the desktop client loading the configuration into its tool list.

Codex project settings live in `.codex/config.toml` in a trusted project. After
changing servers, use the client's MCP restart/refresh and verify its tool list.
See [official MCP setup](https://learn.chatgpt.com/docs/extend/mcp?surface=cli).

## Verification and external access

Native probes run on explicitly selected disposable builds. Gem and item/tree
comparisons require their own state-preservation evidence; passing a data lookup
or listing the tools does not verify every calculation.

GGG currently documents account/public/guild stash endpoints as PoE1-only.
Authenticated character access has a separate OAuth workflow; live authorization
remains unverified. Anonymous weighted queries may hit the reported complexity
limit. Bulk quotations describe advertised offers, quantities and gross scenarios,
not completed fills or guaranteed net profit.
