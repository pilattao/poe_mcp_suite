# Native PoE2 gem evaluation

API 1.3 adds `evaluate_gem_setups`. The core MCP exposes it through
`compare_gem_setups`, `suggest_support_gems` and `find_optimal_links`.
Comparisons use PoB2 calculations on the selected loaded build. They do not
reload a requested file over an unrelated or unsaved build.

## Inputs and preservation

- The native request binds to the build name, exact exported XML, skill-set ID
  and one-based group index. MCP group indexes are zero-based.
- Explicit setups can retain a gem with `refIndex`, change its level/quality,
  or use a native gem identity. Global/weapon selections and stat sets remain
  attached to retained gems. Item-granted active skills are preserved.
- An optional evaluation group measures another skill while changing the target
  group. This does not change the actual weapon-set selection.
- Native skill snapshots are restored after valid trials, incompatible supports,
  invalid inputs and calculation failures. Returned results require verified
  XML, numerical output, selection and undo-history preservation.
- Native processing can modify shared raw-skill cost records; the adapter restores
  those records as well. A regression test covers this side effect.
- Support search is bounded. It reports the evaluated count, eligible candidates,
  chosen metric, configuration and truncation. A result is the best evaluated
  setup, not proof of the global optimum. Market prices are a separate input.

## Reproducing the native checks

Use a disposable portable PoB2 instance with API 1.3 installed. Keep the user's
original application and saved builds separate. The probe itself does not load,
restart or save PoB. Prepare the selected test build in weapon set 2 first.

```sh
.venv/bin/python tests/poe2/probe_native_gem_evaluator.py --plan --port 55698
.venv/bin/python tests/poe2/probe_native_gem_evaluator.py --run-native --port 55698 --include-search
```

The probe requires a build containing Spark, Powered by Verisium and item-granted
Lightning Bolt. It discovers group indexes or accepts explicit overrides. Each
case independently compares the exported XML, stats, config and skill selection
before and after evaluation. The API additionally verifies native undo history.

## Verified on 2026-09-15

Native target: PoB2 0.23.1, API 1.3, separate portable runtime. Six cases passed:

| Case | Result |
|---|---|
| Spark level 20 to 19 | Native CombinedDPS changed from 10,723.0680 to 9,587.8788 in the test configuration |
| Verisium 18 to 19, measuring Lightning Bolt | Both setups calculated; Bolt output unchanged |
| Verisium 18 to 19, measuring Spark | Both setups calculated; Spark output unchanged |
| Item-granted Bolt with Cooldown Recovery II | Native support applied; state restored |
| Invalid gem followed by the original setup | Invalid trial rejected; subsequent original output unchanged |
| Bounded Spark support search | 48 trials completed, 220 eligible candidates, truncation reported |

All six passed independent preservation checks. Explicit trials took about
0.5–0.7 seconds per case; the bounded search took about 2.9 seconds. The outer
integration check restored the original primary weapon set, semantic XML and all
baseline numerical stats. Map serialization order may change across a process
restart; values and memberships may not.

The same deployment also passed core MCP gem comparison and support ranking,
with independent full XML/stat/skill/config preservation across the workflow.

## Limits of these results

These figures describe the disposable test configuration, not current gameplay.
PoB's static calculations did not model a DPS gain from increasing the infusion
supply in the Verisium case. Do not turn that zero delta into a claim that the
upgrade has no in-game benefit. Projectile overlap, infusion uptime, enemy
movement and similar conditions need separate evidence.

Private account snapshots and raw native logs are kept outside the published
repository. Unit tests use synthetic records; the opt-in probe can reproduce the
native contracts on another suitable build.
