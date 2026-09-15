from pathlib import Path
from lupa.luajit21 import LuaRuntime

SOURCE=Path(__file__).resolve().parents[2]/'PathOfBuilding/src/API/TcpServer.lua'

def test_nonblocking_partial_writes_keep_every_byte_in_order():
    lua=LuaRuntime(unpack_returned_tuples=True)
    lua.execute('''
      payload=string.rep('x', 600000)
      received=''; sends=0; reads=0; accepted=false
      ConPrintf=function() end
      package.preload.dkjson=function() return {
        encode=function(v) if v.ready then assert(v.version.apiVersion=='1.3.0') end;return v.ready and 'ready' or v.message end,
        decode=function(line) return {action=line} end
      } end
      client={settimeout=function() end,close=function() closed=true end}
      function client:send(data)
        sends=sends+1
        if sends%3==0 then return nil,'timeout',0 end
        local n=math.min(4093,#data)
        received=received..data:sub(1,n)
        if n<#data then return nil,'timeout',n end
        return n
      end
      function client:receive(n)
        reads=reads+1
        return nil,'timeout', reads==2 and 'echo\\n' or ''
      end
      package.preload.socket=function() return {bind=function() return {
        settimeout=function() end,close=function() end,
        accept=function() if not accepted then accepted=true;return client end end
      } end} end
      handlers={echo=function() return {message=payload} end}
    ''')
    api=lua.execute(SOURCE.read_text())
    assert api.init(lua.globals().handlers,55698)
    for _ in range(250):api.pump()
    assert lua.globals().received=='ready\n'+'x'*600000+'\n'
