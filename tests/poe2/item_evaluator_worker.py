"""JSON-line test transport around the real, isolated PoB2 ItemEvaluator."""
import json
import os
import sys
from item_evaluator_runtime import runtime, table, SOURCE

lua = runtime(quiet=True)
os.chdir(SOURCE)
api = lua.execute((SOURCE / 'API/BuildOps.lua').read_text())
encode = lua.eval("require('dkjson').encode")
xml = api.export_build_xml()
print(encode(lua.table_from({'xml': xml, 'stats': api.export_stats(), 'name': 'Item native fixture'})), flush=True)
for line in sys.stdin:
    try:
        request = json.loads(line)
        if 'fixtureItems' in request:
            # Test-only setup in this process; never exposed by the production API.
            for index, item in enumerate(request['fixtureItems']):
                lua.globals().fixtureItemText = item['text']
                lua.globals().fixtureItemSlot = item['slot']
                lua.globals().fixtureItemId = 9000 + index
                lua.execute('''
                  local item=new('Item');item.id=fixtureItemId;item:Item(fixtureItemText)
                  build.itemsTab.items[item.id]=item;table.insert(build.itemsTab.itemOrderList,item.id)
                  build.itemsTab.slots[fixtureItemSlot]:SetSelItemId(item.id)
                ''')
            lua.execute('''
              build.calcsTab:BuildOutput()
              for index,group in ipairs(build.skillsTab.socketGroupList) do if group.slot=='Weapon 1' and group.source then
                build.mainSocketGroup=index;group.includeInFullDPS=true
              end end
              build.calcsTab:BuildOutput()
            ''')
            print(encode(lua.table_from({'xml': api.export_build_xml(), 'stats': api.export_stats(), 'name': 'Item native fixture'})), flush=True)
            continue
        result = api.evaluate_item_replacements(table(lua, request))
        if isinstance(result, tuple):
            print(json.dumps({'error': result[1]}), flush=True)
        else:
            print(encode(result), flush=True)
    except Exception as error:
        print(json.dumps({'error': str(error)}), flush=True)
