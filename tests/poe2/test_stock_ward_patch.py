"""Validate the exact stock backport in memory; never write an installed/runtime file."""
import hashlib
import json
import os
import re
from pathlib import Path
import pytest
from lupa.luajit21 import LuaRuntime
from test_native_ward_costs import build_cost_runtime, convert, run, SOURCE

HERE=Path(__file__).parent
PATCH=(HERE/'fixtures/stock-ward-costs.patch').read_text()
MANIFEST=json.loads((HERE/'fixtures/stock-ward-costs.json').read_text())
STOCK=Path(os.environ['POB2_STOCK_SOURCE']).expanduser() if os.environ.get('POB2_STOCK_SOURCE') else Path(__file__).parent / '.unconfigured-stock-source'


def sections():
    files={}; current=None
    for line in PATCH.splitlines(True):
        if line.startswith('--- a/'):
            current=line.removeprefix('--- a/').strip();files[current]=[]
        elif current and not line.startswith('+++ b/'):
            files[current].append(line)
    return files


def apply_exact(text, patch_lines, reverse=False):
    original=text.splitlines(True);result=[];cursor=0;index=0
    while index<len(patch_lines):
        match=re.fullmatch(r'@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@.*\n',patch_lines[index])
        assert match,patch_lines[index]
        start=int(match[3] if reverse else match[1])-1
        result.extend(original[cursor:start]);cursor=start;index+=1
        while index<len(patch_lines) and not patch_lines[index].startswith('@@'):
            line=patch_lines[index];prefix=line[0];value=line[1:]
            if reverse:prefix={'+':'-','-':'+',' ':' '}[prefix]
            if prefix in [' ','-']:
                assert original[cursor]==value,'stock patch context mismatch'
                cursor+=1
            if prefix in [' ','+']:result.append(value)
            index+=1
    result.extend(original[cursor:]);return ''.join(result)


@pytest.fixture(scope='module')
def stock_files():
    if not (STOCK/'Modules/CalcOffence.lua').exists():pytest.skip('Set POB2_STOCK_SOURCE to stock PoB2 for in-memory patch tests')
    original={entry['path']:(STOCK/entry['path']).read_bytes() for entry in MANIFEST['files']}
    patched={name:apply_exact(value.decode(),sections()[name]) for name,value in original.items()}
    return original,patched


def test_stock_hashes_forward_patch_and_byte_exact_reverse(stock_files):
    original,patched=stock_files
    for entry in MANIFEST['files']:
        name=entry['path']
        assert hashlib.sha256(original[name]).hexdigest()==entry['original_sha256']
        assert hashlib.sha256(patched[name].encode()).hexdigest()==entry['patched_sha256']
        assert apply_exact(patched[name],sections()[name],reverse=True).encode()==original[name]
        assert (STOCK/name).read_bytes()==original[name]


def test_all_four_patched_stock_files_compile_as_luajit(stock_files):
    _,patched=stock_files
    lua=LuaRuntime(unpack_returned_tuples=True)
    compile_source=lua.eval('function(text)local f,e=loadstring(text);return f~=nil,e end')
    for name,text in patched.items():
        ok,error=compile_source(text)
        assert ok,(name,error)


@pytest.mark.parametrize('level,mods,expected',[(18,{},134),(19,{},144),
    (18,{'MORE':{'Cost':-40}},81),(19,{'MORE':{'Cost':-40}},87),
    (18,{'MORE':{'Cost':-40},'INC':{'WardCostEfficiency':100}},41),
    (19,{'MORE':{'Cost':-40},'INC':{'CostEfficiency':100}},44),
    (18,{'MORE':{'Cost':-40},'INC':{'ManaCostEfficiency':100}},81)])
def test_backported_ward_model_matches_native_fork(stock_files,level,mods,expected):
    _,patched=stock_files
    stock=build_cost_runtime(STOCK,patched['Modules/CalcOffence.lua'])
    native=build_cost_runtime(SOURCE)
    assert run(stock,level,mods)['WardCost']==expected
    assert run(native,level,mods)['WardCost']==expected


@pytest.mark.parametrize('mods',[{}, {'MORE':{'Cost':-40},'INC':{'ManaCostEfficiency':50,'LifeCostEfficiency':25}},
    {'BASE':{'HybridManaAndLifeCost_Life':50,'ManaCost':3},'MORE':{'Cost':-30}},
    {'MORE':{'SupportManaMultiplier':20,'Cost':-35,'ManaCost':50},'INC':{'CostEfficiency':17,'LifeCost':30}},
    {'BASE':{'WardCostAsPercentOfLifeCost':20,'WardCostAsPercentOfManaCost':20}}])
def test_existing_stock_resource_outputs_are_unchanged(stock_files,mods):
    original,patched=stock_files
    old=build_cost_runtime(STOCK,original['Modules/CalcOffence.lua'].decode())
    new=build_cost_runtime(STOCK,patched['Modules/CalcOffence.lua'])
    data={'cost':{'Mana':134,'Life':40,'ES':20,'Soul':10,'Rage':2}}
    output={'Speed':2,'Cooldown':5.3}
    before=old.globals().calculateNativeCosts(convert(old,data),convert(old,mods),convert(old,output))
    after=new.globals().calculateNativeCosts(convert(new,data),convert(new,mods),convert(new,output))
    for key,value in before.items():assert after[key]==value,(key,value,after[key])
