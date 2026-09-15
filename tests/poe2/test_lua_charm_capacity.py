"""Charm capacity is a native modifier sum, not the belt's printed slot count."""
from pathlib import Path
import pytest
from lupa.luajit21 import LuaRuntime

SOURCE = Path(__file__).resolve().parents[2] / 'PathOfBuilding/src/API/BuildOps.lua'

@pytest.mark.parametrize('base,override,expected', [(3, None, 3), (2, None, 2), (2, 1, 1), (5, None, 3)])
def test_main_environment_capacity_includes_character_modifiers(base, override, expected):
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.execute('build={calcsTab={mainOutput={},mainEnv={modDB={}}}}')
    lua.globals().baseCapacity = base
    lua.globals().overrideCapacity = override
    lua.execute('''
      function build.calcsTab.mainEnv.modDB:Sum(kind,cfg,name)
        assert(kind=='BASE' and name=='CharmLimit');return baseCapacity
      end
      function build.calcsTab.mainEnv.modDB:Override(cfg,name)
        assert(name=='CharmLimit');return overrideCapacity
      end
    ''')
    api = lua.execute(SOURCE.read_text())
    assert api.export_stats(lua.eval('{"CharmLimit"}'))['CharmLimit'] == expected

def test_missing_native_modifiers_do_not_fabricate_capacity():
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.execute('build={calcsTab={mainOutput={}}}')
    api = lua.execute(SOURCE.read_text())
    assert api.export_stats(lua.eval('{"CharmLimit"}'))['CharmLimit'] is None
