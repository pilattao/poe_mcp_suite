"""Transactional gem ABI tests using installed PoB2 skill/undo/save methods.

The calculator here returns synthetic outputs to expose selection/count/quality,
rollback, and ranking bugs. These tests are NOT evidence of real build DPS;
main deploys the helper and performs the native GUI A/B checks separately.
"""
import json
from pathlib import Path
import pytest
from test_lua_buildops_mutations import backend, rejected, INSTALLED, ROOT


def plain(value):
    if hasattr(value, 'items'):
        return {str(k): plain(v) for k, v in value.items()}
    return value


@pytest.fixture
def evaluator(backend):
    lua, api = backend
    lua.globals().encodeFixture = lambda value: json.dumps(plain(value), sort_keys=True, separators=(',', ':'))
    lua.globals().api_source_root = str(ROOT / 'PathOfBuilding/src')
    lua.execute('''
      package.path=api_source_root..'/?.lua;'..package.path
      SkillType={Spell=1,Attack=2,OR=3,AND=4,NOT=5}
      GlobalCache={cachedData={MAIN={},CALCS={},CALCULATOR={}},sentinel='original'}
      GlobalGemAssignments={sentinel='original'}
      build.buildName='Fixture'; build.characterLevel=93; build.activeLoadout=4
      build.controls={buildLoadouts={selIndex=4,list={'fixture'}}}
      build.calcsTab.input.misc_buffMode='EFFECTIVE'
      build.itemsTab.activeItemSet.useSecondWeaponSet=true
      build.configTab.input.enemyLevel=83
      local active=data.gems.active.grantedEffect
      active.skillTypes={[SkillType.Spell]=true}; active.statSets={{label='Base'},{label='Alt'}}
      for _,id in ipairs({'support','better','worse','explode','recovery','incompatible'}) do
        if not data.gems[id] then fixtureGem(id,id,true,1) end
        local effect=data.gems[id].grantedEffect
        effect.requireSkillTypes={SkillType.Spell};effect.excludeSkillTypes={};effect.gemFamily={id}
      end
      data.gems.incompatible.grantedEffect.requireSkillTypes={SkillType.Attack}
      data.gems.better.grantedEffect.gemFamily={'support'}
      data.gems.support.grantedEffect.gemFamily={'support'}
      for id,g in pairs(data.gems) do g.gameId=id;g.variantId=id;g.tags=g.grantedEffect.support and {support=true,spell=true} or {spell=true} end
      function build:SyncLoadouts() self.activeLoadout=1;self.controls.buildLoadouts.selIndex=1 end
      function build:SaveDB()
        local skills={};self.skillsTab:Save(skills)
        return encodeFixture({skills=skills,level=self.characterLevel,auto=self.characterLevelAutoMode,
          main=self.mainSocketGroup,calcs=self.calcsTab.input,output=self.calcsTab.mainOutput,
          weapon=self.itemsTab.activeItemSet.useSecondWeaponSet,config=self.configTab.input})
      end
      function fixtureCalc(b, mode)
        local group=b.skillsTab.socketGroupList[b.mainSocketGroup]
        if not group then error('no group') end
        local actor={enemy={}};actor.enemy.player=actor
        local env={player=actor,mode=mode};local activeList={}
        for _,gem in ipairs(group.gemList) do
          local ge=gem.grantedEffect or gem.gemData and gem.gemData.grantedEffect
          if ge and not ge.support then
            activeList[#activeList+1]={skillTypes=ge.skillTypes,actor=actor,
              activeEffect={grantedEffect=ge,gemData=gem.gemData,srcInstance=gem},socketGroup=group}
          end
        end
        actor.activeSkillList=activeList;actor.mainSkill=activeList[group.mainActiveSkill or 1]
        group.displaySkillList=activeList;group.slotEnabled=true
        local score,mana,ehp=100,10,1000;local families={}
        for _,candidateGroup in ipairs(b.skillsTab.socketGroupList) do
          if candidateGroup==group or candidateGroup.slot and candidateGroup.slot==group.slot then
            for _,gem in ipairs(candidateGroup.gemList) do
              local ge=gem.grantedEffect or gem.gemData and gem.gemData.grantedEffect
              if ge and ge.support then
                local applies=gem.enabled and calcLib.canGrantedEffectSupportActiveSkill(ge,actor.mainSkill)
                local family=ge.gemFamily[1]
                local effect={isSupporting={},superseded=false};gem.displayEffect=effect
                if applies then
                  if families[family] then families[family].superseded=true end
                  families[family]=effect;effect.isSupporting[actor.mainSkill]=true
                  if gem.gemId=='explode' then error('fixture native calculation failure') end
                  if gem.gemId=='better' then score=score+40;mana=20 end
                  if gem.gemId=='worse' then score=score-20 end
                  if gem.gemId=='recovery' then ehp=1500 end
                end
              elseif ge then
                score=score+(gem.count or 1)-1+(gem.quality or 0)+(gem.level or 18)-18
              end
            end
          end
        end
        actor.output={CombinedDPS=score,TotalDPS=score,FullDPS=score*(group.groupCount or 1),
          ManaCost=mana,LifeCost=0,SpiritUnreserved=10,TotalEHP=ehp,Life=500,EnergyShield=200,
          Str=100,Dex=100,Int=200}
        GlobalCache.cachedData[mode].trial=score
        return env
      end
      build.calcsTab.calcs={buildOutput=fixtureCalc}
      build.calcsTab.BuildOutput=function(self)
        self.mainEnv=fixtureCalc(build,'MAIN');self.mainOutput=self.mainEnv.player.output
        self.calcsOutput={CombinedDPS=self.mainOutput.CombinedDPS+3}
      end
    ''')
    # Build the fixtures through the native processing boundary used by the existing API.
    api.create_socket_group(lua.eval('{label="Fixture",count=3}'))
    api.add_gem(lua.eval('{groupIndex=1,gemName="active",level=18,quality=10,count=2}'))
    api.add_gem(lua.eval('{groupIndex=1,gemName="support"}'))
    lua.execute('''
      local st=build.skillsTab;local g=st.socketGroupList[1]
      g.gemList[1].statSet={activePlayer=2};g.gemList[1].statSetCalcs={activePlayer=1}
      g.gemList[1].enableGlobal2=false
      st:CreateSkillSet(8,'Alternate');st.skillSetOrderList[2]=8
      st.skillSets[8].socketGroupList[1]={label='Unrelated',gemList={},enabled=false}
      build.calcsTab:BuildOutput();build.activeLoadout=4;build.controls.buildLoadouts.selIndex=4
      build.viewMode='CALCS';build.modFlag=true;st.modFlag=true
      st.redo={st:CreateUndoState()};undoRef=st.undo;redoRef=st.redo
    ''')
    return lua, api


def call(evaluator, expression):
    lua, api = evaluator
    params = lua.eval(expression)
    params['expectedBuildName'] = 'Fixture'
    params['skillSetId'] = 3
    params['expectedXml'] = api.export_build_xml()
    return api.evaluate_gem_setups(params)


def test_native_deltas_and_exact_rollback(evaluator):
    lua, api = evaluator
    before = api.export_build_xml()
    out = call(evaluator, "{groupIndex=1,setups={{name='Current',gems={{refIndex=1},{refIndex=2}}},{name='Better',gems={{refIndex=1},{gemId='better'}}}}}")
    assert out['baseline']['CombinedDPS'] == 111
    assert out['setups'][2]['output']['CombinedDPS'] == 151
    assert out['setups'][2]['deltas']['CombinedDPS']['absolute'] == 40
    assert out['setups'][2]['output']['ManaCost'] == 20
    assert out['ranking'][1]['name'] == 'Better'
    assert out['rollback']['xmlUnchanged'] is True
    assert api.export_build_xml() == before
    assert lua.eval('build.skillsTab.undo==undoRef and build.skillsTab.redo==redoRef')
    assert lua.eval('build.activeLoadout') == 4
    assert lua.eval('build.viewMode') == 'CALCS'
    assert lua.eval('build.skillsTab.socketGroupList[1].gemList[1].statSet.activePlayer') == 2
    assert lua.eval('build.skillsTab.socketGroupList[1].gemList[1].statSetCalcs.activePlayer') == 1
    assert lua.eval('build.skillsTab.socketGroupList[1].gemList[1].count') == 2
    assert lua.eval('build.itemsTab.activeItemSet.useSecondWeaponSet') is True


def test_failure_between_candidates_does_not_leak_to_following_candidate(evaluator):
    lua, api = evaluator
    before = api.export_build_xml()
    out = call(evaluator, "{groupIndex=1,setups={{name='Failure',gems={{refIndex=1},{gemId='explode'}}},{name='Baseline again',gems={{refIndex=1},{refIndex=2}}}}}")
    assert 'fixture native calculation failure' in out['setups'][1]['error']
    assert out['setups'][2]['output']['CombinedDPS'] == 111
    assert api.export_build_xml() == before


@pytest.mark.parametrize('changes', ["{expectedBuildName='Other'}", "{expectedXml='stale'}", "{skillSetId=8}"])
def test_unrelated_or_stale_state_rejected_before_evaluation(evaluator, changes):
    lua, api = evaluator
    before = api.export_build_xml()
    params=lua.eval("{groupIndex=1,expectedBuildName='Fixture',skillSetId=3,setups={{name='A',gems={{refIndex=1}}}}}")
    params['expectedXml']=before
    for key,value in lua.eval(changes).items(): params[key]=value
    assert rejected(api.evaluate_gem_setups(params))
    assert api.export_build_xml() == before


def test_native_support_families_and_compatibility_exclude_invalid_rankings(evaluator):
    out = call(evaluator, "{groupIndex=1,setups={{name='Family collision',gems={{refIndex=1},{refIndex=2},{gemId='better'}}},{name='Wrong type',gems={{refIndex=1},{gemId='incompatible'}}}}}")
    assert len(out['ranking']) == 0
    assert out['setups'][1]['supports'][1]['status'] == 'superseded'
    assert out['setups'][2]['supports'][1]['status'] == 'incompatible'


def test_search_uses_actual_outputs_for_damage_and_defense(evaluator):
    damage = call(evaluator, "{groupIndex=1,search={mode='suggest',candidateGemIds={'worse','better','recovery'},maxEvaluations=12,limit=3}}")
    assert damage['ranking'][1]['gems'][2]['gemId'] == 'better'
    defense = call(evaluator, "{groupIndex=1,metric='TotalEHP',search={mode='optimize',targetGemCount=2,candidateGemIds={'worse','better','recovery'},maxEvaluations=12,limit=3}}")
    assert defense['ranking'][1]['gems'][2]['gemId'] == 'recovery'
    assert defense['ranking'][1]['output']['TotalEHP'] == 1500


def test_item_granted_active_is_preserved_when_evaluating_supports(evaluator):
    lua, api=evaluator
    lua.execute("local g=build.skillsTab.socketGroupList[1];g.source='Item:fixture';g.slot='Weapon 1';table.remove(g.gemList,2)")
    before=api.export_build_xml()
    out=call(evaluator,"{groupIndex=1,setups={{name='Supported item skill',gems={{refIndex=1},{gemId='better'}}}}}")
    assert out['setups'][1]['output']['CombinedDPS']==151
    assert api.export_build_xml()==before
    assert lua.eval('#build.skillsTab.socketGroupList')==1
    assert lua.eval('build.skillsTab.socketGroupList[1].source')=='Item:fixture'


def test_failed_restore_is_not_returned_as_a_successful_comparison(evaluator):
    lua, api=evaluator
    lua.execute("savedRestore=build.skillsTab.RestoreUndoState;build.skillsTab.RestoreUndoState=function() error('restore failure') end")
    assert 'rollback' in rejected(call(evaluator,"{groupIndex=1,setups={{name='A',gems={{refIndex=1}}}}}"))


def test_replacement_keeps_existing_instance_flags_count_and_quality(evaluator):
    lua,api=evaluator
    lua.execute("local g=build.skillsTab.socketGroupList[1].gemList[2];g.count=3;g.quality=7;g.enableGlobal2=false")
    out=call(evaluator,"{groupIndex=1,setups={{name='Replacement',gems={{refIndex=1},{replaceIndex=2,gemId='better'}}}}}")
    gem=out['setups'][1]['gems'][2]
    assert gem['count']==3 and gem['quality']==7 and gem['enableGlobal2'] is False


def test_reordering_active_gems_retains_selected_skill_identity(evaluator):
    lua,api=evaluator
    lua.execute("local g=fixtureGem('second','Second Active',false,20);g.tags={spell=true};g.gameId='second';g.grantedEffect.statSets={{}};g.grantedEffect.skillTypes={[SkillType.Spell]=true}")
    api.add_gem(lua.eval("{groupIndex=1,gemName='second',level=18}"))
    out=call(evaluator,"{groupIndex=1,setups={{name='Reordered',gems={{refIndex=3},{refIndex=2},{refIndex=1}}}}}")
    assert out['setups'][1]['selection']['mainActiveSkill']==2
    assert lua.eval('build.skillsTab.socketGroupList[1].mainActiveSkill')==1


def test_zero_baseline_does_not_invent_a_percentage(evaluator):
    lua,api=evaluator
    lua.execute("originalCalc=fixtureCalc;build.calcsTab.calcs.buildOutput=function(b,m) local env=originalCalc(b,m);env.player.output.CombinedDPS=env.player.output.CombinedDPS-111;return env end;build.calcsTab.BuildOutput=function(self)self.mainEnv=self.calcs.buildOutput(build,'MAIN');self.mainOutput=self.mainEnv.player.output;self.calcsOutput={} end")
    out=call(evaluator,"{groupIndex=1,setups={{name='B',gems={{refIndex=1},{gemId='better'}}}}}")
    assert out['baseline']['CombinedDPS']==0
    assert out['setups'][1]['deltas']['CombinedDPS']['absolute']==40
    assert out['setups'][1]['deltas']['CombinedDPS']['percent'] is None


def test_bound_is_reported_and_baseline_reproducible_after_search(evaluator):
    lua,api=evaluator
    before=api.export_build_xml()
    out=call(evaluator,"{groupIndex=1,search={mode='suggest',candidateGemIds={'better','worse','recovery'},maxEvaluations=1}}")
    assert out['search']['evaluations']==1
    assert out['search']['truncated'] is True
    assert api.export_build_xml()==before


def test_additional_granted_effect_stat_sets_are_owned_by_the_same_gem(evaluator):
    lua,api=evaluator
    lua.execute("local secondary={id='SecondaryPlayer',name='Secondary',statSets={{},{}}};data.skills.SecondaryPlayer=secondary;data.gems.active.additionalGrantedEffects={secondary}")
    out=call(evaluator,"{groupIndex=1,setups={{name='Secondary stat set',gems={{refIndex=1,statSet={SecondaryPlayer=2}},{refIndex=2}}}}}")
    assert out['setups'][1]['valid'] is True
    assert out['setups'][1]['gems'][1]['statSet']['SecondaryPlayer']==2


def test_installed_gem_dropdown_really_uses_temporary_instance_edits(evaluator):
    lua,api=evaluator
    lua.execute((INSTALLED / 'Classes/GemSelectControl.lua').read_text())
    lua.execute('''
      build.skillsTab.displayGroup=build.skillsTab.socketGroupList[1]
      selector=setmetatable({skillsTab=build.skillsTab,index=2},{__index=classes.GemSelectControl})
      originalGem=build.skillsTab.displayGroup.gemList[2].gemData
      selector:CalcOutputWithThisGem(function()
        seenTemporaryGem=build.skillsTab.displayGroup.gemList[2].gemData.id
        return {CombinedDPS=123}
      end,data.gems.better,true)
    ''')
    assert lua.eval('seenTemporaryGem')=='better'
    assert lua.eval('build.skillsTab.displayGroup.gemList[2].gemData==originalGem')


def test_nonfinite_native_metric_is_not_ranked(evaluator):
    lua,api=evaluator
    lua.execute("originalCalc=fixtureCalc;build.calcsTab.calcs.buildOutput=function(b,m)local env=originalCalc(b,m);if env.player.output.CombinedDPS>120 then env.player.output.CombinedDPS=math.huge end;return env end")
    out=call(evaluator,"{groupIndex=1,setups={{name='Nonfinite',gems={{refIndex=1},{gemId='better'}}}}}")
    assert out['setups'][1]['output']['CombinedDPS'] is None
    assert len(out['ranking'])==0


def test_restore_failure_after_a_trial_still_recovers_serialized_skill_state(evaluator):
    lua,api=evaluator
    before=api.export_build_xml()
    lua.execute('''
      savedRestore=build.skillsTab.RestoreUndoState;restoreCalls=0
      build.skillsTab.RestoreUndoState=function(self,state)
        restoreCalls=restoreCalls+1
        if restoreCalls==3 then error('final undo UI failure') end
        return savedRestore(self,state)
      end
    ''')
    assert 'rollback' in rejected(call(evaluator,"{groupIndex=1,setups={{name='B',gems={{refIndex=1},{gemId='better'}}}}}"))
    assert api.export_build_xml()==before


def test_level_18_to_19_preserves_weapon_set_two_and_other_gem_state(evaluator):
    lua,api=evaluator
    before=api.export_build_xml()
    out=call(evaluator,"{groupIndex=1,setups={{name='Level 18',gems={{refIndex=1},{refIndex=2}}},{name='Level 19',gems={{refIndex=1,level=19},{refIndex=2}}}}}")
    assert out['conditions']['useSecondWeaponSet'] is True
    assert out['setups'][2]['gems'][1]['level']==19
    assert out['setups'][2]['gems'][1]['count']==2
    assert out['setups'][2]['deltas']['CombinedDPS']['absolute']==1
    assert api.export_build_xml()==before


def test_unchanged_generated_skill_without_support_capacity_can_be_compared(evaluator):
    lua,api=evaluator
    lua.execute("local g=build.skillsTab.socketGroupList[1];g.source='Tree:fixture';g.noSupports=true;g.slot=nil;table.remove(g.gemList,2)")
    out=call(evaluator,"{groupIndex=1,setups={{name='Retained source',gems={{refIndex=1}}}}}")
    assert out['setups'][1]['valid'] is True


def test_triggered_raw_skill_processing_restores_shared_native_level_costs(evaluator):
    lua,api=evaluator
    lua.execute('''
      local gem=build.skillsTab.socketGroupList[1].gemList[1]
      gem.gemId=nil;gem.gemData=nil;gem.grantedEffect=data.skills.activePlayer;gem.triggered=true
      data.skills.activePlayer.levels[18].cost={Mana=5}
      data.skills.activePlayer.levels[19].cost={Mana=7}
    ''')
    out=call(evaluator,"{groupIndex=1,setups={{name='Triggered level',gems={{refIndex=1,level=19},{refIndex=2}}}}}")
    assert out['rollback']['xmlUnchanged'] is True
    assert lua.eval('data.skills.activePlayer.levels[18].cost.Mana')==5
    assert lua.eval('data.skills.activePlayer.levels[19].cost.Mana')==7


def test_api_13_advertises_native_gem_evaluation(evaluator):
    lua,api=evaluator
    lua.globals().fixtureApi=api
    lua.execute("package.loaded['API.BuildOps']=fixtureApi;package.preload.dkjson=function()return {}end")
    handlers=lua.execute((ROOT/'PathOfBuilding/src/API/Handlers.lua').read_text())
    version=handlers['handlers']['version'](lua.eval('{}'))['version']
    assert version['apiVersion']=='1.4.0'
    assert version['features']['nativeGemEvaluation'] is True


def test_resource_outputs_use_native_names_and_separate_base_from_modified_cost(evaluator):
    lua,api=evaluator
    lua.execute('''
      data.skills.activePlayer.levels[18].cost={Ward=134}
      data.skills.activePlayer.levels[18].cooldown=5.3
      baseCalc=build.calcsTab.calcs.buildOutput
      build.calcsTab.calcs.buildOutput=function(b,mode)
        local env=baseCalc(b,mode)
        env.player.output.Ward=700;env.player.output.WardCost=81
        env.player.output.WardPerSecondCost=16.2;env.player.output.ManaPerSecondCost=20
        env.player.output.LifePerSecondCost=5;env.player.output.Cooldown=5
        return env
      end
    ''')
    result=call(evaluator,"{groupIndex=1,setups={{name='Resources',gems={{refIndex=1},{refIndex=2}}}}}")
    row=result['setups'][1]
    assert row['output']['WardCost']==81
    assert row['output']['WardPerSecondCost']==16.2
    assert row['output']['ManaPerSecondCost']==20
    assert row['output']['LifePerSecondCost']==5
    assert row['output']['Cooldown']==5
    assert row['gems'][1]['baseCosts']['Ward']==134
    assert row['gems'][1]['baseCooldown']==5.3


def test_missing_native_ward_model_is_reported_instead_of_zero_or_a_valid_recommendation(evaluator):
    lua,api=evaluator
    lua.execute('data.skills.activePlayer.levels[18].cost={Ward=134}')
    result=call(evaluator,"{groupIndex=1,setups={{name='Missing Ward model',gems={{refIndex=1},{refIndex=2}}}}}")
    row=result['setups'][1]
    assert row['output']['WardCost'] is None
    assert any('WardCost' in note for _,note in row['resourceNotes'].items())
    assert row['valid'] is False


def test_native_ward_affordability_warning_prevents_ranking(evaluator):
    lua,api=evaluator
    lua.execute('''
      baseCalc=build.calcsTab.calcs.buildOutput
      build.calcsTab.calcs.buildOutput=function(b,mode)
        local env=baseCalc(b,mode);env.player.output.WardCostWarning=true;return env
      end
    ''')
    result=call(evaluator,"{groupIndex=1,setups={{name='Cannot afford',gems={{refIndex=1},{refIndex=2}}}}}")
    assert result['setups'][1]['valid'] is False
    assert 'WardCostWarning' in list(result['setups'][1]['warnings'].values())


def test_resource_only_mode_does_not_require_or_invent_dps(evaluator):
    lua,api=evaluator
    lua.execute('''
      baseCalc=build.calcsTab.calcs.buildOutput
      build.calcsTab.calcs.buildOutput=function(b,mode)
        local env=baseCalc(b,mode)
        env.player.output.CombinedDPS=nil;env.player.output.TotalDPS=nil
        env.player.output.Cooldown=5;env.player.output.WardCost=81
        return env
      end
    ''')
    result=call(evaluator,"{groupIndex=1,resourceOnly=true,setups={{name='Utility',gems={{refIndex=1},{refIndex=2}}}}}")
    assert result['metric']=='resource-only'
    assert result['setups'][1]['output']['CombinedDPS'] is None
    assert result['setups'][1]['output']['WardCost']==81
    assert result['setups'][1]['output']['Cooldown']==5
    assert len(result['ranking'])==0


def test_native_cost_waiver_is_distinct_from_a_missing_ward_model(evaluator):
    lua,api=evaluator
    lua.execute('''
      data.skills.activePlayer.levels[18].cost={Ward=134}
      baseCalc=build.calcsTab.calcs.buildOutput
      build.calcsTab.calcs.buildOutput=function(b,mode)
        local env=baseCalc(b,mode)
        env.player.mainSkill.skillModList={Flag=function(_,_,name)return name=='HasNoCost'end}
        return env
      end
    ''')
    result=call(evaluator,"{groupIndex=1,resourceOnly=true,setups={{name='Waived',gems={{refIndex=1},{refIndex=2}}}}}")
    assert result['setups'][1]['valid'] is True
    assert 'HasNoCost' in result['setups'][1]['resourceNotes'][1]
