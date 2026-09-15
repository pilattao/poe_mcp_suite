"""Queued creation ABI tests; loads installed XML parser, class maps and importer.
No running PoB process, build file or calculated engine output is used.
"""
import os
import re
from pathlib import Path
import pytest
from lupa.luajit21 import LuaRuntime

ROOT = Path(__file__).resolve().parents[2]
NATIVE = Path(os.environ.get('POB2_SOURCE') or os.environ.get('POB_INSTALL_DIR') or ROOT/'PathOfBuilding/src')
if not (NATIVE/'Classes').is_dir() and (NATIVE/'src/Classes').is_dir():
    NATIVE = NATIVE/'src'
LUA_LIB = NATIVE/'lua' if (NATIVE/'lua').is_dir() else NATIVE.parent/'runtime/lua'

@pytest.fixture
def backend():
    if not (NATIVE/'TreeData/0_5/tree.lua').exists():
        pytest.skip('PoB2 source with TreeData required')
    lua=LuaRuntime(unpack_returned_tuples=True)
    lua.globals().nativeTree=lua.execute((NATIVE/'TreeData/0_5/tree.lua').read_text())
    lua.globals().xmlParser=lua.execute((LUA_LIB/'xml.lua').read_text())
    lua.execute('''
      common={xml=xmlParser};latestTreeVersion='0_5';liveTargetVersion='0_1'
      function copyTable(t,shallow) local out={} for k,v in pairs(t) do out[k]=shallow and v or (type(v)=='table' and copyTable(v) or v) end return out end
      function wipeTable(t) for k in pairs(t) do t[k]=nil end return t end
      nativeTree.treeVersion=latestTreeVersion
    ''')
    # Execute the installed remapping from integerId and class/ascendancy lookup construction.
    source=(NATIVE/'Classes/PassiveTree.lua').read_text()
    start=source.index('\tlocal classes = { }')
    end=source.index('\n\tself.skillsPerOrbit',start)
    lua.execute('local self=nativeTree\n'+source[start:end])
    source=(NATIVE/'Classes/PassiveSpec.lua').read_text()
    method=re.search(r'^function PassiveSpecClass:ImportFromNodeList\(.*?^end',source,re.M|re.S).group()
    lua.execute('PassiveSpecClass={};local t_insert=table.insert\n'+method)
    lua.execute('''
      function freshBuild(name)
        local b={buildName=name,targetVersion='0_1',abortSave=false,characterLevel=1,importTab={},calcsTab={mainOutput={},input={},BuildOutput=function() end},treeTab={}}
        local spec=setmetatable({tree=nativeTree,treeVersion='0_5',nodes={},allocNodes={},hashOverrides={},masterySelections={},allocExtendedNodes={},allocSubgraphNodes={},build=b}, {__index=PassiveSpecClass})
        spec.ResetNodes=function(self) self.allocNodes={} end
        spec.SelectClass=function(self,id) self.curClassId=id;self.curClassName=self.tree.classes[id].name end
        spec.SelectAscendClass=function(self,id) self.curAscendClassId=id;self.curAscendClassName=self.tree.classes[self.curClassId].classes[id].name end
        spec.SelectSecondaryAscendClass=function(self,id) self.curSecondaryAscendClassId=id end
        spec.BuildAllDependsAndPaths=function() end
        spec.SetWindowTitleWithBuildClass=function() end
        spec.AddUndoState=function() end
        b.UpdateClassDropdowns=function() end
        b.spec=spec;spec:SelectClass(nativeTree.classNameMap.Warrior);spec:SelectAscendClass(0)
        return b
      end
      build=freshBuild('Previous')
      main={mode='BUILD',modes={BUILD=build},LoadTree=function() return nativeTree end,
        SetMode=function(self,mode,...) self.newMode=mode;self.newModeArgs={...};queuedCount=(queuedCount or 0)+1 end}
      function frame()
        main.mode=main.newMode;main.newMode=nil
        local args=main.newModeArgs
        build=freshBuild(args[2]);build.dbFileName=args[1];main.modes.BUILD=build
      end
    ''')
    api=lua.execute((ROOT/'PathOfBuilding/src/API/BuildOps.lua').read_text())
    return lua,api


def rejected(result):
    assert isinstance(result,tuple) and result[0] is None,result
    return result[1]


def status(lua,api,request):
    return api.open_build_xml(lua.table_from({'statusOnly':True,'requestId':request['requestId']}))


def test_blank_selects_installed_class_and_ascendancy_after_queue(backend):
    lua,api=backend
    request=api.open_build_xml(lua.eval('{className="Witch",ascendancy="Blood Mage"}'))
    assert request['requestId'] is not None
    assert request['ready'] is False
    assert lua.eval('build.buildName')=='Previous'
    assert status(lua,api,request)['ready'] is False
    lua.execute('frame()')
    result=status(lua,api,request)
    assert result['ready'] is True
    assert lua.eval('build.spec.curClassId')==lua.eval('nativeTree.classNameMap.Witch')
    assert lua.eval('build.spec.curAscendClassName')=='Blood Mage'
    assert lua.eval('build.spec.treeVersion')=='0_5'
    # The real ImportFromNodeList iterates masteryEffects and weaponSets: shifted args crash.
    assert lua.eval('next(build.spec.masterySelections)') is None


@pytest.mark.parametrize('params',['{className="Scion"}','{className="Witch",ascendancy="Titan"}','{className="Witch",ascendancy="not real"}','{ascendancy="Blood Mage"}'])
def test_invalid_names_do_not_replace_current_build(backend,params):
    lua,api=backend
    rejected(api.open_build_xml(lua.eval(params)))
    assert lua.eval('queuedCount') is None
    assert lua.eval('build.buildName')=='Previous'


def test_xml_is_passed_whole_without_class_rebuild(backend):
    lua,api=backend
    text='<PathOfBuilding2><Build targetVersion="0_1"/><Tree/><Skills/><Items/><Config/><Future note="keep"/></PathOfBuilding2>'
    request=api.open_build_xml(lua.table_from({'xml':text,'name':'Loaded'}))
    assert lua.eval('main.newModeArgs[3]')==text
    lua.execute('frame();build.spec.ImportFromNodeList=function() error("must not rebuild loaded XML") end')
    assert status(lua,api,request)['ready'] is True


@pytest.mark.parametrize('text',['','<PathOfBuilding/>','{"pob_xml":"not XML"}','<PathOfBuilding2><bad></PathOfBuilding2>'])
def test_invalid_xml_never_becomes_blank_build(backend,text):
    lua,api=backend
    rejected(api.open_build_xml(lua.table_from({'xml':text})))
    assert lua.eval('queuedCount') is None


def test_pending_and_unknown_open_tokens_cannot_replace_or_complete(backend):
    lua,api=backend
    request=api.open_build_xml(lua.eval('{className="Witch"}'))
    rejected(api.open_build_xml(lua.eval('{className="Warrior"}')))
    rejected(api.open_build_xml(lua.eval('{statusOnly=true,requestId="wrong"}')))
    assert lua.eval('queuedCount')==1
    lua.execute('frame()')
    assert status(lua,api,request)['ready'] is True
    lua.execute('build.spec.ImportFromNodeList=function() error("double application") end')
    assert status(lua,api,request)['ready'] is True


def test_failed_native_open_is_reported_as_failure(backend):
    lua,api=backend
    request=api.open_build_xml(lua.eval('{className="Witch"}'))
    lua.execute('main.newMode=nil;main.mode="LIST"')
    assert 'build' in rejected(status(lua,api,request)).lower()


def handlers_for(lua,api):
    lua.globals().testOps=api
    lua.globals().jsonModule=lua.execute((LUA_LIB/'dkjson.lua').read_text())
    lua.execute("package.preload['API.BuildOps']=function() return testOps end;package.preload.dkjson=function() return jsonModule end")
    return lua.execute((ROOT/'PathOfBuilding/src/API/Handlers.lua').read_text())['handlers']


def test_handler_preserves_queue_token_and_capability(backend):
    lua,api=backend
    handlers=handlers_for(lua,api)
    assert handlers.version(lua.eval('{}'))['version']['features']['queuedBuildOpen'] is True
    request=handlers.open_build_xml(lua.eval('{className="Witch"}'))
    assert request['requestId'] is not None
    lua.execute('frame()')
    result=handlers.get_build_open_status(lua.table_from({'requestId':request['requestId']}))
    assert result['ready'] is True


def test_pending_open_rejects_other_api_build_operations(backend):
    lua,api=backend
    handlers=handlers_for(lua,api)
    handlers.open_build_xml(lua.eval('{className="Witch"}'))
    result=handlers.get_stats(lua.eval('{}'))
    assert result['ok'] is False
    assert 'pending' in result['error']


def test_legacy_split_import_payloads_fail_before_control_changes(backend):
    lua,api=backend
    handlers=handlers_for(lua,api)
    lua.execute('build.importTab.controls={charImportTreeClearJewels={state=false}}')
    result=handlers.import_passive_tree(lua.eval('{json=\'{"hashes":[1],"items":[]}\',char_data={name="Old format",class="Witch"}}'))
    assert result['ok'] is False
    assert 'PoB2' in result['error']
    assert lua.eval('build.importTab.controls.charImportTreeClearJewels.state') is False


def test_complete_character_uses_actual_native_passive_import_and_weapon_maps(backend):
    lua,api=backend
    source=(NATIVE/'Classes/ImportTab.lua').read_text()
    method=re.search(r'^function ImportTabClass:ImportPassiveTreeAndJewels\(.*?^end',source,re.M|re.S).group()
    lua.execute('ImportTabClass={};local t_insert=table.insert\n'+method)
    lua.execute('''
      colorCodes={POSITIVE=''}
      build.importTab=setmetatable({build=build,controls={charImportTreeClearJewels={state=false}},
        ImportQuestRewardConfig=function() end}, {__index=ImportTabClass})
      build.itemsTab={slots={},PopulateSlots=function() end,AddUndoState=function() end}
      build.treeTab.controls={versionSelect={}};build.treeTab.treeVersions={1}
      build.spec.nodes={[100]={id=100},[101]={id=101}}
      build.configTab={UpdateLevel=function() end,varControls={resistancePenalty={SetSel=function() end}}}
      build.controls={characterLevel={SetText=function() end}}
      build.EstimatePlayerProgress=function() end
      main.SetWindowTitleSubtext=function() end
    ''')
    handlers=handlers_for(lua,api)
    result=handlers.import_passive_tree(lua.eval('''{json='{"character":{"name":"Native ABI","class":"Blood Mage","level":50,"league":"Test","jewels":[],"passives":{"hashes":[100],"specialisations":{"set1":[101]},"skill_overrides":{},"quest_stats":{},"jewel_data":{}}}}',clear_jewels=false}'''))
    assert result['ok'] is True,result['error']
    assert lua.eval('build.spec.curClassName')=='Witch'
    assert lua.eval('build.spec.curAscendClassName')=='Blood Mage'
    assert lua.eval('build.spec.allocNodes[101].allocMode')==1


def test_items_import_keeps_equipment_and_skill_arrays_in_one_native_argument(backend):
    lua,api=backend
    handlers=handlers_for(lua,api)
    lua.execute('''
      build.importTab.controls={}
      build.importTab.ImportItemsAndSkills=function(self,...)
        assert(select('#',...)==1,'PoB2 ImportItemsAndSkills takes one argument')
        receivedCharacter=(...)
      end
    ''')
    result=handlers.import_items_skills(lua.eval('''{json='{"character":{"name":"Native ABI","class":"Witch","level":50,"equipment":[{"id":"weapon"}],"skills":[{"id":"skill"}]}}'}'''))
    assert result['ok'] is True,result['error']
    assert lua.eval('receivedCharacter.equipment[1].id')=='weapon'
    assert lua.eval('receivedCharacter.skills[1].id')=='skill'


@pytest.mark.parametrize('class_name,ascendancy',[
    ('Ranger','Deadeye'),('Huntress','Amazon'),('Warrior','Titan'),
    ('Mercenary','Witchhunter'),('Druid','Oracle'),('Witch','Blood Mage'),
    ('Sorceress','Stormweaver'),('Monk','Invoker'),
])
def test_all_eight_class_creation_pairs_use_native_metadata(backend,class_name,ascendancy):
    lua,api=backend
    request=api.open_build_xml(lua.table_from({'className':class_name,'ascendancy':ascendancy}))
    lua.execute('frame()')
    result=status(lua,api,request)
    assert result['ready'] is True
    assert result['info']['className']==class_name
    assert result['info']['ascendClassName']==ascendancy


def test_conversion_pending_cannot_use_stale_calcs_from_prior_build(backend):
    lua,api=backend
    request=api.open_build_xml(lua.eval('{className="Witch"}'))
    lua.execute('frame();build.targetVersion=nil')
    rejected(status(lua,api,request))


def test_native_initialization_must_finish_before_marking_ready(backend):
    lua,api=backend
    request=api.open_build_xml(lua.eval('{className="Witch"}'))
    lua.execute('frame();build.abortSave=true')
    assert status(lua,api,request)['ready'] is False
    lua.execute('build.abortSave=false')
    assert status(lua,api,request)['ready'] is True


def test_multiple_xml_roots_do_not_open(backend):
    lua,api=backend
    rejected(api.open_build_xml(lua.eval('{xml="<PathOfBuilding2/><Other/>"}')))
    assert lua.eval('queuedCount') is None
