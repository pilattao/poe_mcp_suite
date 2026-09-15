"""Real PoB2 tree calculations on isolated source runtimes; never opens a GUI socket."""
import os
import importlib.util
from pathlib import Path
import pytest
from item_evaluator_runtime import runtime, table, SOURCE


@pytest.fixture
def native():
    previous = Path.cwd()
    lua = runtime(quiet=True)
    os.chdir(SOURCE)
    lua.execute('''
      function treeTestPath(id)
        local ids,attributes={},{}
        for _,node in ipairs(assert(build.spec.nodes[id].path)) do
          if not build.spec.allocNodes[node.id] then
            ids[#ids+1]=node.id
            if node.isAttribute then attributes[tostring(node.id)]='int' end
          end
        end
        return ids,attributes
      end
      function treeTestConnected(count)
        local seen,queue,ids,attributes={},{},{},{}
        for _,node in pairs(build.spec.allocNodes) do
          if node.type=='ClassStart' then queue[#queue+1]=node;seen[node.id]=true end
        end
        local cursor=1
        while queue[cursor] and #ids<count do
          for _,node in ipairs(queue[cursor].linked) do
            if not seen[node.id] and not node.ascendancyName and node.isFreeAllocate==nil and
              (node.type=='Normal' or node.type=='Notable') then
              seen[node.id]=true;queue[#queue+1]=node;ids[#ids+1]=node.id
              if node.isAttribute then attributes[tostring(node.id)]='int' end
              if #ids==count then break end
            end
          end
          cursor=cursor+1
        end
        assert(#ids==count,'Native fixture lacks enough connected ordinary nodes')
        return ids,attributes
      end
      function treeTestAudit()
        local records,seen={},{}
        local function visit(value)
          if type(value)~='table' or seen[value] then return end;seen[value]=true
          local row={ref=value,values={},meta=getmetatable(value)};records[#records+1]=row
          visit(row.meta)
          for k,v in pairs(value) do row.values[k]=v;visit(k);visit(v) end
        end
        visit({build,data,main.tree,GlobalCache,GlobalGemAssignments,modLib.parseModCache})
        return records
      end
      function treeTestUnchanged(records)
        for _,r in ipairs(records) do
          if getmetatable(r.ref)~=r.meta then return false,'metatable changed' end
          for k,v in pairs(r.values) do if rawget(r.ref,k)~=v then return false,'changed '..tostring(k) end end
          for k in pairs(r.ref) do if r.values[k]==nil then return false,'added '..tostring(k) end end
        end
        return true
      end
    ''')
    try:
        yield lua, lua.execute((SOURCE / 'API/BuildOps.lua').read_text())
    finally:
        os.chdir(previous)


def call(native, **params):
    lua, api = native
    result = api.calc_with(table(lua, params))
    if isinstance(result, tuple):
        assert result[0] is not None, result[1]
        return result[0]
    return result


def rejected(native, **params):
    lua, api = native
    result = api.calc_with(table(lua, params))
    assert isinstance(result, tuple) and result[0] is None, 'Invalid proposal was accepted'
    return str(result[1])


def path_request(native, target=1140, mode=0):
    lua, _ = native
    ids, attrs = lua.globals().treeTestPath(target)
    return dict(addNodes=list(ids.values()), weaponSets={str(i): mode for i in ids.values()}, attributeOverrides=dict(attrs.items()))


def assert_unchanged(lua, ledger):
    result = lua.globals().treeTestUnchanged(ledger)
    assert result is True, result


def test_explicit_weapon_context_and_full_numeric_output(native):
    for weapon in [1, 2]:
        out = call(native, weaponSet=weapon, useFullDPS=True)
        assert out['calculationContext']['weaponSet'] == weapon
        assert out['calculationContext']['treeVersion'] == '0_5'
        assert isinstance(out['Int'], (int, float))
        assert out['Life'] > 0
        assert len([v for _, v in out.items() if isinstance(v, (int, float))]) > 200
        assert isinstance(out['FullDPS'], (int, float))


def test_attribute_path_changes_only_its_weapon_set_with_real_native_math(native):
    baseline = {w: call(native, weaponSet=w) for w in [1, 2]}
    request = path_request(native, mode=1)
    first = call(native, weaponSet=1, **request)
    second = call(native, weaponSet=2, **request)
    assert first['Int'] == baseline[1]['Int'] + 5
    assert second['Int'] == baseline[2]['Int']
    shared = call(native, weaponSet=2, **path_request(native, mode=0))
    assert shared['Int'] == baseline[2]['Int'] + 5


def test_success_preserves_entire_graph_references_and_caches(native):
    lua, _ = native
    before = lua.eval("build:SaveDB('tree-test')")
    ledger = lua.globals().treeTestAudit()
    call(native, weaponSet=2, useFullDPS=True, **path_request(native, mode=2))
    assert_unchanged(lua, ledger)
    assert lua.eval("build:SaveDB('tree-test')") == before


def test_allocated_attribute_can_change_without_retaining_old_mods(native):
    lua, _ = native
    lua.execute("build.spec.allocMode=0;build.spec:AllocNode(build.spec.nodes[1140]);build.calcsTab:BuildOutput()")
    base = call(native, weaponSet=1)
    ledger = lua.globals().treeTestAudit()
    changed = call(native, weaponSet=1, attributeOverrides={'1140': 'int'})
    assert changed['Int'] == base['Int'] + 5
    assert changed['Str'] == base['Str'] - 5
    assert_unchanged(lua, ledger)


def test_unconnected_add_and_orphaning_remove_are_rejected(native):
    assert 'connect' in rejected(native, addNodes=[1140], attributeOverrides={'1140': 'int'}).lower()
    lua, _ = native
    lua.execute("build.spec:AllocNode(build.spec.nodes[1140]);build.calcsTab:BuildOutput()")
    parent = lua.eval("(function() for _,n in ipairs(build.spec.nodes[1140].linked) do if n.alloc and n.type~='ClassStart' then return n.id end end end)()")
    ledger = lua.globals().treeTestAudit()
    assert 'connect' in rejected(native, removeNodes=[parent]).lower()
    assert_unchanged(lua, ledger)


@pytest.mark.parametrize('weapon', [1, 2])
def test_weapon_budget_is_checked_even_when_other_weapon_is_requested(native, weapon):
    lua, _ = native
    ids, attributes = lua.globals().treeTestConnected(25)
    params = dict(addNodes=list(ids.values()), attributeOverrides=dict(attributes.items()),
                  weaponSets={str(i): weapon for i in ids.values()}, weaponSet=3-weapon)
    assert 'weapon' in rejected(native, **params).lower()


def test_level_budget_and_native_free_allocations(native):
    lua, _ = native
    lua.execute("build.spec:SelectClass(build.spec.tree.classNameMap.Witch);build.spec:SelectAscendClass(build.spec.tree.ascendNameMap['Blood Mage'].ascendClassId);build.characterLevel=1;build.characterLevelAutoMode=false;build.spec:BuildAllDependsAndPaths();build.calcsTab:BuildOutput()")
    ids, attributes = lua.globals().treeTestConnected(24)
    # Native Sanguimancy is free and must not consume a regular/ascendancy point.
    assert lua.eval("build.spec.nodes[8415].isFreeAllocate") is True
    assert call(native, weaponSet=1, addNodes=list(ids.values()), attributeOverrides=dict(attributes.items()))['Life'] > 0
    ids, attributes = lua.globals().treeTestConnected(25)
    assert 'budget' in rejected(native, weaponSet=2, addNodes=list(ids.values()), attributeOverrides=dict(attributes.items())).lower()


@pytest.mark.parametrize('params,reason', [
    ({'weaponSet': 3}, 'weapon'),
    ({'weaponSets': {'1140': 3}}, 'mode'),
    ({'attributeOverrides': {'56651': 'int'}}, 'attribute'),
    ({'attributeOverrides': {'1140': 'wis'}}, 'attribute'),
    ({'addNodes': [1140, 1140]}, 'duplicate'),
    ({'addNodes': [999999999]}, 'node'),
    ({'addNodes': [1140], 'removeNodes': [1140]}, 'both'),
    ({'masteryEffects': {'1140': 1}}, 'mastery'),
    ({'useFullDPS': 'true'}, 'boolean'),
])
def test_invalid_contract_is_rejected_without_side_effects(native, params, reason):
    lua, _ = native
    ledger = lua.globals().treeTestAudit()
    assert reason in rejected(native, **params).lower()
    assert_unchanged(lua, ledger)


def test_error_after_native_mutations_restores_all_shared_state(native):
    lua, _ = native
    lua.execute('''
      originalPerform=build.calcsTab.calcs.perform
      build.calcsTab.calcs.perform=function(env)
        env.spec.nodes[1140].modKey='trial-only'
        env.spec.nodes[1140].allocMode=2
        data.skills.ArcPlayer.levels[1].cost.Mana=999
        GlobalCache.treeTrial='trial-only'
        modLib.parseModCache.treeTrial={value='trial-only'}
        error('injected tree calculation failure')
      end
    ''')
    ledger = lua.globals().treeTestAudit()
    try:
        assert 'injected tree calculation failure' in rejected(native, weaponSet=2, **path_request(native, mode=2))
        assert_unchanged(lua, ledger)
    finally:
        lua.execute('build.calcsTab.calcs.perform=originalPerform')


def test_full_dps_tracks_real_skill_group_count_and_tree_damage(native):
    lua, api = native
    created = api.create_socket_group(table(lua, {'label': 'Tree DPS fixture', 'includeInFullDPS': True, 'count': 3}))
    assert not isinstance(created, tuple), created
    index = created['index']
    gem = api.add_gem(table(lua, {'groupIndex': index, 'gemName': 'Spark', 'level': 1, 'quality': 0}))
    assert not isinstance(gem, tuple), gem
    lua.globals().treeTestGroup = index
    lua.execute('build.mainSocketGroup=treeTestGroup;build.calcsTab:BuildOutput()')
    base = call(native, weaponSet=1, useFullDPS=True)
    assert base['CombinedDPS'] > 0
    assert base['FullDPS'] == pytest.approx(base['CombinedDPS'] * 3)
    changed = call(native, weaponSet=1, useFullDPS=True, **path_request(native, target=56651))
    assert changed['FullDPS'] > base['FullDPS']
    assert changed['FullDPS'] == pytest.approx(changed['CombinedDPS'] * 3)


def test_reassigning_existing_path_recomputes_both_weapon_contexts(native):
    lua, _ = native
    request = path_request(native)
    lua.execute("build.spec:AllocNode(build.spec.nodes[1140]);build.spec:SwitchAttributeNode(1140,3);build.spec:BuildAllDependsAndPaths();build.calcsTab:BuildOutput()")
    base = call(native, weaponSet=1)
    assignment = {str(id): 2 for id in request['addNodes']}
    assert call(native, weaponSet=1, weaponSets=assignment)['Int'] == base['Int'] - 5
    assert call(native, weaponSet=2, weaponSets=assignment)['Int'] == base['Int']
    assert 'connect' in rejected(native, weaponSet=2, weaponSets={'1140': 0, str(request['addNodes'][-1]): 2}).lower()


def test_added_attribute_requires_choice_and_class_start_cannot_be_reassigned(native):
    request = path_request(native)
    request.pop('attributeOverrides')
    assert 'attribute choice' in rejected(native, **request).lower()
    lua, _ = native
    root = lua.eval("(function() for id,n in pairs(build.spec.allocNodes) do if n.type=='ClassStart' then return id end end end)()")
    assert 'shared' in rejected(native, weaponSets={str(root): 1}).lower()
    assert 'class start' in rejected(native, removeNodes=[root]).lower()


def test_invalid_raw_params_and_sparse_arrays_do_not_become_noop_success(native):
    lua, api = native
    for raw in [False, 'invalid', 4]:
        result = api.calc_with(raw)
        assert isinstance(result, tuple) and result[0] is None
    result = api.calc_with(lua.eval('{addNodes={[2]=1140}}'))
    assert isinstance(result, tuple) and result[0] is None


def test_attribute_processing_failure_restores_live_aliases_touched_by_a_callback(native):
    lua, _ = native
    lua.execute('''
      oldTreeProcess=build.spec.tree.ProcessStats
      local remembered=build.spec.nodes[1140]
      build.spec.tree.ProcessStats=function(self,node)
        remembered.modKey='leaked callback key'
        remembered.sd[1]='leaked callback description'
        remembered.modList.leaked=true
        error('injected attribute processing failure')
      end
    ''')
    ledger = lua.globals().treeTestAudit()
    try:
        assert 'injected attribute processing failure' in rejected(native, **path_request(native))
        assert_unchanged(lua, ledger)
    finally:
        lua.execute('build.spec.tree.ProcessStats=oldTreeProcess')


def test_tree_helper_loads_from_buildops_sibling_with_no_api_search_path(native):
    lua, _ = native
    binding={'expectedBuildName':lua.eval('build.buildName'),'expectedXml':lua.eval("build:SaveDB('tree-binding')")}
    lua.globals().treeTestApiPath = str(SOURCE / 'API/BuildOps.lua')
    lua.execute("treeTestApi=dofile(treeTestApiPath);treeTestPackagePath=package.path;package.path='';package.loaded['API.TreeEvaluator']=nil")
    try:
        result = lua.globals().treeTestApi.calc_with(table(lua, {'weaponSet': 2, **binding}))
        assert isinstance(result, tuple) and result[0] is not None, result
        assert result[0]['calculationContext']['weaponSet'] == 2
    finally:
        lua.execute('package.path=treeTestPackagePath')


@pytest.mark.skipif(not os.getenv('POE2_TREE_PRIVATE_XML'), reason='Private native build acceptance is opt-in')
def test_private_native_build_preserves_skill_grants_and_every_shared_table(native):
    lua, _ = native
    lua.globals().treeTestPrivateXml = Path(os.environ['POE2_TREE_PRIVATE_XML']).read_text()
    lua.execute("main:SetMode('BUILD',false,'Private offline tree acceptance',treeTestPrivateXml);main:OnFrame({});build=main.modes.BUILD")
    # Save before the ledger: native SaveDB itself reparses items.
    before = lua.eval("build:SaveDB('tree-test')")
    ledger = lua.globals().treeTestAudit()
    binding = {'expectedBuildName': lua.eval('build.buildName'), 'expectedXml': before}
    first = call(native, weaponSet=1, useFullDPS=True, **binding)
    second = call(native, weaponSet=2, useFullDPS=True, **binding)
    assert first['calculationContext']['weaponSet'] == 1
    assert second['calculationContext']['weaponSet'] == 2
    assert first['CombinedDPS'] > 0 and second['CombinedDPS'] > 0
    node = lua.eval("(function() for id,n in pairs(build.spec.allocNodes) do if n.isAttribute and n.dn=='Intelligence' and (n.allocMode or 0)==0 then return id end end end)()")
    assert node is not None
    changed = call(native, weaponSet=1, useFullDPS=True, attributeOverrides={str(node): 'str'}, **binding)
    assert changed['Str'] > first['Str'] and changed['Int'] < first['Int']
    assert_unchanged(lua, ledger)
    assert lua.eval("build:SaveDB('tree-test')") == before


def test_optional_snapshot_binding_preserves_full_native_state(native):
    lua, _ = native
    xml = lua.eval("build:SaveDB('tree-binding')")
    name = lua.eval('build.buildName')
    ledger = lua.globals().treeTestAudit()
    assert call(native, weaponSet=2, expectedBuildName=name, expectedXml=xml)['calculationContext']['weaponSet'] == 2
    assert_unchanged(lua, ledger)
    assert 'name' in rejected(native, expectedBuildName=name.lower() if name != name.lower() else name+' ').lower()
    changed=xml.replace('<PathOfBuilding2>','<PathOfBuilding2 changedBinding="true">',1)
    assert changed!=xml
    assert 'xml' in rejected(native, expectedXml=changed).lower()
    assert call(native, weaponSet=1, expectedXml=xml+'\n')['Life'] > 0
    assert_unchanged(lua, ledger)
    # The old call shape remains a supported native calculation.
    assert call(native, weaponSet=1)['Life'] > 0


@pytest.mark.parametrize('params', [
    {'expectedBuildName': ''}, {'expectedBuildName': 3},
    {'expectedXml': False}, {'expectedXml': ''}, {'expectedXml': 'x'*(20*1024*1024+1)},
])
def test_bad_binding_inputs_are_rejected_without_echoing_the_payload(native, params):
    error = rejected(native, **params)
    assert len(error) < 400


def test_snapshot_mismatch_is_checked_before_any_native_calculation(native):
    lua, _ = native
    lua.execute("savedTreePerform=build.calcsTab.calcs.perform;build.calcsTab.calcs.perform=function() error('calculator must not run') end")
    try:
        error = rejected(native, expectedBuildName=lua.eval('build.buildName'), expectedXml='<stale/>')
        assert 'xml' in error.lower() and 'calculator must not run' not in error
    finally:
        lua.execute('build.calcsTab.calcs.perform=savedTreePerform')


def test_deadline_aborts_native_work_and_restores_graph_caches_and_debug_hook(native):
    lua, _ = native
    lua.execute('''
      treeRealClock=os.clock;treeTimeJump=0
      os.clock=function() return treeRealClock()+treeTimeJump end
      treeOldPerform=build.calcsTab.calcs.perform
      build.calcsTab.calcs.perform=function(env)
        env.spec.nodes[1140].modKey='deadline trial'
        modLib.parseModCache.deadlineTrial={changed=true}
        treeTimeJump=1000
        local sum=0;for i=1,500000 do sum=sum+i end
        return treeOldPerform(env)
      end
      treePriorHook=function() end;debug.sethook(treePriorHook,'',1000000)
    ''')
    ledger = lua.globals().treeTestAudit()
    try:
        error = rejected(native, weaponSet=2)
        assert 'time budget' in error.lower()
        assert_unchanged(lua, ledger)
        assert lua.eval("(function() local h,m,c=debug.gethook();return h==treePriorHook and m=='' and c==1000000 end)()")
    finally:
        lua.execute('debug.sethook();os.clock=treeRealClock;build.calcsTab.calcs.perform=treeOldPerform;treeTimeJump=0')
    assert call(native, weaponSet=1)['Life'] > 0, 'Timeout must release the busy guard'


@pytest.fixture
def xml_variants(native):
    lua, api = native
    # An inactive native config set is still part of the snapshot. Its unique
    # input map can reorder; unrelated collections/sequences cannot.
    lua.execute('''
      local c=build.configTab
      c:CreateConfigSet(77,'Inactive binding fixture')
      c.configSetOrderList[#c.configSetOrderList+1]=77
      c.configSets[77].input={alpha='A',beta='B'}
      c.configSets[77].placeholder={};c.configSets[77].customModsList={}
      local key='questAct 2Valley of the TitansMedallion'
      c.input[key]='30% increased Charm Charges Gained\\n\\t+1 Charm Slot'
      c:BuildModList()
      local save=build.SaveDB
      build.SaveDB=function(self,...)
        local result=save(self,...)
        return (result:gsub('</PathOfBuilding2>', '<FutureBinding flag="untouched"><Entry name="duplicate" value="first"/><Entry name="duplicate" value="second"/></FutureBinding></PathOfBuilding2>'))
      end
      function treeBindingVariant(text,kind)
        local root=assert(common.xml.ParseXML(text))[1]
        local function find(node,tag)
          if node.elem==tag then return node end
          for _,child in ipairs(node) do if type(child)=='table' then local n=find(child,tag);if n then return n end end end
        end
        if kind=='root-order' then root[1],root[#root]=root[#root],root[1]
        elseif kind=='unique-config-order' then
          for _,set in ipairs(find(root,'Config')) do if set.attrib.id=='77' then set[1],set[2]=set[2],set[1] end end
        elseif kind=='quest-newlines' then
          for _,set in ipairs(find(root,'Config')) do for _,input in ipairs(set) do
            if input.elem=='Input' and input.attrib.name=='questAct 2Valley of the TitansMedallion' then
              input.attrib.string=input.attrib.string:gsub('\\n\\t','  ')
            end
          end end
        elseif kind=='calcs' then
          local calcs=find(root,'Calcs');calcs[#calcs+1]={elem='Input',attrib={name='opaqueBindingInput',string='changed'}}
        elseif kind=='repeated-key-order' then
          local future=find(root,'FutureBinding');future[1],future[2]=future[2],future[1]
        elseif kind=='opaque-attribute' then find(root,'FutureBinding').attrib.flag='changed'
        elseif kind=='gem-order' then
          for _,set in ipairs(find(root,'Skills')) do if type(set)=='table' then for _,group in ipairs(set) do
            if type(group)=='table' and group.elem=='Skill' then
              local gems={};for i,child in ipairs(group) do if type(child)=='table' and child.elem=='Gem' then gems[#gems+1]=i end end
              if #gems>=2 then group[gems[1]],group[gems[2]]=group[gems[2]],group[gems[1]];return assert(common.xml.ComposeXML(root)) end
            end
          end end end
          error('Fixture needs two gems')
        else error('Unknown XML fixture variant') end
        return assert(common.xml.ComposeXML(root))
      end
    ''')
    group = api.create_socket_group(table(lua, {'label': 'XML sequence fixture'}))
    assert not isinstance(group, tuple), group
    for gem in ['Spark', 'Rapid Casting II']:
        assert not isinstance(api.add_gem(table(lua, {'groupIndex': group['index'], 'gemName': gem, 'level': 1})), tuple)
    return native


@pytest.mark.parametrize('kind', ['root-order', 'unique-config-order'])
def test_binding_accepts_only_semantically_unordered_native_maps(xml_variants, kind):
    lua, _ = xml_variants
    xml = lua.eval("build:SaveDB('semantic-binding')")
    variant = lua.globals().treeBindingVariant(xml, kind)
    assert variant != xml
    ledger = lua.globals().treeTestAudit()
    result = call(xml_variants, weaponSet=1, expectedBuildName=lua.eval('build.buildName'), expectedXml=variant)
    assert result['calculationContext']['weaponSet'] == 1
    assert_unchanged(lua, ledger)


@pytest.mark.parametrize('kind', ['quest-newlines', 'calcs', 'gem-order', 'repeated-key-order', 'opaque-attribute'])
def test_binding_rejects_semantic_changes_in_all_sections_before_calculation(xml_variants, kind):
    lua, _ = xml_variants
    xml = lua.eval("build:SaveDB('semantic-binding')")
    variant = lua.globals().treeBindingVariant(xml, kind)
    lua.execute("bindingOldPerform=build.calcsTab.calcs.perform;build.calcsTab.calcs.perform=function() error('binding rejection reached calculator') end")
    ledger = lua.globals().treeTestAudit()
    try:
        error = rejected(xml_variants, weaponSet=1, expectedBuildName=lua.eval('build.buildName'), expectedXml=variant)
        assert 'xml' in error.lower()
        assert 'binding rejection reached calculator' not in error
        assert_unchanged(lua, ledger)
    finally:
        lua.execute('build.calcsTab.calcs.perform=bindingOldPerform')


@pytest.mark.skipif(not os.getenv('POE2_TREE_RECORDED_XML'), reason='Recorded native snapshot binding replay is opt-in')
def test_recorded_snapshot_reimport_never_weakens_the_full_state_guard(native):
    lua, _ = native
    raw = Path(os.environ['POE2_TREE_RECORDED_XML']).read_text()
    lua.globals().treeRecordedXml = raw
    lua.execute("main:SetMode('BUILD',false,'PoE2 MCP Port Test',treeRecordedXml);main:OnFrame({});build=main.modes.BUILD")
    current=lua.eval("build:SaveDB('recorded-binding')")
    reference_path=SOURCE.parents[1]/'scripts/poe2_xml_semantics.py'
    spec=importlib.util.spec_from_file_location('tree_binding_reference',reference_path)
    reference=importlib.util.module_from_spec(spec);spec.loader.exec_module(reference)
    ledger = lua.globals().treeTestAudit()
    if reference.canonical(raw)!=reference.canonical(current):
        # Reimport can recompute stats, apply defaults, or reconcile skill grants.
        # This is a genuinely different state: reject the recorded request. Only
        # a SEPARATE request with an explicitly acquired current snapshot may run.
        assert 'xml' in rejected(native,weaponSet=1,expectedBuildName='PoE2 MCP Port Test',expectedXml=raw).lower()
        assert_unchanged(lua,ledger)
    result = call(native, weaponSet=1, useFullDPS=True, expectedBuildName='PoE2 MCP Port Test', expectedXml=current)
    assert result['calculationContext']['weaponSet'] == 1
    assert result['calculationContext']['treeVersion'] == '0_5'
    assert result['Life'] > 0
    assert_unchanged(lua, ledger)
    assert Path(os.environ['POE2_TREE_RECORDED_XML']).read_text() == raw
