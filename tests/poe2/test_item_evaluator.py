"""Real native numerical replacement calculations, with no running GUI involved."""
import os
from pathlib import Path
import pytest
from item_evaluator_runtime import runtime, table, SOURCE

RING = 'Rarity: RARE\nBudget Fixture\nRuby Ring\nItem Level: 80\nLevelReq: 24\nImplicits: 0\n+100 to maximum Life'


@pytest.fixture
def native():
    previous = Path.cwd()
    lua = runtime(quiet=True)
    os.chdir(SOURCE)
    try:
        yield lua, lua.execute((SOURCE / 'API/ItemEvaluator.lua').read_text())
    finally:
        os.chdir(previous)


def call(native, scenarios, **overrides):
    lua, evaluator = native
    p = {'expectedBuildName': 'Item native fixture', 'expectedXml': lua.eval("build:SaveDB('test')"),
         'snapshotId': 'test-snapshot', 'itemSetId': lua.eval('build.itemsTab.activeItemSetId'),
         'skillSetId': lua.eval('build.skillsTab.activeSkillSetId'), 'scenarios': scenarios}
    p.update(overrides)
    return evaluator.evaluate(lua.globals().build, table(lua, p))


def replacement(slot='Ring 1', text=RING, **extra):
    return {'slotName': slot, 'text': text, 'candidateId': 'candidate-' + slot,
            'entryId': 'equipment:' + slot, 'listingId': 'listing-' + slot, **extra}


def test_real_native_single_and_combined_equipment_deltas(native):
    lua, _ = native
    before = lua.eval("build:SaveDB('test')")
    result = call(native, [{'id': 'single', 'replacements': [replacement()]},
                          {'id': 'pair', 'replacements': [replacement(), replacement('Ring 2')]}])
    assert not isinstance(result, tuple), result
    # Recorded native fixture multipliers make the +100 item line worth +105 life.
    assert result['comparisons'][1]['output'] is not None, result['comparisons'][1]['error']
    assert result['comparisons'][1]['output']['Life'] - result['baseline']['Life'] == 105
    assert result['comparisons'][2]['output']['Life'] - result['baseline']['Life'] == 210
    assert result['comparisons'][1]['valid'] is True
    assert result['comparisons'][2]['valid'] is True
    assert all(result['preservation'][key] for key in ['xmlUnchanged', 'statsUnchanged', 'selectionsUnchanged', 'undoUnchanged'])
    assert lua.eval("build:SaveDB('test')") == before


@pytest.mark.parametrize('factory_abi', ['stock-inline', 'source-named'])
def test_factory_compatibility_parses_with_trial_id_and_calculates(native, factory_abi):
    lua, _ = native
    lua.globals().factoryFixtureText = RING
    lua.globals().factoryAbi = factory_abi
    # Stock new() runs an inline constructor and exposes no :Item() method.
    # Source new() rejects constructor arguments. Retain the real native
    # ParseRaw and calculator in both cases, recording the ID before parsing.
    lua.execute('''
      local sourceNew=new
      local itemClass=common.classes.Item
      local sourceConstructor=itemClass.Item
      local sourceParseRaw=itemClass.ParseRaw
      itemClass.ParseRaw=function(self,raw,...)
        if raw==factoryFixtureText then
          factoryParsedItem=self;factoryParseId=self.id
        end
        return sourceParseRaw(self,raw,...)
      end
      if factoryAbi=='stock-inline' then
        itemClass._constructor=sourceConstructor;itemClass.Item=nil
        new=function(className,...)
          if className~='Item' then return sourceNew(className,...) end
          local item=sourceNew(className)
          itemClass._constructor(item,...)
          return item
        end
      end
    ''')
    before = lua.eval("build:SaveDB('factory-before')")
    result = call(native, [{'id': 'factory-item', 'replacements': [replacement()]}])
    assert not isinstance(result, tuple), result
    row = result['comparisons'][1]
    assert row['output'] is not None, row['error']
    assert row['valid'] is True
    assert row['output']['Life'] - result['baseline']['Life'] == 105
    assert lua.eval("factoryParseId~=nil and factoryParseId<0 and factoryParseId==factoryParsedItem.id")
    assert lua.eval("factoryParsedItem.modSource:sub(1,#('Item:'..factoryParseId..':'))=='Item:'..factoryParseId..':'")
    assert lua.eval("factoryParsedItem.Item==nil") is (factory_abi == 'stock-inline')
    assert lua.eval("build.itemsTab.items[factoryParseId]==nil")
    assert all(value for _, value in result['preservation'].items())
    assert lua.eval("build:SaveDB('factory-after')") == before


def test_rejects_stale_xml_and_selection_before_calculation(native):
    assert 'snapshot' in call(native, [{'id': 'one', 'replacements': [replacement()]}], expectedXml='stale')[1].lower()
    assert 'item set' in call(native, [{'id': 'one', 'replacements': [replacement()]}], itemSetId=999)[1].lower()


def test_unparsed_modifier_has_no_fake_calculated_result(native):
    result = call(native, [{'id': 'unsupported', 'replacements': [replacement(text=RING + '\n999% totally made up damage')]}])
    row = result['comparisons'][1]
    assert row['output'] is None
    assert row['valid'] is False
    assert 'unparsed' in row['error'].lower()


def test_missing_native_property_does_not_validate_as_the_expected_value(native):
    result = call(native, [{'id': 'wrong-weapon', 'replacements': [replacement(expected={'weapon': {'PhysicalMin': 100}})]}])
    assert result['comparisons'][1]['output'] is None
    assert 'weapon' in result['comparisons'][1]['error'].lower()


def test_invalid_slot_or_duplicate_replacement_cannot_change_build(native):
    lua, _ = native
    before = lua.eval("build:SaveDB('test')")
    result = call(native, [{'id': 'wrong', 'replacements': [replacement('Weapon 1')]},
                          {'id': 'duplicate', 'replacements': [replacement(), replacement()]}])
    assert result['comparisons'][1]['valid'] is False
    assert result['comparisons'][2]['valid'] is False
    assert lua.eval("build:SaveDB('test')") == before


def test_native_damage_output_is_calculated_and_level_constraints_remain_visible(native):
    damage = RING + '\n50% increased Damage'
    result = call(native, [{'id': 'damage', 'replacements': [replacement(text=damage)]},
                          {'id': 'future', 'replacements': [replacement(text=RING.replace('LevelReq: 24', 'LevelReq: 100'))]}])
    assert result['comparisons'][1]['output']['CombinedDPS'] > result['baseline']['CombinedDPS']
    assert result['comparisons'][2]['output']['Life'] > result['baseline']['Life']
    assert result['comparisons'][2]['valid'] is False
    assert 'level 100' in result['comparisons'][2]['warnings'][1]


def test_charm_activation_and_both_weapon_sets_are_preserved(native):
    lua, _ = native
    lua.execute('''
      build.itemsTab.activeItemSet.useSecondWeaponSet=true
      build.itemsTab.slots['Charm 1'].controls.activate.state=false
      build.itemsTab.activeItemSet['Charm 1'].active=false
      build.calcsTab:BuildOutput()
    ''')
    before = lua.eval("build:SaveDB('test')")
    charm = 'Rarity: MAGIC\nThawing Charm\nQuality: 0\nLevelReq: 24\nImplicits: 0'
    result = call(native, [{'id': 'charm', 'replacements': [replacement('Charm 1', charm)]},
                          {'id': 'remove-swap', 'replacements': [replacement('Weapon 1 Swap', None, remove=True)]}])
    assert result['comparisons'][1]['output'] is not None
    assert result['comparisons'][2]['output'] is not None
    assert result['conditions']['weaponSet'] == 2
    assert lua.eval("build.itemsTab.slots['Charm 1'].controls.activate.state") is False
    assert lua.eval("build:SaveDB('test')") == before


def test_active_spell_and_full_dps_use_native_calculations_without_changing_gems(native):
    lua, _ = native
    lua.execute('''
      local ops=dofile('API/BuildOps.lua')
      assert(ops.create_socket_group({label='Native Spark'}))
      local index=#build.skillsTab.socketGroupList
      assert(ops.add_gem({groupIndex=index,gemName='Spark',level=1,quality=0}))
      local group=build.skillsTab.socketGroupList[index]
      group.includeInFullDPS=true;group.groupCount=1
      build.mainSocketGroup=index;build.calcsTab:BuildOutput()
    ''')
    before = lua.eval("build:SaveDB('test')")
    result = call(native, [{'id': 'spell', 'replacements': [replacement(text=RING + '\n50% increased Spell Damage')]}])
    assert not isinstance(result, tuple), result
    row = result['comparisons'][1]
    assert row['output']['CombinedDPS'] > result['baseline']['CombinedDPS'] > 0
    assert row['output']['FullDPS'] > result['baseline']['FullDPS'] > 0
    assert lua.eval("build:SaveDB('test')") == before


STAFF = '''Rarity: RARE
Native Staff Fixture
Voltaic Staff
Item Level: 80
Quality: 17
LevelReq: 55
Sockets: S S
Rune: None
Rune: Iron Rune
Implicits: 1
Grants Skill: Level 18 Lightning Bolt
+300 to Intelligence
100% increased effect of Socketed Augment Items'''
CHOIR = '''Rarity: UNIQUE
Choir of the Storm
Jade Amulet
Item Level: 80
LevelReq: 55
Implicits: 2
Grants Skill: Level 18 Lightning Bolt
+10 to Dexterity
+50% to Lightning Resistance
Critical Hits Ignore Enemy Monster Lightning Resistance
Trigger Lightning Bolt Skill on Critical Hit'''


def test_generated_weapon_levels_supports_and_same_item_rune_roundtrip(native):
    lua, _ = native
    lua.globals().fixtureStaff = STAFF
    lua.execute('''
      local item=new('Item');item.id=9001;item:Item(fixtureStaff)
      build.itemsTab.items[item.id]=item;table.insert(build.itemsTab.itemOrderList,item.id)
      build.itemsTab.slots['Weapon 1']:SetSelItemId(item.id)
      build.itemsTab.activeItemSet.useSecondWeaponSet=false
      build.calcsTab:BuildOutput()
      local ops=dofile('API/BuildOps.lua')
      for index,group in ipairs(build.skillsTab.socketGroupList) do
        if group.slot=='Weapon 1' and group.gemList[1].nameSpec=='Lightning Bolt' then
          build.mainSocketGroup=index;group.includeInFullDPS=true
        end
      end
      local supports=assert(ops.create_socket_group({slot='Weapon 1',label='Staff supports'}))
      assert(ops.add_gem({groupIndex=supports.index,gemName='Rapid Casting II',level=1,quality=0}))
      build.calcsTab:BuildOutput()
    ''')
    before = lua.eval("build:SaveDB('test')")
    # Trade contains the already-scaled rune effect in addition to the rune identity.
    from_trade = STAFF.replace('Implicits: 1', 'Implicits: 2\n{enchant}{rune}50% increased Spell Damage')
    result = call(native, [{'id': 'same', 'replacements': [replacement('Weapon 1', from_trade)]},
                          {'id': 'level', 'replacements': [replacement('Weapon 1', from_trade.replace('Level 18 Lightning Bolt', 'Level 19 Lightning Bolt'))]},
                          {'id': 'pair-control', 'replacements': [replacement('Weapon 1', from_trade), replacement('Ring 2', None, remove=True)]}])
    assert not isinstance(result, tuple), result
    rows = result['comparisons']
    diagnostic = lua.eval("require('dkjson').encode")(lua.table_from({'before': result['baselineSkills'], 'after': rows[1]['skills'], 'error': rows[1]['error']}))
    assert rows[1]['output'] is not None, rows[1]['error']
    assert rows[1]['output']['CombinedDPS'] == result['baseline']['CombinedDPS'], diagnostic
    assert rows[1]['output']['FullDPS'] == result['baseline']['FullDPS']
    assert rows[3]['output']['CombinedDPS'] == rows[1]['output']['CombinedDPS']
    assert rows[2]['output']['CombinedDPS'] > rows[1]['output']['CombinedDPS']
    group = next(g for _, g in rows[2]['skills']['groups'].items() if g['slot'] == 'Weapon 1' and g['gems'][1]['name'] == 'Lightning Bolt')
    assert group['gems'][1]['level'] == 19
    assert group['gems'][1]['skillId'] == 'LightningBoltPlayer'
    assert group['gems'][2]['name'] == 'Rapid Casting II'
    assert all(result['preservation'][key] for key in ['catalogUnchanged', 'treeUnchanged', 'cacheUnchanged', 'undoUnchanged'])
    assert lua.eval("build:SaveDB('test')") == before


def test_choir_granted_trigger_same_item_and_new_level_preserve_public_costs(native):
    lua, _ = native
    lua.globals().fixtureChoir = CHOIR
    lua.execute('''
      local item=new('Item');item.id=9002;item:Item(fixtureChoir)
      build.itemsTab.items[item.id]=item;table.insert(build.itemsTab.itemOrderList,item.id)
      build.itemsTab.slots.Amulet:SetSelItemId(item.id)
      build.calcsTab:BuildOutput()
      for _,group in ipairs(build.skillsTab.socketGroupList) do if group.slot=='Amulet' and group.source then
        fixtureGrantId=group.gemList[1].skillId
      end end
      fixtureCost=data.skills[fixtureGrantId].levels[19].cost
      fixtureCostJson=require('dkjson').encode(fixtureCost)
    ''')
    before = lua.eval("build:SaveDB('test')")
    result = call(native, [{'id': 'choir-same', 'replacements': [replacement('Amulet', CHOIR)]},
                          {'id': 'choir-level', 'replacements': [replacement('Amulet', CHOIR.replace('Level 18 Lightning Bolt', 'Level 19 Lightning Bolt'))]}])
    assert not isinstance(result, tuple), result
    assert result['comparisons'][1]['output'] is not None, result['comparisons'][1]['error']
    assert result['comparisons'][1]['output']['CombinedDPS'] == result['baseline']['CombinedDPS']
    assert result['comparisons'][2]['output'] is not None
    assert lua.eval('data.skills[fixtureGrantId].levels[19].cost==fixtureCost')
    assert lua.eval("require('dkjson').encode(data.skills[fixtureGrantId].levels[19].cost)==fixtureCostJson")
    assert lua.eval("build:SaveDB('test')") == before


def test_calculation_error_cannot_mutate_catalog_tree_caches_or_call_live_ui(native):
    lua, _ = native
    lua.globals().fixtureChoir = CHOIR
    lua.execute('''
      local item=new('Item');item.id=9002;item:Item(fixtureChoir)
      build.itemsTab.items[item.id]=item;table.insert(build.itemsTab.itemOrderList,item.id)
      build.itemsTab.slots.Amulet:SetSelItemId(item.id);build.calcsTab:BuildOutput()
      for _,group in ipairs(build.skillsTab.socketGroupList) do if group.slot=='Amulet' and group.source then fixtureGrantId=group.gemList[1].skillId end end
      fixtureCostJson=require('dkjson').encode(data.skills[fixtureGrantId].levels[19].cost)
      failureCache=GlobalCache;failureData=data;failureTree=build.spec.tree
      failureTreeKey=next(build.spec.tree.nodes);failureNodeName=build.spec.tree.nodes[failureTreeKey].dn
      local original=build.calcsTab.calcs.buildOutput
      failureOriginalCalc=original
      build.calcsTab.calcs.buildOutput=function(trial,mode)
        local env=original(trial,mode)
        data.skills[fixtureGrantId].levels[19].cost={budgetTest=123}
        trial.spec.tree.nodes[failureTreeKey].dn='detached failure sentinel'
        GlobalCache.detachedFailure=true
        error('forced after real MAIN calculation')
      end
    ''')
    before = lua.eval("build:SaveDB('test')")
    result = call(native, [{'id': 'failure', 'replacements': [replacement()]}])
    lua.execute('build.calcsTab.calcs.buildOutput=failureOriginalCalc')
    assert isinstance(result, tuple) and 'forced after real MAIN' in result[1]
    assert lua.eval('GlobalCache==failureCache and GlobalCache.detachedFailure==nil and data==failureData')
    assert lua.eval('build.spec.tree==failureTree and build.spec.tree.nodes[failureTreeKey].dn==failureNodeName')
    assert lua.eval("require('dkjson').encode(data.skills[fixtureGrantId].levels[19].cost)==fixtureCostJson")
    assert lua.eval("build:SaveDB('test')") == before


def test_live_ui_callbacks_are_never_invoked_by_detached_calculation(native):
    lua, _ = native
    lua.execute('''
      uiCalls=0
      for _,slot in pairs(build.itemsTab.slots) do
        slot.onSelChange=function() uiCalls=uiCalls+1;error('live UI callback invoked') end
        slot.onClick=function() uiCalls=uiCalls+1;error('live UI callback invoked') end
      end
      build.controls.buildLoadouts.onSelChange=function() uiCalls=uiCalls+1;error('live loadout callback invoked') end
    ''')
    result = call(native, [{'id': 'equipment', 'replacements': [replacement()]}])
    assert not isinstance(result, tuple), result
    assert result['comparisons'][1]['output']['Life'] > result['baseline']['Life']
    assert lua.eval('uiCalls') == 0


def test_batch_offhand_is_validated_against_the_replacement_mainhand(native):
    lua, _ = native
    bow = 'Rarity: NORMAL\nCrude Bow\nQuality: 0\nImplicits: 0'
    club = 'Rarity: NORMAL\nWooden Club\nQuality: 0\nImplicits: 0'
    shield = 'Rarity: NORMAL\nSplintered Tower Shield\nQuality: 0\nImplicits: 1\nGrants Skill: Raise Shield'
    lua.globals().fixtureBow = bow
    lua.execute('''
      local item=new('Item');item.id=9010;item:Item(fixtureBow)
      build.itemsTab.items[item.id]=item;table.insert(build.itemsTab.itemOrderList,item.id)
      build.itemsTab.slots['Weapon 1']:SetSelItemId(item.id);build.calcsTab:BuildOutput()
    ''')
    before = lua.eval("build:SaveDB('test')")
    result = call(native, [{'id': 'valid-pair', 'replacements': [replacement('Weapon 2', shield), replacement('Weapon 1', club)]},
                          {'id': 'bad-offhand', 'replacements': [replacement('Weapon 2', shield)]}])
    assert not isinstance(result, tuple), result
    assert result['comparisons'][1]['output'] is not None, result['comparisons'][1]['error']
    assert result['comparisons'][2]['output'] is None
    assert 'offhand' in result['comparisons'][2]['error'].lower()
    assert lua.eval("build:SaveDB('test')") == before


def test_unchanged_nonfinite_cached_values_are_not_reported_as_mutation(native):
    lua, _ = native
    lua.execute('GlobalCache.itemTestUndefined=0/0')
    result = call(native, [{'id': 'finite-output', 'replacements': [replacement()]}])
    assert not isinstance(result, tuple), result
    assert result['preservation']['cacheUnchanged'] is True
    assert result['comparisons'][1]['output']['Life'] > result['baseline']['Life']


def test_many_native_sets_bind_by_semantics_and_keep_literal_quest_newlines(native):
    lua, _ = native
    # Model the installed release's named-map format (before character rune slots
    # and custom-modifier blocks). These are empty, unused features in this fixture.
    lua.execute('''
      build.itemsTab.runeSlotOrder={}
      for id=2,16 do
        build.itemsTab:NewItemSet(id,'Fixture equipment '..id)
        build.configTab:NewConfigSet(id,'Fixture configuration '..id)
      end
      for _,set in pairs(build.configTab.configSets) do
        set.customModsList={}
        for index=1,24 do set.input['snapshot-input-'..index]='unchanged '..index end
        set.input['snapshot-literal-newline']='Charges\\n\\t+1 Charm Slot'
      end
      build.calcsTab:BuildOutput()
      fixtureOriginalXml=build:SaveDB('fixture-before')
      local document=assert(common.xml.ParseXML(fixtureOriginalXml))
      local function reverse(list)
        for index=1,math.floor(#list/2) do list[index],list[#list-index+1]=list[#list-index+1],list[index] end
      end
      local function reorder(node)
        if type(node)~='table' then return end
        for _,child in ipairs(node) do reorder(child) end
        if node.elem=='ConfigSet' or node.elem=='ItemSet' or node.elem=='PathOfBuilding2' then reverse(node) end
      end
      reorder(document[1]);fixtureReorderedXml=assert(common.xml.ComposeXML(document[1]))
    ''')
    original, reordered = lua.globals().fixtureOriginalXml, lua.globals().fixtureReorderedXml
    assert original != reordered
    # Independent existing reference must agree before the evaluator sees the request.
    import importlib.util
    reference_path = SOURCE.parents[1] / 'scripts/poe2_xml_semantics.py'
    spec = importlib.util.spec_from_file_location('item_binding_reference', reference_path)
    reference = importlib.util.module_from_spec(spec); spec.loader.exec_module(reference)
    assert reference.canonical(original) == reference.canonical(reordered)
    result = call(native, [{'id': 'ordered-map-control', 'replacements': [replacement()]}], expectedXml=reordered)
    assert not isinstance(result, tuple), result
    assert result['comparisons'][1]['output']['Life'] - result['baseline']['Life'] == 105
    assert all(value for _, value in result['preservation'].items())
    assert reference.canonical(lua.eval("build:SaveDB('fixture-after')")) == reference.canonical(original)

    # Real data loss still rejects before the native calculator factory is reached.
    lua.execute("build.calcsTab.calcs.getMiscCalculator=function() error('CALC_BOUNDARY_REACHED') end")
    changed = reordered.replace('Charges\n\t+1 Charm Slot', 'Charges  +1 Charm Slot')
    assert changed != reordered
    failure = call(native, [{'id': 'changed-quest', 'replacements': [replacement()]}], expectedXml=changed)
    assert isinstance(failure, tuple) and 'snapshot' in failure[1].lower()
    assert 'CALC_BOUNDARY_REACHED' not in failure[1]
