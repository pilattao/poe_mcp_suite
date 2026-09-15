"""Isolated real PoB2 calculator. Only window/HTTP/formatting adapters are replaced.

No GUI socket is opened. Source reads use the checked-out PoB2; all file writes
and network access are rejected. ASCII fixtures use string for display-only UTF8.
"""
import os
from pathlib import Path
from lupa.luajit21 import LuaRuntime

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'PathOfBuilding/src'


def runtime(quiet=False, source=SOURCE, overrides=None):
    lua = LuaRuntime(unpack_returned_tuples=True)
    if quiet:
        lua.execute('print=function() end')
    lua.globals().item_test_source = str(source)
    lua.globals().item_test_overrides = table(lua, overrides or {})
    lua.globals().item_test_runtime = str(ROOT / 'PathOfBuilding/runtime')
    lua.globals().item_test_private = str(ROOT / '.local/item-evaluator-tests')
    previous = Path.cwd()
    os.chdir(source)
    try:
        lua.execute((SOURCE / '_SimpleGraphic.def.lua').read_text())
        lua.execute('''
          package.path=item_test_source..'/?.lua;'..item_test_runtime..'/lua/?.lua;'..item_test_runtime..'/lua/?/init.lua;'..package.path
          package.preload['lcurl.safe']=function() return {} end
          package.preload['lua-utf8']=function() return string end
          APP_NAME='PoB2 isolated item test'; __callbackTable__={}; arg={}
          launch={startTime=0,versionNumber='isolated',devMode=false,installedMode=true,continuousIntegrationMode=true}
          function GetScriptPath() return item_test_source end
          function GetRuntimePath() return item_test_runtime end
          function GetUserPath() return item_test_private end
          function launch:RegisterSubScript() end
          function launch:DownloadPage() error('Network forbidden in item test') end
          function launch:ShowErrMsg(...) error(string.format(...)) end
          local open=io.open
          io.open=function(path,mode)
            if mode and mode:match('[wa+]') then error('Item test blocked file write: '..path) end
            return open(path,mode)
          end
          os.remove=function() error('Item test blocked file removal') end
          local nativeLoadfile=loadfile
          loadfile=function(path,...)
            local text=item_test_overrides[path]
            if text then return loadstring(text,'@'..path) end
            return nativeLoadfile(path,...)
          end
          main=LoadModule('Modules/Main')
          main.ChangeUserPath=function(self) self.userPath=item_test_private..'/';self.buildPath=item_test_private..'/' end
          main:Init()
          main:SetMode('BUILD',false,'Item native fixture');main:OnFrame({})
          build=main.modes.BUILD
          build.characterLevel=90;build.characterLevelAutoMode=false
          build.calcsTab:BuildOutput()
        ''')
    finally:
        os.chdir(previous)
    return lua


def table(lua, value):
    if isinstance(value, dict):
        return lua.table_from({k: table(lua, v) for k, v in value.items()})
    if isinstance(value, list):
        return lua.table_from([table(lua, v) for v in value])
    return value
