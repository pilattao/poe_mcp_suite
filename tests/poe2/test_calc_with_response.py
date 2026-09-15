from pathlib import Path
from lupa.luajit21 import LuaRuntime

ROOT=Path(__file__).resolve().parents[2]

def test_calculator_response_preserves_numeric_outputs_and_actual_context_only():
    lua=LuaRuntime(unpack_returned_tuples=True)
    lua.execute('''
      package.preload.dkjson=function() return {} end
      package.preload['API.BuildOps']=function() return {
        calc_with=function(params) return {
          FullDPS=123, Mana=0, Str=77, ReqStr=55, MissingFireResist=0,
          PhysicalMaximumHitTaken=999, ExtraPoints=3, PassivePointsToWeaponSetPoints=2,
          Minion={CombinedDPS=42,TotalDPS=40,callback=function() end},
          callback=function() end, infinity=math.huge, notNumber=0/0,
          calculationContext={weaponSet=2,treeVersion='0_5',callback=function() end},
        },{} end
      } end
    ''')
    h=lua.execute((ROOT/'PathOfBuilding/src/API/Handlers.lua').read_text())['handlers']
    result=h.calc_with(lua.eval('{weaponSet=1}'))
    assert result['ok'] is True
    out=result['output']
    assert out['FullDPS']==123 and out['Mana']==0 and out['ExtraPoints']==3
    assert out['Str']==77 and out['ReqStr']==55 and out['PhysicalMaximumHitTaken']==999
    assert out['MissingFireResist']==0 and out['PassivePointsToWeaponSetPoints']==2
    assert out['MinionCombinedDPS']==42 and out['Minion']['TotalDPS']==40
    assert out['calculationContext']['weaponSet']==2  # backend acknowledgement, not echoed request
    assert out['calculationContext']['treeVersion']=='0_5'
    assert out['callback'] is None and out['infinity'] is None and out['notNumber'] is None
    assert out['Minion']['callback'] is None
