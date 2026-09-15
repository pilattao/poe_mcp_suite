"""Execute the fork's actual native cost and per-second loops, not a reimplementation.

Primary implementation: PathOfBuildingCommunity/PathOfBuilding-PoE2, dev,
https://github.com/PathOfBuildingCommunity/PathOfBuilding-PoE2/blob/dev/src/Modules/CalcOffence.lua
The fork already contains upstream Ward/WardPercent/WardPerMinute handling.
Fixture modifiers isolate rounding and efficiency; these are NOT character-build
measurements or a simulation of infusion generation, depletion or uptime.
"""
from pathlib import Path
import pytest
from lupa.luajit21 import LuaRuntime

SOURCE = Path(__file__).resolve().parents[2] / 'PathOfBuilding/src'


def build_cost_runtime(source_root=SOURCE, calc_text=None):
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.execute('''
      m_floor,m_ceil,m_max,m_min=math.floor,math.ceil,math.max,math.min
      t_insert,t_remove,s_format=table.insert,table.remove,string.format
      SkillType=setmetatable({}, {__index=function(_,k)return k end})
      ModFlag=setmetatable({}, {__index=function()return 1 end})
      KeywordFlag=ModFlag
      OR64=function(a,b)return a+b end
      function recordMod(name,kind,value,...)return {name=name,kind=kind,value=value}end
      function fixtureStore(values)
        values=values or {};values.BASE=values.BASE or {};values.INC=values.INC or {};values.MORE=values.MORE or {}
        return {
          Sum=function(self,kind,cfg,...)local n=0;for _,name in ipairs({...})do n=n+(values[kind][name] or 0)end;return n end,
          More=function(self,cfg,...)local n=1;for _,name in ipairs({...})do n=n*(1+(values.MORE[name] or 0)/100)end;return n end,
          Flag=function(self,cfg,name)return values.flags and values.flags[name] or false end,
          Override=function(self,cfg,name)return values.overrides and values.overrides[name] end,
        }
      end
    ''')
    common = (source_root / 'Modules/Common.lua').read_text()
    lua.execute(common[common.index('function round(val, dec)'):common.index('-- Symmetric round with precision:')])
    lua.execute((source_root / 'Modules/CalcTools.lua').read_text())
    cost_data = lua.execute((source_root / 'Data/Costs.lua').read_text())
    lua.globals().nativeCosts = cost_data
    lua.execute('data={costs={}};for _,row in ipairs(nativeCosts)do data.costs[row.Resource]=row end')
    lua.execute('skills={}')
    for file in ['other.lua', 'sup_str.lua']:
        args = (lua.globals().skills, lua.globals().recordMod, lua.globals().recordMod, lua.globals().recordMod)
        loaded = lua.execute((source_root / 'Data/Skills' / file).read_text(), *args)
        if lua.eval('type')(loaded) == 'function':
            loaded(*args)
    source = calc_text if calc_text is not None else (source_root / 'Modules/CalcOffence.lua').read_text()
    cost_start = source.index('\t-- Calculate costs (may be slightly off due to rounding differences)')
    end_marker = '\t-- Eldritch Battery adds maximum Energy Shield' if '\t-- Eldritch Battery adds maximum Energy Shield' in source else '\t-- account for Sacrificial Zeal'
    cost_end = source.index(end_marker, cost_start)
    per_second_start = source.index("\t--Calculates and displays cost per second for skills that don't already have one")
    per_second_end = source.index('\t-- Self hit dmg calcs', per_second_start)
    function = '''function calculateNativeCosts(levelData,modifiers,baseOutput)
      local skillModList=fixtureStore(modifiers)
      local skillCfg,skillFlags,skillData={},{},{}
      local activeSkill={skillTypes={},skillData=skillData,activeEffect={grantedEffectLevel=levelData}}
      local output=baseOutput or {Speed=0}
      local env={modDB=fixtureStore({}),player={mainSkill={skillData={}}}}
      local breakdown=nil
    ''' + source[cost_start:cost_end] + source[per_second_start:per_second_end] + '\nreturn output end'
    lua.execute(function)
    return lua


@pytest.fixture
def costs():
    return build_cost_runtime()


def convert(lua, value):
    return lua.table_from({k: convert(lua, v) for k, v in value.items()}) if isinstance(value, dict) else value


def run(lua, level, mods=None, output=None):
    row = lua.globals().skills.PoweredByVerisiumPlayer.levels[level]
    return lua.globals().calculateNativeCosts(row, convert(lua, mods or {}), convert(lua, output or {'Speed': 0}))


@pytest.mark.parametrize('level,expected', [(18, 134), (19, 144)])
def test_native_base_ward_cost_without_modifiers(costs, level, expected):
    result = run(costs, level)
    assert result['WardCost'] == expected
    assert result['WardHasCost'] is True


@pytest.mark.parametrize('level,expected', [(18, 81), (19, 87)])
def test_efficiency_ii_uses_native_generic_less_cost_and_rounding(costs, level, expected):
    support = costs.globals().skills.SupportEfficiencyPlayerTwo.statSets[1]
    stat = support.constantStats[1]
    mapping = support.statMap[stat[1]][1]
    assert mapping['name'] == 'Cost' and mapping['kind'] == 'MORE'
    result = run(costs, level, {'MORE': {mapping['name']: stat[2]}})
    assert result['WardCost'] == expected
    assert costs.globals().skills.PoweredByVerisiumPlayer.levels[level].cost.Ward == (134 if level == 18 else 144)


@pytest.mark.parametrize('efficiency_mod,expected', [('WardCostEfficiency',41),('CostEfficiency',41),('ManaCostEfficiency',81)])
def test_only_matching_or_generic_efficiency_changes_ward(costs, efficiency_mod, expected):
    result = run(costs, 18, {'MORE': {'Cost': -40}, 'INC': {efficiency_mod: 100}})
    assert result['WardCost'] == expected


def test_native_modifier_order_percent_and_conversion_paths(costs):
    output = run(costs, 18, {'MORE': {'SupportManaMultiplier': 23.456, 'Cost': -40},
        'INC': {'WardCostEfficiency': 25, 'CostEfficiency': 25}})
    assert output['WardCost'] == 66
    row = convert(costs, {'cost': {'Ward': 134, 'Mana': 100, 'Life': 40}})
    output = costs.globals().calculateNativeCosts(row, convert(costs, {'BASE': {
        'WardCostAsPercentOfManaCost': 20, 'WardCostAsPercentOfLifeCost': 20}}), convert(costs, {'Speed': 0}))
    assert output['WardCost'] == 162
    percent = costs.globals().calculateNativeCosts(convert(costs, {'cost': {'WardPercent': 20}}),
        convert(costs, {'INC': {'WardCostEfficiency': 200}}), convert(costs, {'Speed': 0}))
    assert percent['WardPercentCost'] == pytest.approx(20/3)


def test_native_per_second_output_uses_cooldown_and_keeps_correct_field_name(costs):
    result = run(costs, 18, {'MORE': {'Cost': -40}}, {'Speed': 0, 'Cooldown': 5.3})
    assert result['WardPerSecondCost'] == pytest.approx(81/5.3)
    assert result['WardCostPerSecond'] is None


def test_continuous_ward_cost_uses_native_resource_divisor(costs):
    result = costs.globals().calculateNativeCosts(convert(costs, {'cost': {'WardPerMinute': 600}}),
        convert(costs, {}), convert(costs, {'Speed': 0}))
    assert result['WardPerSecondCost'] == 10


def test_native_flat_reduction_clamps_cost_at_zero(costs):
    assert run(costs, 18, {'BASE': {'WardCost': -200}})['WardCost'] == 0
