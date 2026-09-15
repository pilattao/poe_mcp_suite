"""Offline timing/RSS probe for the real TreeEvaluator; no GUI/API connection."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import statistics
import time
from item_evaluator_runtime import runtime, table, SOURCE

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--private-xml')
parser.add_argument('--calls', type=int, default=24)
parser.add_argument('--output', required=True)
args = parser.parse_args()
lua = runtime(quiet=True)
os.chdir(SOURCE)
api = lua.execute((SOURCE / 'API/BuildOps.lua').read_text())
if args.private_xml:
    lua.globals().treeBenchXml = Path(args.private_xml).read_text()
    lua.execute("main:SetMode('BUILD',false,'Offline tree benchmark',treeBenchXml);main:OnFrame({});build=main.modes.BUILD")
    node = lua.eval("(function() for id,n in pairs(build.spec.allocNodes) do if n.isAttribute and n.dn=='Intelligence' and (n.allocMode or 0)==0 then return id end end end)()")
    proposal = {'addNodes': [], 'attributeOverrides': {str(node): 'str'}}
else:
    group = api.create_socket_group(table(lua, {'label': 'Benchmark Spark', 'includeInFullDPS': True, 'count': 3}))
    assert not isinstance(group, tuple), group
    lua.globals().treeBenchGroup = group['index']
    assert not isinstance(api.add_gem(lua.eval('{groupIndex=treeBenchGroup,gemName="Spark",level=1}')), tuple)
    lua.execute('build.mainSocketGroup=treeBenchGroup;build.calcsTab:BuildOutput()')
    ids = lua.eval("(function() local r={} for _,n in ipairs(build.spec.nodes[1140].path) do if not n.alloc then r[#r+1]=n.id end end return r end)()")
    node = 1140
    proposal = {'addNodes': list(ids.values()), 'attributeOverrides': {'1140': 'int'}}
expected = lua.eval("build:SaveDB('tree-benchmark')")
name = lua.eval('build.buildName')
peak_before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
heap_before = lua.eval("collectgarbage('count')")
rows = []
for i in range(args.calls):
    weapon = i % 2 + 1
    params = {**proposal, 'weaponSet': weapon, 'useFullDPS': True, 'expectedBuildName': name, 'expectedXml': expected}
    params['attributeOverrides'] = {str(node): ['str', 'dex', 'int'][(i // 2) % 3]}
    started, cpu = time.perf_counter(), time.process_time()
    result = api.calc_with(table(lua, params))
    elapsed, used_cpu = time.perf_counter() - started, time.process_time() - cpu
    assert isinstance(result, tuple) and result[0] is not None, result
    assert result[0]['calculationContext']['weaponSet'] == weapon
    row = {'call': i + 1, 'weaponSet': weapon, 'wallSeconds': elapsed, 'cpuSeconds': used_cpu,
           'processPeakRssMiB': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
           'luaHeapAfterMiB': lua.eval("collectgarbage('count')") / 1024}
    rows.append(row)
    if (i + 1) % 6 == 0:
        print(json.dumps({'progress': i + 1, 'calls': args.calls, 'lastWallSeconds': elapsed, 'processPeakRssMiB': row['processPeakRssMiB']}), flush=True)
after = lua.eval("build:SaveDB('tree-benchmark')")
assert after == expected, 'Native serialized build changed'
report = {'fixture': 'private-source-build' if args.private_xml else 'native-Spark-fixture',
          'requests': rows, 'callCount': len(rows), 'totalWallSeconds': sum(r['wallSeconds'] for r in rows),
          'medianWallSeconds': statistics.median(r['wallSeconds'] for r in rows),
          'maxWallSeconds': max(r['wallSeconds'] for r in rows),
          'medianCpuSeconds': statistics.median(r['cpuSeconds'] for r in rows),
          'processPeakBeforeMiB': peak_before / 1024,
          'processPeakRssMiB': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
          'luaHeapBeforeMiB': heap_before / 1024, 'luaHeapAfterMiB': lua.eval("collectgarbage('count')") / 1024,
          'serializedBuildUnchanged': after == expected, 'snapshotSha256': hashlib.sha256(expected.encode()).hexdigest(),
          'notes': ['Headless source runtime; process RSS includes Python, LuaJIT, loaded data, graph audit and detached copies.',
                    'No native GUI memory measured. Existing GUI history and system load can increase memory and latency.',
                    'Each request retains snapshot validation, baseline and BOTH candidate weapon calculations; useFullDPS is enabled.',
                    '15-second calculation-work budget; restoration is unconditional and needs transport headroom.']}
Path(args.output).write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps({k: v for k, v in report.items() if k not in ['requests', 'notes']}), flush=True)
