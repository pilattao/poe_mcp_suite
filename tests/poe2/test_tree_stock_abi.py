"""Stock weapon-selection ABI with real native calculations underneath.

The facade intentionally ignores override.weaponSet and exposes no env.weaponSet.
The stock condition statement is executed verbatim from installed CalcSetup.lua.
No installed files or running PoB processes are changed.
"""
import os
from pathlib import Path
import pytest
from test_tree_evaluator import native, call, rejected, path_request, assert_unchanged

STOCK=Path(os.environ['POB2_STOCK_SOURCE']).expanduser() if os.environ.get('POB2_STOCK_SOURCE') else Path(__file__).parent / '.unconfigured-stock-source'


@pytest.fixture
def stock_abi(native):
    lua,api=native
    source=STOCK/'Modules/CalcSetup.lua'
    if not source.exists():pytest.skip('POB2_STOCK_SOURCE is required for the real stock weapon-condition statement')
    code=source.read_text()
    statement=next(line for line in code.splitlines() if 'modDB:NewMod("Condition:WeaponSet"' in line)
    lua.execute('stockWeaponCondition=function(build,modDB)\n'+statement+'\nend')
    lua.execute('''
      local source=build.calcsTab.calcs
      local function selected(b,override)
        local nativeOverride=copyTable(override or {},true)
        -- Stock ignores the request override. This selects the real engine
        -- solely from the detached item's flag, matching stock CalcSetup.
        nativeOverride.weaponSet=b.itemsTab.activeItemSet.useSecondWeaponSet and 2 or 1
        return nativeOverride
      end
      build.calcsTab.calcs={nativeDelegate=source,
        initEnv=function(b,mode,override,cache)
          local env,playerDB,enemyDB,minionDB=source.initEnv(b,mode,selected(b,override),cache)
          env.stockInternalWeapon=env.weaponSet
          env.modDB.mods['Condition:WeaponSet1']=nil
          env.modDB.mods['Condition:WeaponSet2']=nil
          stockWeaponCondition(b,env.modDB)
          env.weaponSet=nil
          return env,playerDB,enemyDB,minionDB
        end,
        perform=function(env,...)
          -- Only the underlying NEWER source calculator needs this field.
          -- It is absent at the evaluator boundary, as in actual stock.
          env.weaponSet=env.stockInternalWeapon
          local result=source.perform(env,...)
          env.weaponSet=nil
          return result
        end,
        calcFullDPS=function(b,mode,override,cache)
          return source.calcFullDPS(b,mode,selected(b,override),cache)
        end,
      }
    ''')
    return lua,api


@pytest.mark.parametrize('weapon',[1,2])
def test_stock_baseline_acknowledges_the_native_condition_not_the_request(stock_abi,weapon):
    lua,_=stock_abi
    before=lua.eval('build.itemsTab.activeItemSet.useSecondWeaponSet')
    ledger=lua.globals().treeTestAudit()
    result=call(stock_abi,weaponSet=weapon,useFullDPS=True)
    assert result['calculationContext']['weaponSet']==weapon
    assert result['Life']>0
    assert lua.eval('build.itemsTab.activeItemSet.useSecondWeaponSet')==before
    assert_unchanged(lua,ledger)


def test_stock_per_weapon_attribute_math_and_original_flag_are_preserved(stock_abi):
    lua,_=stock_abi
    baseline=call(stock_abi,weaponSet=1)
    proposal=path_request(stock_abi,mode=2)
    ledger=lua.globals().treeTestAudit()
    one=call(stock_abi,weaponSet=1,**proposal)
    two=call(stock_abi,weaponSet=2,**proposal)
    assert one['Int']==baseline['Int']
    assert two['Int']==baseline['Int']+5
    assert_unchanged(lua,ledger)


def test_stock_legacy_empty_request_uses_observed_selected_weapon(stock_abi):
    lua,_=stock_abi
    lua.execute('build.itemsTab.activeItemSet.useSecondWeaponSet=true')
    ledger=lua.globals().treeTestAudit()
    result=call(stock_abi)
    assert result['calculationContext']['weaponSet']==2
    assert_unchanged(lua,ledger)


@pytest.mark.parametrize('kind',['missing','both','wrong'])
def test_missing_ambiguous_or_wrong_native_flags_never_echo_requested_weapon(stock_abi,kind):
    lua,_=stock_abi
    lua.globals().badWeaponKind=kind
    lua.execute('''
      local perform=build.calcsTab.calcs.perform
      build.calcsTab.calcs.perform=function(env,...)
        perform(env,...)
        env.modDB.mods['Condition:WeaponSet1']=nil
        env.modDB.mods['Condition:WeaponSet2']=nil
        if badWeaponKind~='missing' then env.modDB:NewMod('Condition:WeaponSet1','FLAG',true,'Fixture') end
        if badWeaponKind=='both' then env.modDB:NewMod('Condition:WeaponSet2','FLAG',true,'Fixture') end
      end
    ''')
    ledger=lua.globals().treeTestAudit()
    assert 'weapon' in rejected(stock_abi,weaponSet=2).lower()
    assert_unchanged(lua,ledger)
