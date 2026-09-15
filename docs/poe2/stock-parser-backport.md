# Stock Runic Ward parser backport

The bundled installer includes this `Modules/ModParser.lua` backport for stock
PoB2 0.23.1. The fixture tests operate entirely in memory; the installer manages
separate byte-preserving backups and validates the patch chain before writing.

## Payload and hash chain

- `tests/poe2/fixtures/stock-parser-backport.json`: exact replacement strings.
- `tests/poe2/fixtures/stock-parser-backport.patch`: diff against the existing
  Ward-cost-patched parser.
- `tests/poe2/test_stock_parser_backport.py`: isolated native LuaJIT verification.

All three replacements are included in the existing `ward-costs-modparser`
manifest target, after the Ward resource fixes. Hashes below cover UTF-8 text
with LF line endings; installer backups retain the original raw bytes.

| State | SHA-256 |
| --- | --- |
| Original stock | `01e2668025f70d0212378f815d10b189484d11c7db6e84e77c08c0e1dd068247` |
| Existing Ward-cost patch | `b48ff91ce387203e36097f305e26548b2dbad4be44ee4fadef1d47f44e327c9c` |
| Costs plus complete parser backport | `d22c07172faf417d80c3d40015feb5bc8f5487e3d18bdb063702fd6a50f81981` |

The complete patch adds `runic ward` and `maximum runic ward` aliases, adds
`as extra maximum runic ward` conversion grammar, and maps the specific phrase
`armour, evasion and energy shield` to those three stats. Shipping the aliases
without that last mapping incorrectly lets Iron Runes and specific global
A/E/ES bonuses increase Ward. The genuine generic `defences` mapping remains.
All three replacements match the current source fork.

## Verified native results

These are isolated PoB2 calculator results, not measurements of game behaviour.
The sanitized body fixture has native base Ward 387 and quality 20.

| Case | Body Ward | Player Ward | Body ES |
| --- | ---: | ---: | ---: |
| Corrected stock or source, normal runes | 557 | 557 without other Ward bonuses | 389 |
| 50% augment effect, printed Ward bonus 30% | 604 | Depends on global bonuses | 405 |
| Specific global 30% Armour/Evasion/ES | 557 | 557 | 389 |
| True global 30% Defences or Ward | 557 | 724 | 389 |

The first two local values are native rounding of `387 * 1.20 * 1.20` and
`387 * 1.30 * 1.20`. Greater Iron Rune removal leaves Ward unchanged. Rune
identities together with printed rune lines, text-only rune inference, and a
native raw-item round trip each apply the rune once.

The optional private snapshot was inspected offline without saving its XML:
old body/player Ward 548/712 became 557/557 with the complete patch. Its 30%
specific A/E/ES quest bonus had previously become generic Defences. Body ES
stayed 389. A separate running PoB2 with the installed backport confirmed the
same item calculation and same-item comparison. Those values describe that
snapshot only. Private build XML is not part of the fixtures.

## Archon and Bonded boundary

`Bonded: Archon recovery period expires 30% faster` remains unparsed in stock
and the current source fork, including the known Hedgewitch Assandra's Rune of
Wisdom identity. The stat description `archon_delay_expires_x%_faster` exists,
but no verified native parser/calculation consumer was found. This patch adds
no dummy mapping and does not change the strict unknown-modifier guard. The
staff scenario must remain rejected unless a separately reviewed evaluator
proves that exact modifier inactive for both baseline and candidate.

Stock and newer source use different Bonded contracts:

- Stock: `Condition:CanUseBondedModifiers`, queried by native
  `GetCondition("CanUseBondedModifiers", cfg)`. Condition evaluation also checks
  the relevant `cfg.skillCond` and honours native condition overrides.
- Newer source: `CanUseBonded`, used while selecting active item rune lists.

Offline inspection of the private stock snapshot found the stock predicate
false for baseline and same-body reparse, including all 15 active-skill configs.
Known Bonded `LifeGainAsWard` contributed zero. An isolated enabling-phrase
control made the predicate true and the known 2% conversion active. This is
evidence for those states, not permission to suppress unknown mods generally
or infer inactivity from the character class. The stock rune line itself has
literal `Bonded:` text; it does not carry the newer source's `bonded` field.

## Portable verification

From the suite root, using the existing environment:

```sh
POB2_STOCK_SOURCE=/path/to/stock/PoB2 .venv/bin/python -m pytest -q tests/poe2/test_stock_parser_backport.py tests/poe2/test_stock_item_ward.py
```

`POB_INSTALL_DIR` is an alternative. With neither variable set, stock cases skip
and source-fork cases still run. No personal absolute path is embedded. The
test accepts original stock, the existing Ward-cost patch, or the final parser
hash; transformations and reverse transformations occur only in memory. It
rejects unknown parser hashes and verifies installation bytes remain unchanged.

Configured verification: **22 passed, 7 skipped**. Without stock environment
configuration: **5 passed, 24 skipped**. The configured skipped combinations
exclude correction-only assertions from intentional negative controls and
exclude the stock-specific condition ABI check from other modes.

The older `test_stock_item_ward.py` and `stock-item-runic-ward.json` now use the
complete three-hunk fixture and portable environment configuration. Expected
normal/augmented body Ward is 557/604; the true 30% global Ward control is 724.
Item comparison and item-granted skill projection have separate native tests.
