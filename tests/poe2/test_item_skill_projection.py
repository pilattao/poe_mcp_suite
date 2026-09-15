"""Public-profile item skills must follow actual equipped grants in detached trials."""
import os
from pathlib import Path

import pytest
from item_evaluator_runtime import runtime, table, SOURCE
from test_item_evaluator import CHOIR, replacement
from test_stock_parser_backport import stock_root


@pytest.fixture(params=['source', 'stock'])
def projection(request):
    source = SOURCE if request.param == 'source' else stock_root()
    if not (source / 'Modules/Main.lua').exists():
        pytest.skip('Set POB2_STOCK_SOURCE for the actual stock engine')
    before = Path.cwd()
    lua = runtime(quiet=True, source=source)
    os.chdir(source)
    lua.globals().choirText = CHOIR.replace('Level 18 Lightning Bolt', 'Level 19 Lightning Bolt')
    lua.execute(r'''
      local item=new('Item');item.id=901;item:ParseRaw(sanitiseText(choirText))
      build.itemsTab.items[item.id]=item;table.insert(build.itemsTab.itemOrderList,item.id)
      build.itemsTab.slots.Amulet:SetSelItemId(item.id)
      build.configTab.input.customMods='+300 to Intelligence\n+300 to Dexterity\n+300 to Strength'
      build.configTab:BuildModList();build.calcsTab:BuildOutput()
      local function gem(skillId,level)
        local effect=data.skills[skillId];assert(effect,skillId)
        return {skillId=skillId,gemId=data.gemForSkill[effect] or data.gemForSkill[skillId],nameSpec=effect.name,level=level,quality=0,
          enabled=true,enableGlobal1=true,enableGlobal2=true,count=1,corrupted=false,corruptLevel=0}
      end
      profileGroup={label='Imported Lightning Bolt',enabled=true,includeInFullDPS=true,groupCount=1,
        mainActiveSkill=1,mainActiveSkillCalcs=1,gemList={
          gem('UniqueBreachLightningBoltPlayer',19),gem('SupportCooldownRecoveryPlayerTwo',1),
          gem('SupportConcentratedAreaPlayer',1),gem('SupportDeliberationPlayer',1),
          gem('SupportSpellCascadePlayer',1),gem('SupportZenithPlayerTwo',1)}}
      table.insert(build.skillsTab.socketGroupList,1,profileGroup)
      build.skillsTab:ProcessSocketGroup(profileGroup)
      build.mainSocketGroup=1;build.calcsTab.input.skill_number=1
    ''')
    try:
        yield lua, lua.globals().dofile(str(SOURCE / 'API/ItemEvaluator.lua'))
    finally:
        os.chdir(before)


def evaluate(projection, scenarios):
    lua, evaluator = projection
    return evaluator.evaluate(lua.globals().build, table(lua, {
        'expectedBuildName': 'Item native fixture', 'expectedXml': lua.eval("build:SaveDB('projection')"),
        'snapshotId': 'profile-projection', 'itemSetId': lua.eval('build.itemsTab.activeItemSetId'),
        'skillSetId': lua.eval('build.skillsTab.activeSkillSetId'), 'scenarios': scenarios,
    }))


def test_imported_manual_grant_keeps_supports_and_follows_native_item_level(projection):
    lua, _ = projection
    text = lua.globals().choirText
    before = lua.eval("build:SaveDB('before')")
    result = evaluate(projection, [
        {'id': 'same', 'replacements': [replacement('Amulet', text)]},
        {'id': 'level', 'replacements': [replacement('Amulet', text.replace('Level 19 Lightning Bolt', 'Level 20 Lightning Bolt'))]},
        {'id': 'same-pair', 'replacements': [replacement('Amulet', text), replacement('Ring 2', None, remove=True)]},
    ])
    assert not isinstance(result, tuple), result
    same, raised, pair = [result['comparisons'][i] for i in (1, 2, 3)]
    assert raised['output'] is not None, raised['error']
    assert raised['output']['CombinedDPS'] > result['baseline']['CombinedDPS'] > 0
    assert raised['output']['FullDPS'] > result['baseline']['FullDPS'] > 0
    assert same['valid'] and raised['valid'] and pair['valid']
    assert dict(same['output'].items()) == dict(pair['output'].items()) == dict(result['baseline'].items())
    for state, level in [(result['baselineSkills'], 19), (raised['skills'], 20)]:
        main = state['groups'][state['mainSocketGroup']]
        assert main['gems'][1]['skillId'] == 'UniqueBreachLightningBoltPlayer'
        assert main['gems'][1]['level'] == level
        assert len(main['gems']) == 6
        assert [main['gems'][i]['skillId'] for i in range(2, 7)] == [
            'SupportCooldownRecoveryPlayerTwo', 'SupportConcentratedAreaPlayer', 'SupportDeliberationPlayer',
            'SupportSpellCascadePlayer', 'SupportZenithPlayerTwo']
        binding = state['itemSkillBindings'][1]
        assert binding['groupIndex'] == state['mainSocketGroup']
        assert binding['slotName'] == 'Amulet' and binding['sourceLevel'] == level
        assert binding['method'] == 'unique-equipped-item-grant'
    assert all(value for _, value in result['preservation'].items())
    assert lua.eval("build:SaveDB('after')") == before
    assert lua.eval('profileGroup.source==nil and profileGroup.slot==nil and profileGroup.gemList[1].level==19')


def test_removed_item_cannot_leave_an_imported_free_skill(projection):
    result = evaluate(projection, [{'id': 'remove', 'replacements': [replacement('Amulet', None, remove=True)]}])
    assert not isinstance(result, tuple), result
    row = result['comparisons'][1]
    assert row['output'] is None and not row['valid']
    assert 'item-granted skill projection' in row['error']
    assert all(value for _, value in result['preservation'].items())


def test_projection_preserves_native_spell_level_bonuses(projection):
    lua, _ = projection
    lua.execute(r'''
      build.configTab.input.customMods=build.configTab.input.customMods..'\n+5 to Level of all Spell Skills'
      build.configTab:BuildModList()
    ''')
    result = evaluate(projection, [{'id': 'level', 'replacements': [replacement('Amulet', lua.globals().choirText.replace('Level 19 Lightning Bolt', 'Level 20 Lightning Bolt'))]}])
    assert not isinstance(result, tuple), result
    row = result['comparisons'][1]
    assert row['output'] is not None, row['error']
    assert result['baseline']['GemLevel'] == 24
    assert row['output']['GemLevel'] == 25
    assert row['output']['CombinedDPS'] > result['baseline']['CombinedDPS']
    assert all(value for _, value in result['preservation'].items())


def test_multiple_equipped_owners_are_explicitly_ambiguous(projection):
    lua, _ = projection
    lua.execute(r'''
      local text='Rarity: RARE\nGrant Fixture\nRuby Ring\nItem Level: 80\nImplicits: 1\nGrants Skill: Level 19 Lightning Bolt'
      local item=new('Item');item.id=902;item:ParseRaw(text)
      item.grantedSkills={{skillId='UniqueBreachLightningBoltPlayer',level=19,source=item.modSource}}
      build.itemsTab.items[item.id]=item;table.insert(build.itemsTab.itemOrderList,item.id)
      build.itemsTab.slots['Ring 1']:SetSelItemId(item.id)
    ''')
    result = evaluate(projection, [{'id': 'ambiguous', 'replacements': [replacement('Amulet', lua.globals().choirText)]}])
    assert isinstance(result, tuple) and result[0] is None
    assert 'ambiguous item-granted skill projection' in result[1]
