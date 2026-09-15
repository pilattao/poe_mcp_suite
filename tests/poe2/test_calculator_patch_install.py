from pathlib import Path
import importlib.util
import pytest

SCRIPT=Path(__file__).resolve().parents[2]/'scripts/install_pob2_api.py'

def setup(tmp_path):
    spec=importlib.util.spec_from_file_location('installer',SCRIPT);api=importlib.util.module_from_spec(spec);spec.loader.exec_module(api)
    install=tmp_path/'runtime';source=tmp_path/'source';(install/'Modules').mkdir(parents=True);source.mkdir()
    main=b'main={}\nfunction main:Init()\nend\n\nfunction main:DetectUnicodeSupport()\nend\n';(install/'Modules/Main.lua').write_bytes(main);(install/'Path of Building-PoE2.exe').write_bytes(b'fixture')
    for name in ['BuildOps.lua','Handlers.lua','TcpServer.lua','Server.lua','GemEvaluator.lua','ItemEvaluator.lua','TreeEvaluator.lua','XmlSemantics.lua']:(source/name).write_text('return {}\n')
    model=b'-- stock\r\nlocal cost = 1\r\nreturn cost\r\n';(install/'Modules/ConfigOptions.lua').write_bytes(model)
    patches=[{'id':'test-cost','path':'Modules/ConfigOptions.lua','replacements':[{'old':'local cost = 1\n','new':'local cost = 2\n'}]}]
    return api,install,source,main,model,patches


def test_apply_reapply_and_uninstall_restore_exact_module_bytes(tmp_path):
    api,install,source,main,model,patches=setup(tmp_path)
    api.install_api(install,source,calculator_patches=patches)
    updated=(install/'Modules/ConfigOptions.lua').read_bytes()
    assert b'local cost = 2\r\n' in updated and b'poe2-mcp calculator patch' in updated
    api.install_api(install,source,calculator_patches=patches)
    assert (install/'Modules/ConfigOptions.lua').read_bytes()==updated
    api.uninstall_api(install)
    assert (install/'Modules/Main.lua').read_bytes()==main
    assert (install/'Modules/ConfigOptions.lua').read_bytes()==model


def test_unknown_target_layout_is_rejected_before_any_writes(tmp_path):
    api,install,source,main,model,patches=setup(tmp_path);patches[0]['replacements'][0]['old']='missing anchor'
    with pytest.raises(ValueError):api.install_api(install,source,calculator_patches=patches)
    assert not (install/'API').exists();assert (install/'Modules/Main.lua').read_bytes()==main;assert (install/'Modules/ConfigOptions.lua').read_bytes()==model


def test_later_user_edits_are_preserved_and_prevent_uninstall(tmp_path):
    api,install,source,_,_,patches=setup(tmp_path);api.install_api(install,source,calculator_patches=patches)
    edited=(install/'Modules/ConfigOptions.lua').read_bytes()+b'-- user edit\n';(install/'Modules/ConfigOptions.lua').write_bytes(edited)
    status=api.installation_status(install,source)
    assert status['main_matches'] and status['api_matches']
    assert status['calculator_matches'] is False and status['installed_integrity_verified'] is False
    assert status['mismatched_files']==['Modules/ConfigOptions.lua']
    with pytest.raises(ValueError,match='changed|modified'):api.uninstall_api(install)
    assert (install/'Modules/ConfigOptions.lua').read_bytes()==edited


def test_hash_constrained_patch_rejects_another_calculator_revision(tmp_path):
    api,install,source,main,model,patches=setup(tmp_path)
    patches[0]['original_sha256']='0'*64
    with pytest.raises(ValueError,match='revision'):api.install_api(install,source,calculator_patches=patches)
    assert (install/'Modules/ConfigOptions.lua').read_bytes()==model
    assert (install/'Modules/Main.lua').read_bytes()==main
    assert not (install/'API').exists()


def test_write_failure_rolls_back_main_api_and_calculator_modules(tmp_path,monkeypatch):
    api,install,source,main,model,patches=setup(tmp_path);original=api.atomic_write;failed=False
    def fail_once(path,data):
        nonlocal failed
        if path==install/'Modules/Main.lua' and not failed:
            failed=True;raise OSError('injected write failure')
        original(path,data)
    monkeypatch.setattr(api,'atomic_write',fail_once)
    with pytest.raises(OSError):api.install_api(install,source,calculator_patches=patches)
    assert (install/'Modules/Main.lua').read_bytes()==main
    assert (install/'Modules/ConfigOptions.lua').read_bytes()==model
    assert not (install/'API/Handlers.lua').exists()
    assert not (install/'API/.poe2-mcp-install.json').exists()
