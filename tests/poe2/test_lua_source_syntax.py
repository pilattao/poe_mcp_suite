"""Compile distributed PoB2 source without executing the GUI or loading builds."""
from pathlib import Path
from lupa.luajit21 import LuaRuntime

ROOT=Path(__file__).resolve().parents[2]

def test_all_checked_out_source_is_stock_luajit_syntax():
    source=ROOT/'PathOfBuilding/src'
    files=list(source.rglob('*.lua'))
    assert len(files)>100, 'A complete PoB2 source checkout is required for source acceptance'
    lua=LuaRuntime(unpack_returned_tuples=True)
    compile_file=lua.eval('function(path) local f,e=loadfile(path); return f~=nil,e end')
    errors=[]
    for path in files:
        ok,error=compile_file(str(path))
        if not ok:errors.append(error)
    assert not errors,'\n'.join(errors)


def test_source_export_preserves_missing_loadout_fields():
    # Real export module: nil lookups must remain nil for a missing loadout.
    lua=LuaRuntime(unpack_returned_tuples=True)
    lua.execute('''
      newClass=function() return {} end
      ConPrintf=function() end
    ''')
    lua.globals().lua_library_root=str(ROOT/'PathOfBuilding/runtime/lua')
    lua.execute("package.path = lua_library_root .. '/?.lua;' .. package.path")
    api=lua.execute((ROOT/'PathOfBuilding/src/Modules/BuildExportPoE2.lua').read_text())
    build=lua.eval('''{
      treeTab={},skillsTab={},itemsTab={},
      SyncLoadouts=function() end,
      controls={buildLoadouts={list={'Missing'}}},
      GetLoadoutByName=function() return nil end
    }''')
    result=api.GetLoadouts(build)
    assert result[1]['name']=='Missing'
    assert result[1]['specIndex'] is None

def test_source_export_skips_empty_groups_without_dropping_later_skills():
    lua=LuaRuntime(unpack_returned_tuples=True)
    lua.globals().lua_library_root=str(ROOT/'PathOfBuilding/runtime/lua')
    lua.execute("package.path = lua_library_root .. '/?.lua;' .. package.path; ConPrintf=function() end")
    api=lua.execute((ROOT/'PathOfBuilding/src/Modules/BuildExportPoE2.lua').read_text())
    lua.execute('''
      local active={level=20,quality=0,enabled=true,gemData={gameId='active-id'}}
      local support={level=1,quality=0,enabled=true,gemData={gameId='support-id',grantedEffect={support=true}}}
      local empty={enabled=true,gemList={{enabled=true}},displaySkillList={}}
      local valid={enabled=true,mainActiveSkill=1,gemList={active,{enabled=true},support},
        displaySkillList={{activeEffect={srcInstance=active}}}}
      fixtureBuild={skillsTab={skillSets={[1]={socketGroupList={empty,valid}}}}}
    ''')
    result=api.BuildTable(lua.globals().fixtureBuild,None,lua.eval('{skillSetId=1}'))
    assert len(result['skills'])==1
    assert result['skills'][1]['id']=='active-id'
    assert result['skills'][1]['support_skills'][1]=='support-id'
