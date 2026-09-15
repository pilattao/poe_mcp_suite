"""Real ConfigTab -> quest parser -> MAIN ModDB tests, with no running PoB/API.

Only the window/HTTP adapters in the existing offline runtime are replaced.
The native XML reader, ConfigTab, ConfigOptions, ModParser and calculator run
from the source fork. Runtime file writes and network access are forbidden.
"""
import os
from pathlib import Path
import xml.etree.ElementTree as ET
from xml.sax.saxutils import quoteattr

import pytest
from item_evaluator_runtime import runtime, SOURCE, ROOT

KEY = 'questAct 2Valley of the TitansMedallion'
CANONICAL = '30% increased Charm Charges Gained\n\t+1 Charm Slot'
FLATTENED = '30% increased Charm Charges Gained  +1 Charm Slot'


@pytest.fixture(scope='module')
def native():
    previous = Path.cwd()
    lua = runtime()
    os.chdir(SOURCE)
    lua.execute('''
      local belt=new('Item'):Item('Rarity: NORMAL\\nUtility Belt\\nCharm Slots: 2\\nItem Level: 60\\nImplicits: 1\\nHas 2 Charm Slots')
      build.itemsTab:AddItem(belt,true)
      build.itemsTab:EquipItemInSet(belt,build.itemsTab.activeItemSetId)
      function questTestLoad(xmlText)
        local doc,err=common.xml.ParseXML(xmlText);assert(doc,err)
        build.configTab:Load(doc[1],'quest-choice-test.xml')
        build.configTab:BuildModList()
      end
      function questTestSavedValue(key)
        local out={};build.configTab:Save(out)
        for _,set in ipairs(out) do
          for _,node in ipairs(set) do
            if node.elem=='Input' and node.attrib.name==key then return node.attrib.string end
          end
        end
      end
      function questTestOutput(weaponSet)
        local env=build.calcsTab.calcs.initEnv(build,'MAIN',{weaponSet=weaponSet})
        build.calcsTab.calcs.perform(env)
        return env.weaponSet,env.modDB:Sum('BASE',nil,'CharmLimit'),build.configTab.modList:Sum('BASE',nil,'CharmLimit')
      end
      function questTestMods()
        local result={}
        for _,mod in ipairs(build.configTab.modList) do
          if mod.source and mod.source:match('^Quest:') then
            result[#result+1]=mod.name..':'..mod.type..':'..tostring(mod.value)..':'..mod.source
          end
        end
        table.sort(result);return table.concat(result,'\\n')
      end
    ''')
    try:
        yield lua
    finally:
        os.chdir(previous)


def config_xml(value, key=KEY):
    # quoteattr deliberately preserves character references for a native parser
    # that doesn't decode them, so use literals for the XML whitespace fixture.
    attr = quoteattr(value).replace('&#10;', '\n').replace('&#9;', '\t').replace('&#13;', '\r')
    return f'<Config activeConfigSet="1"><ConfigSet id="1" title="Test"><Input name={quoteattr(key)} string={attr}/></ConfigSet></Config>'


def load(native, value, key=KEY):
    native.globals().questTestLoad(config_xml(value, key))


@pytest.mark.parametrize('weapon_set', [1, 2])
@pytest.mark.parametrize('value', [
    CANONICAL, FLATTENED,
    '30% increased Charm Charges Gained +1 Charm Slot',
    ' \t30% increased Charm Charges Gained\r\n\t+1 Charm Slot\t ',
])
def test_known_medallion_choice_adds_native_slot_without_rewriting_input(native, value, weapon_set):
    load(native, value)
    # Independent literals: belt 2 + known quest 1, in either actual MAIN weapon context.
    assert native.globals().questTestOutput(weapon_set) == (weapon_set, 3, 1)
    assert native.eval("build.configTab.modList:Sum('INC',nil,'CharmChargesGained')") == 30
    assert native.eval("build.configTab.input['questAct 2Valley of the TitansMedallion']") == value
    assert native.globals().questTestSavedValue(KEY) == value
    native.execute('build.configTab:BuildModList()')
    assert native.globals().questTestOutput(weapon_set) == (weapon_set, 3, 1), 'Recalculation must not double the reward'


def test_second_medallion_option_is_not_silently_changed_to_charges_gained(native):
    value = '30% increased Charm Effect Duration  +1 Charm Slot'
    load(native, value)
    assert native.globals().questTestOutput(2) == (2, 3, 1)
    assert native.eval("build.configTab.modList:Sum('INC',nil,'CharmDuration')") == 30
    assert native.eval("build.configTab.modList:Sum('INC',nil,'CharmChargesGained')") == 0
    assert native.globals().questTestSavedValue(KEY) == value


@pytest.mark.parametrize('value', ['None', '', '+9 Charm Slots',
    '31% increased Charm Charges Gained  +1 Charm Slot',
    '30% increased charm charges gained  +1 Charm Slot',
    '30% increased Charm Charges Gained + 1 Charm Slot'])
def test_unknown_or_unselected_choice_cannot_supply_arbitrary_modifiers(native, value):
    load(native, value)
    assert native.globals().questTestOutput(1) == (1, 2, 0)
    assert native.eval("build.configTab.modList:Sum('INC',nil,'CharmChargesGained')") == 0
    assert native.eval("build.configTab.input['questAct 2Valley of the TitansMedallion']") == value


def test_ambiguous_whitespace_alias_is_ignored_but_exact_choice_stays_valid(native):
    options = native.eval("(function() for _,q in ipairs(data.questRewards) do if q.Info=='Medallion' then return q.Options end end end)()")
    size = len(options)
    options[size + 1] = '30% increased Charm Charges Gained\n+1 Charm Slot'
    try:
        load(native, FLATTENED)
        assert native.globals().questTestOutput(1) == (1, 2, 0)
        load(native, CANONICAL)
        assert native.globals().questTestOutput(1) == (1, 3, 1)
    finally:
        options[size + 1] = None


def test_all_native_multiline_choices_survive_standard_xml_whitespace_normalization(native):
    checked = []
    for _, quest in native.globals().data.questRewards.items():
        options = quest['Options']
        if options is None:
            continue
        key = 'quest' + quest['Description'] + quest['Area'] + quest['Info']
        for _, option in options.items():
            if '\n' not in option:
                continue
            # A real XML reader normalizes literal attribute whitespace to spaces.
            normalized = ET.fromstring(config_xml(option, key)).find('ConfigSet/Input').get('string')
            load(native, option, key)
            canonical_mods = native.globals().questTestMods()
            assert canonical_mods
            load(native, normalized, key)
            assert native.globals().questTestMods() == canonical_mods, key
            assert native.globals().questTestSavedValue(key) == normalized
            checked.append(key)
    assert set(checked) == {KEY, 'questAct 4Eye of HinekoraTribal Medicine', 'questInterlude 2QimahSeven Pillars'}


@pytest.mark.skipif(not os.getenv('POE2_QUEST_PRIVATE_XML'), reason='Private snapshot acceptance is opt-in')
def test_private_snapshot_quest_reward_is_independent_of_weapon_set_and_xml_roundtrip(native):
    raw = Path(os.environ['POE2_QUEST_PRIVATE_XML']).read_text()
    # Only this isolated Lua instance is loaded. No API socket or installed GUI is involved.
    for content in [raw, ET.tostring(ET.fromstring(raw), encoding='unicode')]:
        native.globals().questPrivateSnapshot = content
        native.execute("main:SetMode('BUILD',false,'Quest private offline acceptance',questPrivateSnapshot);main:OnFrame({});build=main.modes.BUILD")
        for weapon_set in [1, 2]:
            assert native.globals().questTestOutput(weapon_set) == (weapon_set, 3, 1)
