from pathlib import Path
import importlib.util
import json
import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/install_pob2_api.py"

@pytest.fixture
def installation(tmp_path):
    install = tmp_path / "Path of Building Community (PoE2)"
    source = tmp_path / "api"
    (install / "Modules").mkdir(parents=True)
    source.mkdir()
    original = b"main = {}\nfunction main:Init()\n  self.ready = true\nend\n\nfunction main:DetectUnicodeSupport()\nend\n"
    (install / "Modules/Main.lua").write_bytes(original)
    (install / "Path of Building-PoE2.exe").write_bytes(b"fixture")
    for name in ["BuildOps.lua", "Handlers.lua", "TcpServer.lua", "Server.lua", "GemEvaluator.lua"]:
        (source / name).write_text("return {}\n")
    return install, source, original

def load_installer():
    assert SCRIPT.exists(), "PoB2 installer has not been implemented"
    spec = importlib.util.spec_from_file_location("pob2_installer", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def test_install_is_idempotent_and_uninstall_restores_exact_original(installation):
    install, source, original = installation
    api = load_installer()
    api.install_api(install, source)
    first = (install / "Modules/Main.lua").read_bytes()
    assert b"poe2-mcp API begin" in first
    assert first.count(b"poe2-mcp API begin") == 1
    api.install_api(install, source)
    assert (install / "Modules/Main.lua").read_bytes() == first
    api.uninstall_api(install)
    assert (install / "Modules/Main.lua").read_bytes() == original
    assert not (install / "API/Handlers.lua").exists()

def test_update_creates_a_new_original_backup(installation):
    install, source, original = installation
    api = load_installer()
    api.install_api(install, source)
    updated = original.replace(b"self.ready = true", b"self.ready = 'updated'")
    (install / "Modules/Main.lua").write_bytes(updated)
    api.install_api(install, source)
    api.uninstall_api(install)
    assert (install / "Modules/Main.lua").read_bytes() == updated

def test_incompatible_install_does_not_copy_or_patch_anything(installation):
    install, source, _ = installation
    bad = b"not a supported main module"
    (install / "Modules/Main.lua").write_bytes(bad)
    api = load_installer()
    with pytest.raises(ValueError):
        api.install_api(install, source)
    assert (install / "Modules/Main.lua").read_bytes() == bad
    assert not (install / "API").exists()

def test_uninstall_preserves_later_user_edits_instead_of_overwriting_them(installation):
    install, source, _ = installation
    api = load_installer()
    api.install_api(install, source)
    modified = (install / "Modules/Main.lua").read_bytes() + b"\n-- user edit\n"
    (install / "Modules/Main.lua").write_bytes(modified)
    with pytest.raises(ValueError):
        api.uninstall_api(install)
    assert (install / "Modules/Main.lua").read_bytes() == modified

def test_missing_source_leaves_original_untouched(installation):
    install, source, original = installation
    api = load_installer()
    (source / "Handlers.lua").unlink()
    with pytest.raises((ValueError, FileNotFoundError)):
        api.install_api(install, source)
    assert (install / "Modules/Main.lua").read_bytes() == original
    assert not (install / "API").exists()

def test_native_gem_evaluator_is_installed_verified_and_removed(installation):
    install, source, _ = installation
    api = load_installer()
    content = b"-- native evaluator fixture\nreturn {evaluate=function() return true end}\n"
    (source / "GemEvaluator.lua").write_bytes(content)
    api.install_api(install, source)
    assert (install / "API/GemEvaluator.lua").read_bytes() == content
    state = api.read_state(install)
    assert state["files"]["GemEvaluator.lua"] == api.sha(content)
    api.uninstall_api(install)
    assert not (install / "API/GemEvaluator.lua").exists()
