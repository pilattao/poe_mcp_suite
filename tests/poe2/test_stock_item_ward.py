"""Run actual stock item parsing/calculation with an in-memory parser backport."""
import hashlib
import json
import os
from pathlib import Path

import pytest
from item_evaluator_runtime import runtime, table, SOURCE
from test_stock_parser_backport import cost_baseline, stock_root

HERE = Path(__file__).parent
PATCH = json.loads((HERE / 'fixtures/stock-item-runic-ward.json').read_text())
# Sanitized real item shape: both rune identities and printed rune modifiers.
BODY = '''Rarity: RARE
Ward Fixture
Runeforged Vile Robe
Energy Shield: 389
Ward: 548
Item Level: 81
Quality: 20
Sockets: S S
Rune: Greater Iron Rune
Rune: Warding Rune of Reinforcement
LevelReq: 65
Implicits: 5
{enchant}{rune}18% increased Armour, Evasion and Energy Shield
{enchant}{rune}20% increased Runic Ward
{enchant}{rune}Bonded: +20 to maximum Life
{enchant}{rune}Bonded: +20 to maximum Mana
{enchant}{rune}Bonded: Gain 2% of maximum Life as Extra maximum Runic Ward
+86 to maximum Energy Shield
+44 to Spirit
+26 to Intelligence
+253 to Stun Threshold
49% reduced Poison Duration on you
95% increased Energy Shield'''


def patched_parser(root):
    text = cost_baseline(root)
    for replacement in PATCH['replacements']:
        assert text.count(replacement['old']) == 1
        text = text.replace(replacement['old'], replacement['new'], 1)
    return text


@pytest.fixture
def stock():
    root = stock_root()
    original = (root / PATCH['path']).read_bytes()
    before = Path.cwd()
    lua = runtime(quiet=True, source=root, overrides={PATCH['path']: patched_parser(root)})
    os.chdir(root)
    try:
        yield lua
    finally:
        os.chdir(before)
        assert (root / PATCH['path']).read_bytes() == original


def item(lua, text=BODY, item_id=901):
    return lua.eval('''function(raw,id)
      local item=new('Item');item.id=id;item:ParseRaw(sanitiseText(raw));return item
    end''')(text, item_id)


def test_native_runic_ward_parser_retains_bonded_condition(stock):
    parsed = item(stock)
    runes = parsed['runeModLines']
    assert len(runes) == 5
    assert all(line['extra'] is None for _, line in runes.items()), [line['extra'] for _, line in runes.items()]
    ward_mod = runes[2]['modList'][1]
    assert (ward_mod['name'], ward_mod['type'], ward_mod['value']) == ('Ward', 'INC', 20)
    bonded_mod = runes[5]['modList'][1]
    assert (bonded_mod['name'], bonded_mod['type'], bonded_mod['value']) == ('LifeGainAsWard', 'BASE', 2)
    assert dict(bonded_mod[1].items()) == {'type': 'Condition', 'var': 'CanUseBondedModifiers'}


def test_native_rune_names_and_printed_mods_apply_once_with_augment_effect(stock):
    parsed = item(stock)
    assert parsed['armourData']['Ward'] == 557  # round(387 * 1.20 * 1.20); Iron does not grant Ward
    assert [value for _, value in parsed['runes'].items()] == ['Greater Iron Rune', 'Warding Rune of Reinforcement']
    raw_only = item(stock, BODY.replace('Rune: Greater Iron Rune\nRune: Warding Rune of Reinforcement\n', ''))
    assert raw_only['armourData']['Ward'] == parsed['armourData']['Ward']
    assert len(raw_only['runes']) == 2
    # Actual trade text has already scaled augment amounts: 18/20 become 27/30.
    scaled = BODY.replace('18% increased Armour', '27% increased Armour').replace('20% increased Runic Ward', '30% increased Runic Ward')
    scaled = scaled.replace('Bonded: +20', 'Bonded: +30').replace('Gain 2%', 'Gain 3%') + '\n50% increased effect of Socketed Augment Items'
    boosted = item(stock, scaled)
    assert boosted['armourData']['Ward'] == 604  # round(387 * 1.30 * 1.20)
    assert len(boosted['runes']) == 2
    reparsed = item(stock, boosted.BuildRaw(boosted))
    assert reparsed['armourData']['Ward'] == boosted['armourData']['Ward']


def test_stock_same_armour_native_outputs_and_preservation(stock):
    stock.globals().wardFixture = item(stock)
    stock.execute(r'''
      build.itemsTab.items[901]=wardFixture;table.insert(build.itemsTab.itemOrderList,901)
      build.itemsTab.slots['Body Armour']:SetSelItemId(901)
      build.configTab.input.customMods='+300 to Intelligence\n30% increased Runic Ward'
      build.configTab:BuildModList();build.calcsTab:BuildOutput()
    ''')
    before = stock.eval("build:SaveDB('ward-before')")
    evaluator = stock.globals().dofile(str(SOURCE / 'API/ItemEvaluator.lua'))
    replacement = {'slotName': 'Body Armour', 'text': BODY, 'candidateId': hashlib.sha256(BODY.encode()).hexdigest(),
                   'entryId': 'equipment:Body Armour', 'listingId': 'ward-listing'}
    result = evaluator.evaluate(stock.globals().build, table(stock, {
        'expectedBuildName': 'Item native fixture', 'expectedXml': before, 'snapshotId': 'stock-ward',
        'itemSetId': stock.eval('build.itemsTab.activeItemSetId'), 'skillSetId': stock.eval('build.skillsTab.activeSkillSetId'),
        'scenarios': [{'id': 'same-armour', 'replacements': [replacement]}],
    }))
    assert not isinstance(result, tuple), result
    row = result['comparisons'][1]
    assert row['valid'], (row['error'], list(row['warnings'].values()))
    assert result['baseline']['Ward'] == 724
    assert dict(row['output'].items()) == dict(result['baseline'].items())
    assert all(value for _, value in result['preservation'].items())
    assert stock.eval("build:SaveDB('ward-after')") == before


def test_unrecognized_active_modifier_still_has_no_numeric_outcome(stock):
    evaluator = stock.globals().dofile(str(SOURCE / 'API/ItemEvaluator.lua'))
    result = evaluator.evaluate(stock.globals().build, table(stock, {
        'expectedBuildName': 'Item native fixture', 'expectedXml': stock.eval("build:SaveDB('before')"),
        'snapshotId': 'unknown-ward', 'itemSetId': stock.eval('build.itemsTab.activeItemSetId'),
        'skillSetId': stock.eval('build.skillsTab.activeSkillSetId'),
        'scenarios': [{'id': 'unknown', 'replacements': [{'slotName': 'Body Armour', 'text': BODY + '\n20% increased Imaginary Ward',
                         'candidateId': 'unknown', 'entryId': 'body', 'listingId': 'unknown'}]}],
    }))
    assert not isinstance(result, tuple), result
    row = result['comparisons'][1]
    assert not row['valid'] and row['output'] is None
    assert 'Imaginary Ward' in row['error']
    assert all(value for _, value in result['preservation'].items())
