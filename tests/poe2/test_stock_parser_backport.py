"""Portable stock/source native parser checks. No GUI, network or file writes.

Set POB2_STOCK_SOURCE (or POB_INSTALL_DIR) to the stock installation.
"""
import hashlib
import json
import os
from pathlib import Path

import pytest
from item_evaluator_runtime import runtime, SOURCE

HERE=Path(__file__).parent
PATCH=json.loads((HERE/'fixtures/stock-parser-backport.json').read_text())
BODY='''Rarity: RARE
Parser Ward Fixture
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
STAFF='''Rarity: RARE
Parser Rune Fixture
Voltaic Staff
Item Level: 80
Quality: 20
LevelReq: 55
Sockets: S
Rune: Hedgewitch Assandra's Rune of Wisdom
Implicits: 3
Grants Skill: Level 18 Lightning Bolt
{enchant}{rune}+1 to Level of all Spell Skills
{enchant}{rune}Bonded: Archon recovery period expires 30% faster
+300 to Intelligence'''


def stock_root():
    value=os.environ.get('POB2_STOCK_SOURCE') or os.environ.get('POB_INSTALL_DIR')
    if not value:pytest.skip('Set POB2_STOCK_SOURCE to run stock parser tests')
    root=Path(value).expanduser().resolve()
    if not (root/PATCH['path']).exists():pytest.skip('Stock parser not found in configured root')
    return root


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def replacements(text, rows):
    for row in rows:
        assert text.count(row['old'])==1,'parser patch context mismatch'
        text=text.replace(row['old'],row['new'],1)
    return text


def cost_baseline(root):
    text=(root/PATCH['path']).read_text()
    if digest(text)==PATCH['final_sha256']:
        # Parent may already have deployed the backport. Undo only in memory to
        # keep the stock/partial-patch negative controls reproducible.
        for row in reversed(PATCH['replacements']):
            assert text.count(row['new'])==1
            text=text.replace(row['new'],row['old'],1)
    if digest(text)==PATCH['after_ward_costs_sha256']:return text
    assert digest(text)==PATCH['stock_original_sha256'],'Unknown stock parser; fail closed'
    # Apply the already-reviewed cost patch in memory; no parent-manifest dependency.
    lines=(HERE/'fixtures/stock-ward-costs.patch').read_text().splitlines(True)
    selected=False;hunks=[];current=[]
    for line in lines:
        if line.startswith('--- '):
            if selected and current:hunks.append(current)
            current=[];selected=line.strip()=='--- a/'+PATCH['path']
        elif selected and line.startswith('@@'):
            if current:hunks.append(current)
            current=[]
        elif selected and not line.startswith('+++'):current.append(line)
    if selected and current:hunks.append(current)
    for hunk in hunks:
        old=''.join(line[1:] for line in hunk if line[0] in ' -')
        new=''.join(line[1:] for line in hunk if line[0] in ' +')
        assert text.count(old)==1
        text=text.replace(old,new,1)
    assert digest(text)==PATCH['after_ward_costs_sha256']
    return text


@pytest.fixture(scope='module',params=['stock','alias-only','corrected','source'])
def native(request):
    mode=request.param
    root=SOURCE if mode=='source' else stock_root()
    original=(root/PATCH['path']).read_bytes()
    overrides={}
    if mode!='source':
        text=cost_baseline(root)
        if mode=='alias-only':text=replacements(text,[r for r in PATCH['replacements'] if '"armour, evasion and energy shield"' not in r['old']])
        elif mode=='corrected':text=replacements(text,PATCH['replacements']);assert digest(text)==PATCH['final_sha256']
        overrides={PATCH['path']:text}
    previous=Path.cwd();lua=runtime(quiet=True,source=root,overrides=overrides);os.chdir(root)
    try:yield mode,lua
    finally:
        os.chdir(previous)
        assert (root/PATCH['path']).read_bytes()==original


def parse(lua,raw=BODY):
    return lua.eval("function(raw)local item=new('Item');item.id=901;item:ParseRaw(sanitiseText(raw));return item end")(raw)


def equip(lua,item,mods=''):
    lua.globals().parserFixture=item;lua.globals().parserMods=mods
    lua.execute(r'''
      if not build.itemsTab.items[901] then table.insert(build.itemsTab.itemOrderList,901) end
      build.itemsTab.items[901]=parserFixture;build.itemsTab.slots['Body Armour']:SetSelItemId(901)
      build.configTab.input.customMods='+300 to Intelligence\n'..parserMods
      build.configTab:BuildModList();build.calcsTab:BuildOutput()
    ''')
    return lua.eval('build.calcsTab.mainOutput.Ward')


def test_native_body_defences_and_partial_patch_negative_control(native):
    mode,lua=native;item=parse(lua)
    # Negative controls demonstrate the bug; only the complete backport is valid.
    if mode in ['corrected','source']:
        assert item['armourData']['Ward']==557
    elif mode=='alias-only':
        assert item['armourData']['Ward']>557
    else:
        assert item['armourData']['Ward']<557
    assert item['armourData']['EnergyShield']==389
    assert item['base']['armour']['Ward']==387
    assert item['quality']==20


def test_specific_global_defences_do_not_change_ward_and_generic_defences_do(native):
    mode,lua=native;item=parse(lua)
    if mode not in ['corrected','source']:
        assert equip(lua,item,'30% increased Armour, Evasion and Energy Shield')>item['armourData']['Ward']
        return
    assert equip(lua,item,'30% increased Armour, Evasion and Energy Shield')==557
    assert equip(lua,item,'30% increased Defences')==724
    assert equip(lua,item,'30% increased Ward')==724


def test_iron_rune_does_not_affect_ward(native):
    mode,lua=native
    if mode not in ['corrected','source']:pytest.skip('negative-control parser')
    without=BODY.replace('Rune: Greater Iron Rune','Rune: None').replace('{enchant}{rune}18% increased Armour, Evasion and Energy Shield\n','')
    assert parse(lua,without)['armourData']['Ward']==parse(lua)['armourData']['Ward']==557


def test_known_rune_identity_and_printed_lines_apply_once_and_roundtrip(native):
    mode,lua=native
    if mode not in ['corrected','source']:pytest.skip('negative-control parser')
    item=parse(lua)
    text_only=parse(lua,BODY.replace('Rune: Greater Iron Rune\nRune: Warding Rune of Reinforcement\n',''))
    assert item['armourData']['Ward']==text_only['armourData']['Ward']==557
    assert len(item['runes'])==len(text_only['runes'])==2
    assert all(not line['extra'] for _,line in item['runeModLines'].items())
    ward_lines=[line for _,line in item['runeModLines'].items() if line['line']=='20% increased Runic Ward']
    assert len(ward_lines)==1 and ward_lines[0]['modList'][1]['name']=='Ward'
    assert parse(lua,item.BuildRaw(item))['armourData']['Ward']==557
    scaled=BODY.replace('18% increased Armour','27% increased Armour').replace('20% increased Runic Ward','30% increased Runic Ward')
    scaled=scaled.replace('Bonded: +20','Bonded: +30').replace('Gain 2%','Gain 3%')+'\n50% increased effect of Socketed Augment Items'
    boosted=parse(lua,scaled)
    assert boosted['armourData']['Ward']==604
    assert boosted['armourData']['EnergyShield']==405
    assert len(boosted['runes'])==2
    assert parse(lua,boosted.BuildRaw(boosted))['armourData']['Ward']==604


def test_archon_remains_unparsed_with_known_identity_no_noop_mapping(native):
    mode,lua=native;item=parse(lua,STAFF)
    assert list(item['runes'].values())==["Hedgewitch Assandra's Rune of Wisdom"]
    archon=[line for _,line in item['runeModLines'].items() if 'Archon recovery' in line['line']]
    assert len(archon)==1
    if mode=='source':
        assert archon[0]['bonded'] is True
    else:
        # Stock encodes Bonded in the text/predicate, not the newer line flag.
        assert archon[0]['line'].startswith('Bonded: ')
    assert archon[0]['extra'] and len(archon[0]['modList'])==0
    spelling=lua.eval("function()local mods,extra=modLib.parseMod('20% increased Imaginary Ward');return extra end")()
    assert spelling  # The parser/strict guard cannot silently accept an unknown active mod.


def test_stock_bonded_predicate_is_measured_not_inferred_from_class(native):
    mode,lua=native
    if mode!='corrected':pytest.skip('stock-specific condition contract')
    item=parse(lua);equip(lua,item)
    condition="not not build.calcsTab.mainEnv.player.modDB:GetCondition('CanUseBondedModifiers')"
    assert lua.eval(condition) is False
    assert lua.eval("build.calcsTab.mainEnv.player.modDB:Sum('BASE',nil,'LifeGainAsWard')")==0
    equip(lua,item,'Gain the benefits of Bonded Modifiers on Runes and Idols')
    assert lua.eval(condition) is True
    assert lua.eval("build.calcsTab.mainEnv.player.modDB:Flag(nil,'Condition:CanUseBondedModifiers')") is True
    assert lua.eval("build.calcsTab.mainEnv.player.modDB:Sum('BASE',nil,'LifeGainAsWard')")==2
    equip(lua,item)


def test_manifest_preserves_cost_patch_chain_and_exact_reverse():
    root=stock_root();base=cost_baseline(root)
    patched=replacements(base,PATCH['replacements'])
    assert digest(patched)==PATCH['final_sha256']
    for row in reversed(PATCH['replacements']):
        assert patched.count(row['new'])==1;patched=patched.replace(row['new'],row['old'],1)
    assert patched==base
