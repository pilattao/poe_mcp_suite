"""LuaJIT boundary regressions against installed PoB2 class implementations.

These tests execute installed methods, not copied adapters. UI objects and input
records are minimal fixtures; BuildOutput supplies NO calculated stats. Thus a
passing test proves mutation/ABI behavior, never DPS or a native GUI integration.
POB2_SOURCE may point at another installation; tests skip when it is absent.
"""
import os
import re
from pathlib import Path

import pytest
from lupa.luajit21 import LuaRuntime

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "PathOfBuilding/src/API/BuildOps.lua"
INSTALLED = Path(os.environ.get("POB2_SOURCE") or os.environ.get("POB_INSTALL_DIR") or ROOT / "PathOfBuilding/src")


def config_entry(name):
    source = (INSTALLED / "Modules/ConfigOptions.lua").read_text()
    start = source.index('\t{ var = "' + name + '"')
    end = source.find('\n\t{', start + 1)
    # Entries may have comments after their closing brace; Lua permits these.
    return source[start:end]


@pytest.fixture
def backend():
    if not (INSTALLED / "Classes/SkillsTab.lua").exists():
        pytest.skip("installed PoB2 source required (POB2_SOURCE)")
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.execute('''
      classes = {}
      function newClass(name, ...)
        local cls = {}; classes[name] = cls
        for _, base in ipairs({...}) do
          if type(base) == 'string' then
            for key,value in pairs(classes[base] or {}) do cls[key]=value end
          end
        end
        return cls
      end
      function copyTable(t, shallow)
        if type(t) ~= 'table' then return t end
        local c = {}; for k,v in pairs(t) do c[k] = shallow and v or copyTable(v) end
        return setmetatable(c, getmetatable(t))
      end
      copyTableSafe = copyTable
      function wipeTable(t) for k in pairs(t) do t[k]=nil end return t end
      function isValueInArray(t, v) for k,x in ipairs(t) do if x==v then return k end end end
      round = function(n) return math.floor(n+0.5) end
      colorCodes = setmetatable({}, {__index=function() return '' end})
      data = {itemMods={Runes={}},flavourText={}, misc={MaxEnemyLevel=85}, gems={}, gemForSkill={}, skills={}, gemForBaseName={}}
      function LoadModule(name) if name=='Modules/ConfigOptions' then return registry end return {} end
      function new(name, ...)
        if name=='ModList' then return {NewMod=function() end,ModList=function(self) return self end} end
        error('Unexpected constructor: '..name)
      end
    ''')
    lua.execute("registry = {\n" + "\n".join(config_entry(n) for n in ["enemyLevel", "resistancePenalty", "usePowerCharges"]) + "\n}")
    # Development PoB2 loads the same registry with require; releases may use LoadModule.
    lua.globals().test_source_root = str(INSTALLED)
    lua.execute("package.path = test_source_root .. '/?.lua;' .. package.path; package.loaded['Modules.ConfigOptions'] = registry")
    for path in ["Classes/UndoHandler.lua", "Modules/CalcTools.lua", "Classes/ConfigTab.lua", "Classes/SkillsTab.lua", "Classes/ItemsTab.lua", "Classes/ItemSlotControl.lua"]:
        lua.execute((INSTALLED / path).read_text())
    lua.execute('''
      build = {data=data, characterLevel=70, characterLevelAutoMode=true, viewMode='TREE', mainSocketGroup=1,
        modFlag=false, buildFlag=false, spec={jewels={},nodes={},tree={nodes={}}},
        calcsTab={input={skill_number=1}, mainOutput={}, BuildOutput=function() end},
        SyncLoadouts=function(self) self.synced=true end}
      local cfg=setmetatable({build=build,configSets={[3]={input={},placeholder={}}},activeConfigSetId=3,
        varControls={},defaultState={},undo={},redo={},modFlag=false}, {__index=classes.ConfigTab})
      for _,v in ipairs(registry) do
        cfg.defaultState[v.var] = v.type=='check' and false or (v.type=='list' and v.list[v.defaultIndex or 1].val or 0)
        cfg.varControls[v.var] = {varData=v,list=v.list,SetText=function(self,s) self.buf=s end,
          SelByValue=function(self,val) self.value=val end,
          _className=v.type=='check' and 'CheckBoxControl' or (v.type=='list' and 'DropDownControl' or 'EditControl')}
      end
      cfg.input=cfg.configSets[3].input; cfg.placeholder=cfg.configSets[3].placeholder
      build.configTab=cfg; cfg:ResetUndo()
      local st=setmetatable({build=build,skillSets={[3]={id=3,socketGroupList={}}},activeSkillSetId=3,
        skillSetOrderList={3}, controls={groupList={}}, defaultGemLevel='normalMaximum',undo={},redo={},modFlag=false},
        {__index=classes.SkillsTab})
      -- UI display only; the installed processing and undo methods remain real.
      st.SetDisplayGroup=function(self,g) self.displayGroup=g end
      st.socketGroupList=st.skillSets[3].socketGroupList
      build.skillsTab=st; st:ResetUndo()
      local it=setmetatable({build=build,slots={},runeSlots={},orderedSlots={},items={},itemOrderList={},
        itemSets={},itemSetOrderList={},undo={},redo={},modFlag=false}, {__index=classes.ItemsTab})
      build.itemsTab=it
      for _,name in ipairs({'Amulet','Belt','Weapon 1','Weapon 2','Weapon 1 Swap','Weapon 2 Swap','Flask 1','Flask 2','Charm 1','Charm 2','Charm 3'}) do
        local slot=setmetatable({itemsTab=it,slotName=name,selItemId=0,items={},list={},jewelSocketList={},
          controls={activate={state=false}},IsShown=function() return true end},{__index=classes.ItemSlotControl})
        it.slots[name]=slot; table.insert(it.orderedSlots,slot)
      end
      it:NewItemSet(1,'Default'); it:SetActiveItemSet(1); it:ResetUndo(); it.modFlag=false
      function fixtureGem(id, name, support, maxLevel)
        local ge={id=id..'Player',name=name,support=support,levels={},color=3,statSets={}}
        for n=1,maxLevel do ge.levels[n]={levelRequirement=n+3} end
        local gem={id=id,name=name,baseTypeName=name,grantedEffectId=ge.id,grantedEffect=ge,
          naturalMaxLevel=maxLevel,reqStr=0,reqDex=0,reqInt=100}
        data.gems[id]=gem; data.gemForBaseName[name:lower()]=id; data.skills[ge.id]=ge
        return gem
      end
      fixtureGem('active','Test Active',false,20); fixtureGem('support','Test Support',true,1)
      function fixtureItem(kind, name)
        return {type=kind,baseName=name,name=name,base={type=kind,tags={}},rarity='NORMAL',
          NormaliseQuality=function() end,BuildModList=function() end,GetPrimarySlot=function() return kind end}
      end
    ''')
    api = lua.execute(SOURCE.read_text())
    return lua, api


def rejected(result):
    assert isinstance(result, tuple) and result[0] is None and isinstance(result[1], str), result
    return result[1]


def test_enemy_level_persists_in_active_config_and_undo(backend):
    lua, api = backend
    result = api.set_config(lua.eval('{enemyLevel=83}'))
    assert result['applied']['enemyLevel'] == 83
    assert lua.eval('build.configTab.configSets[3].input.enemyLevel') == 83
    assert lua.eval('build.configTab.enemyLevel') == 83
    lua.execute('build.configTab:Undo()')
    assert lua.eval('build.configTab.input.enemyLevel') is None


@pytest.mark.parametrize('params', ['{enemyLevel=83,notAConfig=true}', '{usePowerCharges="nonsense"}', '{resistancePenalty=-13}', '{bandit="Alira"}', '{pantheonMajorGod="None"}'])
def test_invalid_config_batch_never_partially_mutates(backend, params):
    lua, api = backend
    rejected(api.set_config(lua.eval(params)))
    assert lua.eval('next(build.configTab.input)') is None
    assert lua.eval('#build.configTab.undo') == 1


def test_config_calculation_failure_rolls_back(backend):
    lua, api = backend
    lua.execute("build.calcsTab.BuildOutput=function() error('injected failure') end")
    assert 'injected failure' in rejected(api.set_config(lua.eval('{enemyLevel=83}')))
    assert lua.eval('build.configTab.input.enemyLevel') is None
    assert lua.eval('build.configTab.modFlag') is False


@pytest.mark.parametrize('slot,kind,name', [('Flask 3','Flask','Life Flask'),('Flask 2','Flask','Life Flask'),('Charm 1','Flask','Mana Flask')])
def test_item_invalid_slot_does_not_add_inventory(backend, slot, kind, name):
    lua, api = backend
    lua.globals().parsed = lua.globals().fixtureItem(kind, name)
    lua.execute("new=function() return parsed end")
    rejected(api.add_item_text(lua.table_from({'text':'interface fixture','slotName':slot})))
    assert lua.eval('next(build.itemsTab.items)') is None


def test_real_item_add_and_failed_clear_restore_equipment(backend):
    lua, api = backend
    lua.execute("parsed=fixtureItem('Flask','Life Flask'); new=function() return parsed end")
    result=api.add_item_text(lua.eval('{text="interface fixture",slotName="Flask 1"}'))
    assert lua.eval('build.itemsTab.slots["Flask 1"].selItemId') == result['id']
    lua.execute("build.calcsTab.BuildOutput=function() error('injected failure') end")
    rejected(api.clear_item_slot(lua.eval('{slotName="Flask 1"}')))
    assert lua.eval('build.itemsTab.slots["Flask 1"].selItemId') == result['id']


def test_two_flasks_three_charms_and_ui_activation(backend):
    lua, api = backend
    rejected(api.set_flask_active(lua.eval('{index=3,active=true}')))
    assert api.set_flask_active(lua.eval('{index=2,active=true}')) is True
    assert lua.eval('build.itemsTab.slots["Flask 2"].controls.activate.state') is True
    assert api.set_flask_active(lua.eval('{slotName="Charm 3",active=true}')) is True
    assert lua.eval('build.itemsTab.activeItemSet["Charm 3"].active') is True


def test_create_item_set_registers_once_and_copies_weapon_selection(backend):
    lua, api = backend
    lua.execute('build.itemsTab.activeItemSet.useSecondWeaponSet=true')
    result = api.create_item_set(lua.eval('{copyFrom=1,title="Copied"}'))
    assert len(result['itemSets']) == 2
    assert result['itemSets'][2]['useSecondWeaponSet'] is True
    rejected(api.create_item_set(lua.eval('{copyFrom=999}')))
    assert lua.eval('#build.itemsTab.itemSetOrderList') == 2


def test_unknown_gem_is_rejected_without_inserting(backend):
    lua, api = backend
    api.create_socket_group(lua.eval('{}'))
    rejected(api.add_gem(lua.eval('{groupIndex=1,gemName="Missing gem"}')))
    assert lua.eval('#build.skillsTab.socketGroupList[1].gemList') == 0


def test_support_default_level_and_separate_active_set(backend):
    lua, api = backend
    api.create_socket_group(lua.eval('{slot="Weapon 1",label="Supports"}'))
    result=api.add_gem(lua.eval('{groupIndex=1,gemName="test support"}'))
    assert result['name'] == 'Test Support'
    assert lua.eval('build.skillsTab.skillSets[3].socketGroupList[1].gemList[1].level') == 1
    assert api.get_skills()['activeSkillSetId'] == 3
    assert lua.eval('build.skillsTab.modFlag') is True


@pytest.mark.parametrize('params', ['{groupIndex=1,gemName="Test Support",level=20}', '{groupIndex=1,gemName="Test Active",qualityId="Anomalous"}', '{groupIndex=1,gemName="Test Active",level=1.5}'])
def test_gem_input_rejected_before_insertion(backend, params):
    lua, api = backend
    api.create_socket_group(lua.eval('{}'))
    rejected(api.add_gem(lua.eval(params)))
    assert lua.eval('#build.skillsTab.socketGroupList[1].gemList') == 0


def test_generated_groups_are_read_only_and_supports_use_separate_group(backend):
    lua, api = backend
    api.create_socket_group(lua.eval('{slot="Weapon 1"}'))
    lua.execute('build.skillsTab.socketGroupList[1].source="Item:1"')
    rejected(api.add_gem(lua.eval('{groupIndex=1,gemName="Test Support"}')))
    assert lua.eval('#build.skillsTab.socketGroupList[1].gemList') == 0


def test_skill_failed_calculation_restores_active_set_and_undo(backend):
    lua, api = backend
    api.create_socket_group(lua.eval('{}'))
    lua.execute("build.calcsTab.BuildOutput=function() error('injected failure') end")
    rejected(api.add_gem(lua.eval('{groupIndex=1,gemName="Test Active"}')))
    assert lua.eval('#build.skillsTab.socketGroupList[1].gemList') == 0
    assert lua.eval('build.skillsTab.socketGroupList==build.skillsTab.skillSets[3].socketGroupList') is True


def test_group_invalid_count_does_not_change_enabled(backend):
    lua, api = backend
    api.create_socket_group(lua.eval('{}'))
    rejected(api.set_socket_group_enabled(lua.eval('{groupIndex=1,enabled=false,count=-1}')))
    assert lua.eval('build.skillsTab.socketGroupList[1].enabled') is True


def test_main_selection_invalid_group_leaves_selection_intact(backend):
    lua, api = backend
    api.create_socket_group(lua.eval('{}'))
    rejected(api.set_main_selection(lua.eval('{mainSocketGroup=999}')))
    assert lua.eval('build.mainSocketGroup') == 1


def test_gem_detail_uses_real_statset_and_requirement_abi(backend):
    lua, api = backend
    lua.execute('''
      local ge=data.gems.active.grantedEffect
      ge.statSets={{label='First',stats={'test_stat'},levels={{7}},statDescriptionScope='skill'},
        {label='Second',stats={'test_stat'},levels={{9}},statDescriptionScope='skill'}}
      -- Only the presentation renderer is a recorder; stat arithmetic is installed CalcTools.
      data.describeStats=function(stats,scope) return {tostring(stats.test_stat)} end
    ''')
    result=api.get_gem_detail(lua.eval('{gemName="Test Active",levels={1}}'))
    assert result['perLevel'][1]['reqInt'] == lua.eval('calcLib.getGemStatRequirement(4,100,false)')
    assert result['perLevel'][1]['statSets'][1]['statLines'][1] == '7'
    assert result['perLevel'][1]['statSets'][2]['statLines'][1] == '9'


def test_stale_stats_are_not_returned_when_calculation_fails(backend):
    lua, api = backend
    lua.execute("build.calcsTab.BuildOutput=function() error('injected failure') end")
    assert 'injected failure' in rejected(api.get_main_output())


def test_player_level_requires_integer_and_marks_build_dirty(backend):
    lua,api=backend
    rejected(api.set_level(73.5))
    assert api.set_level(73) is True
    assert lua.eval('build.characterLevel') == 73
    assert lua.eval('build.modFlag') is True


def test_read_breakdowns_propagate_calc_failure(backend):
    lua,api=backend
    lua.execute("build.calcsTab.BuildOutput=function() error('injected failure') end")
    for name in ['get_stat_breakdown','get_calc_breakdown']:
        assert 'injected failure' in rejected(api[name](lua.eval('{stat="Life"}')))


def test_anoint_baseline_failure_restores_display_and_view(backend):
    lua,api=backend
    lua.execute('''
      local it=build.itemsTab
      it.items[1]=fixtureItem('Amulet','Amulet'); it.activeItemSet.Amulet.selItemId=1; it.slots.Amulet.selItemId=1
      it.displayItem='original'; it.anointEnchantSlot=2
      it.anointItem=function() error('injected failure') end
      build.calcsTab.GetMiscCalculator=function() return function() error('unexpected calc') end end
    ''')
    assert 'injected failure' in rejected(api.evaluate_anoint_candidates(lua.eval('{}')))
    assert lua.eval('build.itemsTab.displayItem') == 'original'
    assert lua.eval('build.itemsTab.anointEnchantSlot') == 2
    assert lua.eval('build.viewMode') == 'TREE'


def test_ordinary_belt_is_not_anointable(backend):
    lua,api=backend
    lua.execute('''
      local it=build.itemsTab; it.items[1]=fixtureItem('Belt','Belt')
      it.activeItemSet.Belt.selItemId=1; it.slots.Belt.selItemId=1
    ''')
    assert 'anoint' in rejected(api.evaluate_anoint_candidates(lua.eval('{slot="Belt"}'))).lower()


def test_legacy_global_spectre_mutation_is_explicit_gap(backend):
    lua,api=backend
    lua.execute("build.spectreList={};data.spectres={monster={name='Test Monster'}}")
    assert 'gem' in rejected(api.set_spectres(lua.eval('{spectres={"monster"}}'))).lower()
    assert lua.eval('#build.spectreList') == 0


def test_spectre_assignment_sets_real_per_gem_selection(backend):
    lua,api=backend
    lua.execute("build.spectreList={};data.spectres={monster={name='Test Monster'}};data.gems.active.grantedEffect.minionList={'monster'}")
    api.create_socket_group(lua.eval('{}'))
    api.add_gem(lua.eval('{groupIndex=1,gemName="Test Active"}'))
    result=api.set_spectres(lua.eval('{groupIndex=1,gemIndex=1,spectres={"monster"}}'))
    assert result['active'][1]['id'] == 'monster'
    assert lua.eval('build.skillsTab.socketGroupList[1].gemList[1].skillMinion') == 'monster'


def test_calc_with_honours_full_dps_and_restores_view_on_error(backend):
    lua,api=backend
    lua.execute('''
      build.spec.nodes={[1]={id=1}};build.spec.allocNodes={}
      build.calcsTab.GetMiscCalculator=function() return function(override, full)
        assert(full==true,'Full DPS option was discarded'); error('requested full calculation') end, {} end
    ''')
    assert 'requested full calculation' in rejected(api.calc_with(lua.eval('{addNodes={1},useFullDPS=true}')))
    assert lua.eval('build.viewMode') == 'TREE'


def test_failed_open_is_not_reported_ready_from_previous_build(backend):
    lua,api=backend
    lua.execute('''
      build.importTab={};main={modes={BUILD=build},SetMode=function(self,mode,...) self.newMode=mode end}
    ''')
    assert api.open_build_xml(lua.eval('{name="New"}'))['ready'] is False


def test_tree_switch_calls_installed_set_active_spec(backend):
    lua,api=backend
    # Load the actual method (the TreeTab module's GUI dependencies are irrelevant).
    src=(INSTALLED/'Classes/TreeTab.lua').read_text()
    method=re.search(r'^function TreeTabClass:SetActiveSpec\(.*?^end',src,re.M|re.S).group()
    lua.execute('TreeTabClass={};local m_min=math.min\n'+method)
    lua.execute('''
      latestTreeVersion='0_5';data.setJewelRadiiGlobally=function(v) selectedRadii=v end
      local first={treeVersion='0_5',jewels={[12]=7},SetWindowTitleWithBuildClass=function() end}
      local second={treeVersion='0_5',jewels={[12]=9},SetWindowTitleWithBuildClass=function() end}
      build.spec=first;build.itemsTab.slots['Jewel 12']={nodeId=12,selItemId=7}
      build.itemsTab.controls={specSelect={}}
      build.UpdateClassDropdowns=function() end
      build.treeTab=setmetatable({build=build,specList={first,second},activeSpec=1,controls={}}, {__index=TreeTabClass})
    ''')
    api.select_spec(2)
    assert lua.eval('build.itemsTab.slots["Jewel 12"].selItemId') == 9
    assert lua.eval('selectedRadii') == '0_5'


def test_spectre_selection_updates_installed_calculator_catalog(backend):
    lua,api=backend
    lua.execute("build.spectreList={};data.spectres={monster={name='Test Monster'}};data.gems.active.grantedEffect.name='Spectre: {0} ';data.gems.active.grantedEffect.minionList={}")
    api.create_socket_group(lua.eval('{}'))
    api.add_gem(lua.eval('{groupIndex=1,gemName="Test Active"}'))
    result=api.set_spectres(lua.eval('{groupIndex=1,gemIndex=1,spectres={"monster"}}'))
    assert not isinstance(result,tuple),result
    # Execute the installed catalog selection logic, including the empty static minionList.
    src=(INSTALLED/'Modules/CalcActiveSkill.lua').read_text()
    start=src.index('\tlocal minionList, monsterDamage')
    end=src.index('\n\tif minionList[1]',start)
    lua.execute("local t_insert=table.insert;local env={build=build};local activeGrantedEffect=data.gems.active.grantedEffect;local activeSkill={effectList={}}\n"+src[start:end]+"\nselectedCatalog=activeSkill.minionList")
    assert lua.eval('selectedCatalog[1]') == 'monster'


def test_failed_spectre_mutation_restores_catalog(backend):
    lua,api=backend
    lua.execute("build.spectreList={};data.spectres={monster={name='Test Monster'}};data.gems.active.grantedEffect.name='Spectre: {0} ';data.gems.active.grantedEffect.minionList={}")
    api.create_socket_group(lua.eval('{}'));api.add_gem(lua.eval('{groupIndex=1,gemName="Test Active"}'))
    lua.execute("build.calcsTab.BuildOutput=function() error('injected failure') end")
    assert 'injected failure' in rejected(api.set_spectres(lua.eval('{groupIndex=1,gemIndex=1,spectres={"monster"}}')))
    assert lua.eval('#build.spectreList') == 0


def test_failed_item_set_switch_restores_weapon_and_activation(backend):
    lua,api=backend
    api.create_item_set(lua.eval('{}'))
    lua.execute("build.itemsTab.itemSets[2]['Charm 1'].active=true;build.calcsTab.BuildOutput=function() error('injected failure') end")
    assert 'injected failure' in rejected(api.select_item_set(2))
    assert lua.eval('build.itemsTab.activeItemSetId') == 1
    assert lua.eval('build.itemsTab.slots["Charm 1"].active') is None


def test_trade_query_rejects_poe1_options_before_constructor(backend):
    lua,api=backend
    lua.execute('build.itemsTab.tradeQuery={}')
    assert 'PoE1' in rejected(api.generate_weighted_trade_query(lua.eval('{slot="Amulet",options={includeScourge=true}}')))


def test_save_write_error_does_not_clear_dirty_flag(backend):
    lua,api=backend
    lua.execute('''
      build.modFlag=true;build.SaveDB=function() return '<PathOfBuilding2/>' end
      io.open=function() return {write=function() return nil,'disk full' end,close=function() return true end} end
    ''')
    assert 'disk full' in rejected(api.save_build('fixture.xml'))
    assert lua.eval('build.modFlag') is True


def test_empty_gem_level_request_is_rejected(backend):
    lua,api=backend
    lua.execute('data.gems.active.grantedEffect.statSets={}')
    assert 'level' in rejected(api.get_gem_detail(lua.eval('{gemName="Test Active",levels={}}')))


def test_group_removal_preserves_selected_surviving_skill(backend):
    lua,api=backend
    for i in range(3):
        api.create_socket_group(lua.table_from({'label':f'Group {i+1}'}))
    lua.execute('build.mainSocketGroup=3;build.calcsTab.input.skill_number=3')
    assert api.remove_skill(lua.eval('{groupIndex=1}')) is True
    assert lua.eval('build.skillsTab.socketGroupList[build.mainSocketGroup].label') == 'Group 3'


def test_config_failed_mod_builder_restores_prior_input(backend):
    lua,api=backend
    lua.execute('''
      originalBuildModList=build.configTab.BuildModList
      build.configTab.BuildModList=function(self)
        if self.input.enemyLevel==84 then error('injected mod failure') end
        return originalBuildModList(self)
      end
    ''')
    assert 'injected mod failure' in rejected(api.set_config(lua.eval('{enemyLevel=84}')))
    assert lua.eval('build.configTab.input.enemyLevel') is None


def test_statset_selection_rolls_back_nested_gem_fields(backend):
    lua,api=backend
    api.create_socket_group(lua.eval('{}'));api.add_gem(lua.eval('{groupIndex=1,gemName="Test Active"}'))
    lua.execute('''
      local g=build.skillsTab.socketGroupList[1];local gem=g.gemList[1]
      gem.statSet={activePlayer=1};gem.statSetCalcs={activePlayer=1}
      gem.gemData.grantedEffect.statSets={{},{}}
      g.displaySkillList={{activeEffect={grantedEffect=gem.gemData.grantedEffect,srcInstance=gem}}}
      build.calcsTab.BuildOutput=function() error('injected failure') end
    ''')
    rejected(api.set_main_selection(lua.eval('{statSet=2}')))
    assert lua.eval('build.skillsTab.socketGroupList[1].gemList[1].statSet.activePlayer') == 1


def test_real_installed_arc_metadata_and_cost_use_poe2_abi(backend):
    lua,api=backend
    src=(INSTALLED/'Data/Skills/act_int.lua').read_text()
    start=src.index('skills["ArcPlayer"] = ')
    end=src.index('\nskills[',start+1)
    # Real generated data; mod records are never evaluated as character outputs.
    lua.execute('''
      SkillType=setmetatable({}, {__index=function(_,k) return k end})
      bit=require('bit');ModFlag={Projectile=1,Hit=2}
      local skills=data.skills
      local function mod(...) return {...} end
    '''+src[start:end])
    gems=lua.execute((INSTALLED/'Data/Gems.lua').read_text())
    lua.globals().installedGems=gems
    lua.execute('''
      for id,gem in pairs(installedGems) do
        if gem.grantedEffectId=='ArcPlayer' then
          gem.id=id;gem.grantedEffect=data.skills.ArcPlayer
          data.gems[id]=gem;arc=gem;break
        end
      end
      data.costs={{Resource='Mana',ResourceString='{0} Mana',Divisor=1}}
      data.describeStats=function(stats) return {} end
    ''')
    result=api.get_gem_detail(lua.eval('{gemName="Arc",levels={20}}'))
    assert result['perLevel'][1]['critChance'] == lua.eval('arc.grantedEffect.levels[20].critChance')
    assert result['perLevel'][1]['cost'] == str(lua.eval('arc.grantedEffect.levels[20].cost.Mana'))+' Mana'
    assert result['perLevel'][1]['reqInt'] == lua.eval('calcLib.getGemStatRequirement(arc.grantedEffect.levels[20].levelRequirement,arc.reqInt,false)')


def test_mastery_processing_failure_restores_all_node_fields(backend):
    lua,api=backend
    lua.execute('''
      local node={id=5,sd={'before'},modKey='before',mods={'before'},modList={'before'}}
      build.spec.nodes={[5]=node};build.spec.allocNodes={[5]=node}
      build.spec.tree.masteryEffects={[8]={sd={'after'}}}
      build.spec.tree.ProcessStats=function(self,n)
        n.modKey='after';n.mods={};error('injected stat parser failure')
      end
      build.calcsTab.GetMiscCalculator=function() return function() error('unexpected calc') end,{} end
    ''')
    assert 'injected stat parser failure' in rejected(api.calc_with(lua.eval('{masteryEffects={[5]=8}}')))
    assert lua.eval('build.spec.nodes[5].modKey') == 'before'
    assert lua.eval('build.spec.nodes[5].sd[1]') == 'before'
    assert lua.eval('build.spec.tree.masteryEffects[8].sd[1]') == 'after'


def test_mixed_mastery_node_simulation_is_not_silently_ignored(backend):
    lua,api=backend
    lua.execute('''
      local node={id=5,sd={'before'}}
      build.spec.nodes={[5]=node,[6]={id=6}};build.spec.allocNodes={[5]=node}
      build.spec.tree.masteryEffects={[8]={sd={'after'}}}
      build.spec.tree.ProcessStats=function() end
      build.calcsTab.GetMiscCalculator=function() return function(override)
        assert(node.sd[1]=='after','mastery ignored');assert(next(override.addNodes),'node ignored')
        error('both changes reached calculator')
      end,{} end
    ''')
    assert 'both changes reached calculator' in rejected(api.calc_with(lua.eval('{addNodes={6},masteryEffects={[5]=8}}')))
    assert lua.eval('build.spec.nodes[5].sd[1]') == 'before'


# Export-by-export audit. Sources are the installed PoB2 tree, never the PoE1
# donor. This inventory intentionally lists every export so new APIs need review.
# Runtime-only gaps are recorded here because this task owns no documentation files.
EXPORT_AUDIT = [
    ("evaluate_gem_setups", "Classes/GemSelectControl.lua", "function GemSelectClass:CalcOutputWithThisGem(calcFunc, gemData, useFullDPS, fastCalcOptions)", "Native temporary instance calculation; isolated skill undo transactions, full native outputs and XML/stats/history rollback; real GUI A/B checks remain parent-owned"),
    ("get_main_output export_stats", "Classes/CalcsTab.lua", "self.mainOutput = self.mainEnv.player.output", "MAIN/CALCS outputs; fail instead of serving stale stats; PoE2 Spirit/Ward and nested Minion"),
    ("get_tree set_tree update_tree_delta", "Classes/PassiveSpec.lua", "function PassiveSpecClass:ImportFromNodeList(className, classId, ascendClassId, secondaryAscendClassId, hashList, weaponSets, hashOverrides, masteryEffects, treeVersion)", "Preserved nine-argument import, weapon maps and CountAllocNodes; native path allocation; tree-wide rollback and class conversion still need native integration"),
    ("close_build open_build_xml", "Modules/Main.lua", "self.newModeArgs = {...}", "SetMode queues a frame transition; pending opens must not report the previous build ready"),
    ("export_build_xml save_build", "Modules/Build.lua", 'local dbXML = { elem = "PathOfBuilding2" }', "Native SaveDB; failed calculation/write/close returns error; native XML reimport still required"),
    ("set_level get_build_info set_view_mode", "Modules/Build.lua", "self.characterLevelAutoMode", "Native level/auto flag, spec names and UI modes; integer validation and dirty flag"),
    ("calc_with", "Modules/Calcs.lua", "return function(override, useFullDPS, fastCalcOptions)", "Node-keyed override maps; FullDPS honored; masteries patch ProcessStats and restore all fields on failure"),
    ("get_config set_config", "Classes/ConfigTab.lua", "self.input = self.configSets[configSetId].input", "Active config-set input, registry types/list values, enemyLevel override, controls/mod list/undo; no bandit/Pantheon counterpart"),
    ("get_skills create_socket_group add_gem set_gem_level set_gem_quality remove_skill remove_gem set_socket_group_enabled set_gem_enabled", "Classes/SkillsTab.lua", "function SkillsTabClass:ProcessSocketGroup(socketGroup)", "Independent active skill set; native gem IDs/levels, separate slot-linked support groups; generated gem lists protected; alternate quality IDs rejected"),
    ("set_main_selection", "Modules/Build.lua", "srcInstance.statSet[value.grantedEffectId] = index", "MAIN/CALCS selection, parts and per-effect statSet fields"),
    ("add_item_text clear_item_slot get_items", "Classes/ItemsTab.lua", "function ItemsTabClass:IsItemValidForSlot(item, slotName, itemSet, flagState)", "Native slot validation, AddItem, SetSelItemId, PopulateSlots; inventory/equipment undo snapshots"),
    ("set_flask_active", "Classes/ItemSlotControl.lua", 'self.controls.activate.tooltipText = "Activate this charm."', "2 flask indices, Charm 1..3 explicit slotName, slot/control/persistence activation synchronized"),
    ("get_node_state search_nodes get_mastery_options", "Classes/PassiveTree.lua", 'node.type = "Notable"', "Normalized node type, processed descriptions and only mastery options actually present in the loaded tree"),
    ("get_stat_breakdown", "Classes/ModList.lua", "function ModListClass:Tabulate", "Native modDB/skillModList Tabulate, Sum and More; output value from the selected actor"),
    ("get_calc_breakdown", "Classes/CalcsTab.lua", 'self.calcsEnv = self.calcs.buildOutput(self.build, "CALCS")', "Native actor.breakdown flattening; player/minion actor output; no recomputed damage math"),
    ("list_specs select_spec create_spec delete_spec rename_spec", "Classes/TreeTab.lua", "function TreeTabClass:SetActiveSpec(specId, deferSync)", "Real PassiveSpec constructor/undo copy; SetActiveSpec for radii, jewel controls and loadouts; native cross-version integration pending"),
    ("list_item_sets select_item_set create_item_set", "Classes/ItemsTab.lua", "function ItemsTabClass:NewItemSet(itemSetId, name)", "Native item-set registration exactly once, live source copy and weapon-set choice, transactional activation"),
    ("list_spectres set_spectres", "Modules/CalcActiveSkill.lua", "minionList = copyTable(env.build.spectreList)", "Catalog plus per-gem skillMinion/skillMinionCalcs; old global-raised-list request is an explicit gap; native spectre DPS integration pending"),
    ("evaluate_anoint_candidates", "Classes/ItemsTab.lua", 'return (item.canBeAnointed or item.base.type == "Amulet")', "Native anointability/anointItem, real replacement slot, failed baseline restores display; no blanket Belt support"),
    ("probe_stat_weights get_full_dps_breakdown", "Modules/Calcs.lua", "output.SkillDPS = fullDPS.skills", "Native misc-calculator replacements and SkillDPS, nested Minion output; actual DPS/EHP deltas require native runs"),
    ("generate_weighted_trade_query", "Classes/TradeQueryGenerator.lua", 'https://www.pathofexile.com/api/trade2/data/stats', "Native trade2 generator with runes/Base/Radius jewels; PoE1 filter options rejected; live generator/network/popup lifecycle untested"),
    ("get_notes set_notes", "Classes/NotesTab.lua", "self.controls.edit", "Native edit buffer and SetText; dirty flags"),
    ("get_node_power", "Classes/CalcsTab.lua", "function CalcsTabClass:BuildPower()", "Native coroutine, node.power and powerMax; only computed entries returned; native performance/completion integration pending"),
    ("get_gem_detail", "Modules/CalcTools.lua", "function calcLib.buildSkillInstanceStats(skillInstance, grantedEffect, statSet, includeAltQualityStats)", "PoB2 statSets, requirement argument order, cost and quality stat-set scopes; real installed Arc metadata tested"),
]


def test_every_export_has_an_installed_poe2_source_audit(backend):
    _,api=backend
    audited={name for group,_,_,_ in EXPORT_AUDIT for name in group.split()}
    assert set(api.keys()) == audited
    for _,path,anchor,_ in EXPORT_AUDIT:
        assert anchor in (INSTALLED/path).read_text(),path


def test_stats_use_nested_minion_output_and_preserve_field_filter(backend):
    lua,api=backend
    # Boundary fixture values, not a simulated character's engine results.
    lua.execute('build.calcsTab.mainOutput={Minion={TotalDPS=11,CombinedDPS=13}}')
    result=api.export_stats(lua.eval('{"MinionTotalDPS","MinionCombinedDPS"}'))
    assert result['MinionTotalDPS'] == 11
    assert result['MinionCombinedDPS'] == 13
    assert result['Life'] is None
