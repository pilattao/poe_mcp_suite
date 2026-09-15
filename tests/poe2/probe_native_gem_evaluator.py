#!/usr/bin/env python3
"""Parent-only opt-in A/B probe against an already deployed owned PoB2 runtime.

This never starts/restarts PoB, loads a build, commits an edit, or writes XML.
--plan performs discovery reads only. --run-native authorizes temporary native
scenario evaluation; API 1.3/nativeGemEvaluation and weapon set 2 are required.
Example (run by parent after rollout):
  .venv/bin/python tests/poe2/probe_native_gem_evaluator.py --run-native --port 55698
Add --include-search to exercise the 48-trial bounded support search.
"""
import argparse
import copy
import hashlib
import json
import math
import socket
import sys
import time
import xml.etree.ElementTree as ET

METRICS = ['CombinedDPS', 'TotalDPS', 'FullDPS', 'MinionCombinedDPS', 'Life', 'EnergyShield',
           'Mana', 'Spirit', 'SpiritUnreserved', 'ManaCost', 'LifeCost', 'ESCost', 'TotalEHP',
           'Armour', 'Evasion', 'CharmLimit', 'FireResist', 'ColdResist', 'LightningResist', 'ChaosResist']


def digest(value):
    data = value if isinstance(value, str) else json.dumps(value, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(data.encode()).hexdigest()


class Api:
    def __init__(self, host, port, timeout):
        self.connection = socket.create_connection((host, port), timeout=timeout)
        self.connection.settimeout(timeout)
        self.stream = self.connection.makefile('rb')
        ready = self._read()
        if not ready.get('ready'):
            raise RuntimeError('Native API did not send a ready banner')

    def _read(self):
        line = self.stream.readline()
        if not line:
            raise RuntimeError('Native API closed the connection')
        return json.loads(line)

    def request(self, action, params=None):
        self.connection.sendall((json.dumps({'action': action, 'params': params or {}}) + '\n').encode())
        return self._read()

    def read(self, action, key, params=None):
        response = self.request(action, params)
        if not response.get('ok'):
            raise RuntimeError(f'{action}: {response.get("error", "native failure")}')
        return response[key]

    def close(self):
        self.stream.close()
        self.connection.close()


def weapon_set_two(xml):
    root = ET.fromstring(xml)
    if root.tag != 'PathOfBuilding2':
        raise RuntimeError('Current build is not PoE2')
    items = root.find('Items')
    if items is None:
        return False
    selected_id = items.get('activeItemSet')
    sets = items.findall('ItemSet')
    selected = next((s for s in sets if s.get('id') == selected_id), None)
    if selected is None and len(sets) == 1:
        selected = sets[0]
    return selected is not None and selected.get('useSecondWeaponSet') == 'true'


def snapshot(api):
    # Export forces native outputs to be current before snapshot validation.
    xml = api.read('export_build_xml', 'xml')
    return {'xml': xml, 'stats': api.read('get_stats', 'stats', {'fields': METRICS}),
            'config': api.read('get_config', 'config'), 'skills': api.read('get_skills', 'skills'),
            'info': api.read('get_build_info', 'info')}


def assert_unchanged(before, after, label):
    changed = [key for key in before if before[key] != after[key]]
    if changed:
        # Do not dump private XML or try to reload it (which would lose undo).
        raise RuntimeError(f'{label}: rollback mismatch in {changed}; XML hashes '
                           f'{digest(before["xml"])} -> {digest(after["xml"])}. Stop and inspect owned runtime.')


def locate(skills, skill_id, generated=False, explicit=None):
    found = []
    for group in skills.get('groups', []):
        if group.get('enabled') is False or bool(group.get('source')) != generated:
            continue
        if explicit is not None and group['index'] != explicit:
            continue
        for gem in group.get('gems', []):
            if gem.get('skillId') == skill_id and gem.get('enabled') is not False:
                found.append((group, gem))
    if len(found) != 1:
        raise RuntimeError(f'Expected one {skill_id} (generated={generated}); found groups '
                           f'{[g["index"] for g, _ in found]}. Use the explicit group flags.')
    return found[0]


def references(group):
    return [{'refIndex': gem['index']} for gem in group.get('gems', [])]


def build_cases(skills, explicit=None):
    explicit = explicit or {}
    spark, spark_gem = locate(skills, 'SparkPlayer', explicit=explicit.get('spark'))
    power, power_gem = locate(skills, 'PoweredByVerisiumPlayer', explicit=explicit.get('verisium'))
    bolt, _ = locate(skills, 'UniqueBreachLightningBoltPlayer', explicit=explicit.get('bolt'))
    item_bolt, item_gem = locate(skills, 'UniqueBreachLightningBoltPlayer', generated=True, explicit=explicit.get('item_bolt'))
    if spark_gem['level'] != 20 or power_gem['level'] != 18:
        raise RuntimeError('Probe requires current Spark level 20 and Powered by Verisium level 18; no levels were changed')
    candidates = [g for g in bolt['gems'] if g.get('is_support') and g.get('enabled') is not False]
    support = next((g for g in candidates if g['name'] == 'Cooldown Recovery II'), candidates[0] if candidates else None)
    if not support or not support.get('gemId'):
        raise RuntimeError('Configured Lightning Bolt group has no support gem ID to test')
    cases = []

    def level_case(name, group, gem, level, evaluation_group):
        before = references(group)
        after = copy.deepcopy(before)
        next(g for g in after if g['refIndex'] == gem['index'])['level'] = level
        cases.append({'name': name, 'params': {'groupIndex': group['index'], 'evaluationGroupIndex': evaluation_group,
            'metric': 'CombinedDPS', 'setups': [{'name': 'Current', 'gems': before}, {'name': name, 'gems': after}]}})

    level_case('Spark 20 -> 19', spark, spark_gem, 19, spark['index'])
    level_case('Verisium 18 -> 19; Bolt output', power, power_gem, 19, bolt['index'])
    level_case('Verisium 18 -> 19; Spark output', power, power_gem, 19, spark['index'])
    cases.append({'name': 'Item-granted Lightning Bolt support', 'params': {'groupIndex': item_bolt['index'],
        'evaluationGroupIndex': item_bolt['index'], 'metric': 'CombinedDPS', 'setups': [
            {'name': 'Original item skill', 'gems': references(item_bolt)},
            {'name': f'Item skill + {support["name"]}', 'gems': references(item_bolt) + [{'gemId': support['gemId']}]}]}})
    cases.append({'name': 'Invalid setup then original Spark', 'invalid_first': True,
        'params': {'groupIndex': spark['index'], 'metric': 'CombinedDPS', 'setups': [
            {'name': 'Invalid gem', 'gems': references(spark) + [{'gemId': '__InvalidGemEvaluatorProbe__'}]},
            {'name': 'Original after error', 'gems': references(spark)}]}})
    indices = {'spark': spark['index'], 'verisium': power['index'], 'bolt': bolt['index'],
               'item_bolt': item_bolt['index'], 'source_gem_index': item_gem['index'],
               'support_id': support['gemId'], 'skill_set_id': skills['activeSkillSetId']}
    return cases, indices


def run_case(api, before, case):
    params = {**case['params'], 'expectedBuildName': before['info']['name'],
              'expectedXml': before['xml'], 'skillSetId': before['skills']['activeSkillSetId']}
    started = time.monotonic()
    response = api.request('evaluate_gem_setups', params)
    elapsed = time.monotonic() - started
    # Independently check state even if the evaluator rejects the case.
    after = snapshot(api)
    assert_unchanged(before, after, case['name'])
    if not response.get('ok'):
        raise RuntimeError(f'{case["name"]}: {response.get("error")}')
    result = response['result']
    proof = result.get('rollback', {})
    if not all(proof.get(k) is True for k in ['xmlUnchanged', 'statsUnchanged', 'selectionsUnchanged', 'undoUnchanged']):
        raise RuntimeError(f'{case["name"]}: missing native rollback proof')
    rows = result.get('setups', [])
    if 'setups' in params and len(rows) != len(params['setups']):
        raise RuntimeError(f'{case["name"]}: incomplete native setup evaluation')
    for index, row in enumerate(rows):
        if case.get('invalid_first') and index == 0:
            if not row.get('error') or row.get('valid') is not False:
                raise RuntimeError('Invalid gem setup was not rejected')
            continue
        if row.get('error') and 'search' in params:
            continue
        if row.get('error'):
            raise RuntimeError(f'{case["name"]}: {row["error"]}')
        value = row.get('output', {}).get(result['metric'])
        if not isinstance(value, (int, float)) or not math.isfinite(value):
            raise RuntimeError(f'{case["name"]}: native metric missing or nonfinite')
    if case.get('invalid_first'):
        if rows[1]['deltas'][result['metric']]['absolute'] != 0:
            raise RuntimeError('Invalid setup contaminated the following original setup')
    if case['name'] == 'Item-granted Lightning Bolt support':
        if not any(s.get('status') == 'applied' for s in rows[1].get('supports', [])):
            raise RuntimeError('Item-granted support trial applied no support; inspect native compatibility output')
    print(json.dumps({'case': case['name'], 'seconds': round(elapsed, 3), 'metric': result['metric'],
        'native_baseline': result['baseline'], 'results': [{k: row.get(k) for k in ['name', 'valid', 'output', 'deltas', 'supports', 'warnings', 'error']} for row in rows],
        'conditions': result['conditions'], 'search': result['search'], 'rollback': proof,
        'independent_hashes': {key: digest(after[key]) for key in ['xml', 'stats', 'config', 'skills']}}, ensure_ascii=False), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--plan', action='store_true', help='read-only discovery; do not evaluate scenarios')
    mode.add_argument('--run-native', action='store_true', help='parent opt-in to temporary native A/B evaluation')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=55698)
    parser.add_argument('--timeout', type=float, default=60, help='per-response timeout; minimum 60 seconds for evaluation')
    parser.add_argument('--include-search', action='store_true')
    for name in ['spark', 'verisium', 'bolt', 'item-bolt']:
        parser.add_argument(f'--{name}-group', type=int, help='explicit ONE-BASED native group index')
    args = parser.parse_args()
    if args.timeout < 60:
        parser.error('Native evaluator timeout must be at least 60 seconds (15-second guard is between passes)')
    api = Api(args.host, args.port, args.timeout)
    try:
        version = api.read('version', 'version')
        before = snapshot(api)
        explicit = {name: getattr(args, name + '_group') for name in ['spark', 'verisium', 'bolt', 'item_bolt']}
        cases, indices = build_cases(before['skills'], explicit)
        print(json.dumps({'api_version': version.get('apiVersion'), 'feature': version.get('features', {}).get('nativeGemEvaluation'),
            'native_indices': indices, 'mcp_indices': {k: v - 1 for k, v in indices.items() if k in ['spark', 'verisium', 'bolt', 'item_bolt']},
            'weapon_set_two': weapon_set_two(before['xml']),
            'cases': [{'name': case['name'], 'params': case['params']} for case in cases]}, ensure_ascii=False), flush=True)
        if args.plan:
            return
        if version.get('apiVersion') != '1.3.0' or version.get('features', {}).get('nativeGemEvaluation') is not True:
            raise RuntimeError('Deploy API 1.3.0 with nativeGemEvaluation before running this probe')
        if not weapon_set_two(before['xml']):
            raise RuntimeError('Weapon set 2 is not selected; parent must prepare the owned runtime. Probe did not change it.')
        for case in cases:
            run_case(api, before, case)
        if args.include_search:
            run_case(api, before, {'name': 'Bounded 48-trial Spark support search', 'params': {
                'groupIndex': indices['spark'], 'metric': 'CombinedDPS',
                'search': {'mode': 'suggest', 'maxEvaluations': 48, 'limit': 3}}})
        print('PASS: all requested native cases and independent rollback checks completed.', flush=True)
    finally:
        api.close()


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'FAIL: {exc}', file=sys.stderr)
        raise SystemExit(1)
