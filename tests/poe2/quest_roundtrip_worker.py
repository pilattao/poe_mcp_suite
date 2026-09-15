"""Offline native XML/ConfigTab comparison for the TypeScript round-trip test.

Inputs are disposable exported copies. Never connects to the installed PoB/API.
"""
import json
import math
import os
from pathlib import Path
import sys
from item_evaluator_runtime import runtime, SOURCE
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
from poe2_xml_semantics import canonical

request = json.loads(Path(sys.argv[1]).read_text())
lua = runtime()
os.chdir(SOURCE)
lua.execute('''
  function questRoundtripDocument(text)
    local parsed,err=common.xml.ParseXML(text);assert(parsed,err)
    return parsed[1]
  end
  function questRoundtripCalculate(text,fullBuild)
    local doc=questRoundtripDocument(text)
    if fullBuild then
      main:SetMode('BUILD',false,'Offline whitespace round-trip',text)
      main:OnFrame({});build=main.modes.BUILD
    else
      local config
      for _,node in ipairs(doc) do if node.elem=='Config' then config=node end end
      assert(config,'Config section missing')
      build.configTab:Load(config,'round-trip.xml')
    end
    build.configTab:BuildModList()
    build.calcsTab:BuildOutput()
    local env=build.calcsTab.mainEnv
    return {questCharmLimit=build.configTab.modList:Sum('BASE',nil,'CharmLimit'),
      questCharmChargesGained=build.configTab.modList:Sum('INC',nil,'CharmChargesGained'),
      totalCharmLimit=env.modDB:Sum('BASE',nil,'CharmLimit'),output=env.player.output}
  end
''')


def document_evidence(text):
    root = lua.globals().questRoundtripDocument(text)
    attributes, rune_items, item_orders = {}, {}, {}

    def visit(node, path):
        attrs = node['attrib']
        if attrs:
            attributes[path] = dict(attrs.items())
        counts = {}
        content = []
        for i in range(1, len(node) + 1):
            child = node[i]
            if isinstance(child, str):
                content.append(child)
                continue
            name = child['elem']
            counts[name] = counts.get(name, 0) + 1
            visit(child, f'{path}/{name}[{counts[name]}]')
        if node['elem'] in ['Item', 'RuneSlot', 'Notes']:
            rune_items[path] = {'attributes': dict(attrs.items()) if attrs else {}, 'content': content}
        if node['elem'] == 'Item':
            item_orders[path] = ['#text' if isinstance(node[i], str) else node[i]['elem'] for i in range(1, len(node) + 1)]

    visit(root, root['elem'])
    return attributes, rune_items, item_orders


def calculate(text):
    result = lua.globals().questRoundtripCalculate(text, request.get('fullBuild', False))
    stats = {k: v for k, v in result['output'].items()
             if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)}
    return {k: result[k] for k in ['questCharmLimit', 'questCharmChargesGained', 'totalCharmLimit']} | {'numericOutput': stats}

attributes, items, item_orders = document_evidence(request['before'])
new_attributes, new_items, new_item_orders = document_evidence(request['after'])
restored_attributes, restored_items, _ = document_evidence(request['restored'])
before, after, restored = [calculate(request[k]) for k in ['before', 'after', 'restored']]
changed = [k for k in set(before['numericOutput']) | set(after['numericOutput'])
           if before['numericOutput'].get(k) != after['numericOutput'].get(k)]
original_document, exported_document = canonical(request['before']), canonical(request['after'])
def first_difference(a, b, location='root'):
    if type(a) != type(b): return {'location': location, 'beforeType': type(a).__name__, 'afterType': type(b).__name__}
    if isinstance(a, (list, tuple)):
        if len(a) != len(b): return {'location': location, 'beforeLength': len(a), 'afterLength': len(b)}
        for i, (left, right) in enumerate(zip(a, b)):
            if left != right: return first_difference(left, right, f'{location}[{i}]')
    elif a != b:
        return {'location': location, 'before': str(a)[:250], 'after': str(b)[:250]}
    return None
sections_before = {node[0]: node for node in original_document[2] if isinstance(node, tuple)}
sections_after = {node[0]: node for node in exported_document[2] if isinstance(node, tuple)}
proof = {'attributesEqual': attributes == new_attributes,
         'nativeDocumentEqual': original_document == exported_document,
         'changedSections': [key for key in set(sections_before) | set(sections_after) if sections_before.get(key) != sections_after.get(key)],
         'firstDocumentDifference': first_difference(original_document, exported_document),
         'changedItemContentOrder': [{'path': key, 'before': item_orders[key], 'after': new_item_orders.get(key)} for key in item_orders if item_orders[key] != new_item_orders.get(key)],
         'runeAndItemDataEqual': items == new_items,
         'mathEqual': before == after,
         'restoredEqual': before == restored and attributes == restored_attributes and items == restored_items,
         'nativeAttributeNodeCount': len(attributes), 'itemRuneNodeCount': len(items),
         'numericOutputCount': len(before['numericOutput']), 'changedNumericOutputs': changed,
         'changedAttributePaths': [k for k in set(attributes) | set(new_attributes) if attributes.get(k) != new_attributes.get(k)],
         'before': {k: v for k, v in before.items() if k != 'numericOutput'},
         'after': {k: v for k, v in after.items() if k != 'numericOutput'},
         'restored': {k: v for k, v in restored.items() if k != 'numericOutput'}}
print('QUEST_ROUNDTRIP_RESULT ' + json.dumps(proof), flush=True)
