"""Boundary tests use PoB2's real method signature, not a mock of the adapter."""
from pathlib import Path
import pytest
from lupa.luajit21 import LuaRuntime

SOURCE = Path(__file__).resolve().parents[2] / "PathOfBuilding/src/API/BuildOps.lua"

@pytest.fixture
def backend():
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.execute("""
      build = { targetVersion = '0_1', characterLevel = 93, buildName = 'PoE2 test',
        viewMode = 'TREE',
        calcsTab = { mainOutput = { Life=2502, Spirit=144, Ward=712, ManaRegenRecovery=45.8 },
          BuildOutput=function() end },
        spec = { treeVersion='0_5', curClassId=1, curAscendClassId=2, curSecondaryAscendClassId=0,
          allocNodes = { [101]={id=101,allocMode=1}, [102]={id=102,allocMode=2}, [103]={id=103,allocMode=0} },
          hashOverrides = { [103]={name='Attribute choice'} }, masterySelections = { [201]=301 },
          CountAllocNodes=function() return 3,8,0,0,1,1 end,
          BuildAllDependsAndPaths=function() end }
      }
      function build.spec:ImportFromNodeList(className,classId,ascendId,secondaryId,nodes,weaponSets,overrides,masteries,version)
        assert(type(weaponSets)=='table', 'PoB2 weaponSets argument missing')
        assert(type(masteries)=='table', 'PoB2 masteryEffects argument shifted')
        assert(version=='0_5', 'PoB2 treeVersion argument shifted')
        for key in pairs(self.masterySelections) do self.masterySelections[key]=nil end
        for key,value in pairs(masteries) do self.masterySelections[key]=value end
        self.received={classId=classId,ascendId=ascendId,weaponSets=weaponSets,overrides=overrides,masteries=masteries,version=version}
        self.allocNodes={}
        for _,id in ipairs(nodes) do self.allocNodes[id]={id=id,allocMode=weaponSets[id] or 0} end
      end
      build.spec.nodes=build.spec.allocNodes
    """)
    api = lua.execute(SOURCE.read_text())
    return lua, api

def test_tree_export_includes_weapon_assignments_and_counts(backend):
    _, api = backend
    tree = api.get_tree()
    assert tree["weaponSets"] is not None
    assert tree["weaponSets"][101] == 1
    assert tree["weaponSets"][102] == 2
    assert tree["weaponSet1PointsUsed"] == 1
    assert tree["weaponSet2PointsUsed"] == 1

def test_set_tree_preserves_class_modes_and_overrides_with_poe2_signature(backend):
    lua, api = backend
    result = api.set_tree(lua.eval("{nodes={101,102,103}}"))
    assert result is True
    received = lua.globals().build.spec.received
    assert received.classId == 1
    assert received.ascendId == 2
    assert received.weaponSets[101] == 1
    assert received.weaponSets[102] == 2
    assert received.overrides[103].name == "Attribute choice"
    assert received.masteries[201] == 301

def test_explicit_weapon_map_and_empty_masteries_are_not_replaced_by_old_values(backend):
    lua, api = backend
    assert api.set_tree(lua.eval("{nodes={101,102},weaponSets={['101']=2,['102']=1},masteryEffects={}}")) is True
    received = lua.globals().build.spec.received
    assert received.weaponSets[101] == 2
    assert received.weaponSets[102] == 1
    assert received.masteries[201] is None

def test_delta_removal_keeps_surviving_weapon_specialisations(backend):
    lua, api = backend
    result = api.update_tree_delta(lua.eval("{removeNodes={103}}"))
    assert result["removed"][1] == 103
    assert lua.globals().build.spec.allocNodes[101].allocMode == 1
    assert lua.globals().build.spec.allocNodes[102].allocMode == 2

def test_stats_identify_poe2_tree_and_resources(backend):
    _, api = backend
    result = api.export_stats()
    assert result["Spirit"] == 144
    assert result["Ward"] == 712
    assert result["ManaRegenRecovery"] == 45.8
    assert result["_meta"]["treeVersion"] == "0_5"
    assert result["_meta"]["game"] == "poe2"

def test_failed_simulation_restores_view_mode(backend):
    lua, api = backend
    lua.execute("""
      function build.calcsTab:GetMiscCalculator()
        return function() error('intentional calc failure') end, {CombinedDPS=100}
      end
    """)
    try:
        api.calc_with(lua.eval("{removeNodes={103}}"))
    except Exception:
        pass
    assert lua.globals().build.viewMode == "TREE"
def test_socket_loader_uses_absolute_runtime_path_when_cwd_differs():
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.execute("""
      package.preload.dkjson=function() return {encode=function() return '{}' end, decode=function() return {} end} end
      package.preload.socket=function() error('relative socket loader unavailable') end
      GetRuntimePath=function() return 'C:/PoB2 runtime' end
      GetScriptPath=function() return 'C:/PoB2 runtime' end
      package.loadlib=function(path, symbol)
        if path=='C:/PoB2 runtime/socket.dll' and symbol=='luaopen_socket_core' then
          return function() return {tcp=function() end} end
        end
        return nil, 'not found: '..path
      end
    """)
    module = lua.execute((SOURCE.parent / "TcpServer.lua").read_text())
    assert module.available is True

def test_skill_export_identifies_its_independent_active_set(backend):
    lua, api = backend
    lua.execute("build.skillsTab={activeSkillSetId=3,socketGroupList={}};build.calcsTab.input={}")
    assert api.get_skills()['activeSkillSetId'] == 3
