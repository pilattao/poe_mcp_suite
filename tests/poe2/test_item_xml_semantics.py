"""Snapshot binding follows the native XML parser, not standard XML whitespace rules."""
import base64
import importlib.util
import random
from pathlib import Path

import pytest
from lupa.luajit21 import LuaRuntime

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / 'PathOfBuilding/src/API/XmlSemantics.lua'
spec = importlib.util.spec_from_file_location('xml_reference', ROOT / 'scripts/poe2_xml_semantics.py')
reference = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reference)


@pytest.fixture(scope='module')
def semantics():
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.globals().runtime_dir = str(ROOT / 'PathOfBuilding/runtime/lua')
    lua.execute("package.path=runtime_dir..'/?.lua;'..package.path")
    return lua.execute(MODULE.read_text())


def same(semantics, a, b, expected):
    assert (reference.canonical(a) == reference.canonical(b)) is expected
    result = semantics.equivalent(a, b)
    if isinstance(result, tuple):
        assert result[1] is None, result
        result = result[0]
    assert result is expected


def document(body):
    return '<PathOfBuilding2>' + body + '</PathOfBuilding2>'


def tree_url(nodes=(1, 200, 65530), clusters=(2, 10), pairs=((7, 80), (9, 90)), header=b'\x00\x00\x00\x06\x02\x01', suffix=b''):
    raw = header + bytes([len(nodes)]) + b''.join(n.to_bytes(2, 'big') for n in nodes)
    raw += bytes([len(clusters)]) + b''.join(n.to_bytes(2, 'big') for n in clusters)
    raw += bytes([len(pairs)]) + b''.join(effect.to_bytes(2, 'big') + node.to_bytes(2, 'big') for effect, node in pairs)
    return 'https://www.pathofexile.com/passive-skill-tree/' + base64.urlsafe_b64encode(raw + suffix).decode()


def test_known_unique_maps_and_root_sections_can_change_iteration_order(semantics):
    a = document('<Build level="90"/><Config><ConfigSet id="1"><Input name="a" number="1"/><Placeholder name="a" number="2"/><Input name="b" string="x"/></ConfigSet></Config><Items><ItemSet><Slot name="Helmet" itemId="1"/><Slot name="Belt" itemId="2"/></ItemSet></Items>')
    b = document('<Items><ItemSet><Slot itemId="2" name="Belt"/><Slot itemId="1" name="Helmet"/></ItemSet></Items><Config><ConfigSet id="1"><Input string="x" name="b"/><Placeholder number="2" name="a"/><Input number="1" name="a"/></ConfigSet></Config><Build level="90"/>')
    same(semantics, a, b, True)
    same(semantics, a, b.replace('itemId="2"', 'itemId="99"'), False)


def test_calcs_input_map_order_preserves_section_order_and_duplicate_keys(semantics):
    inputs = '<Input name="skill_number" number="3"/><Input name="misc_buffMode" string="EFFECTIVE"/>'
    reversed_inputs = '<Input name="misc_buffMode" string="EFFECTIVE"/><Input name="skill_number" number="3"/>'
    sections = '<Section id="SkillSelect" subsection="SkillHitDamage"/><Section id="SkillSelect" subsection="SkillDotDamage"/>'
    def xml(children):
        return document('<Calcs>' + children + '</Calcs>')
    assert semantics.equivalent(xml(inputs + sections), xml(reversed_inputs + sections)) is True
    assert semantics.equivalent(xml(inputs + sections), xml(reversed_inputs.replace('number="3"', 'number="4"') + sections)) is False
    reordered_sections = '<Section id="SkillSelect" subsection="SkillDotDamage"/><Section id="SkillSelect" subsection="SkillHitDamage"/>'
    assert semantics.equivalent(xml(inputs + sections), xml(inputs + reordered_sections)) is False
    duplicate = '<Input name="skill_number" number="4"/>'
    assert semantics.equivalent(xml(inputs + sections + duplicate), xml(reversed_inputs + sections + duplicate)) is False


@pytest.mark.parametrize('before,after', [
    ('Charges\n\t+1 Charm Slot', 'Charges  +1 Charm Slot'),
    ('Charges\r\n+1 Charm Slot', 'Charges\n+1 Charm Slot'),
    (' +1 Charm Slot', '+1 Charm Slot'),
    ('Charges\n+1 Charm Slot', 'Charges&#10;+1 Charm Slot'),
])
def test_literal_attribute_whitespace_cannot_be_flattened(semantics, before, after):
    def xml(value):
        return document(f'<Config><ConfigSet><Input name="quest" string="{value}"/></ConfigSet></Config>')
    same(semantics, xml(before), xml(after), False)


@pytest.mark.parametrize('body', [
    '<Skills><Skill><Gem nameSpec="Spark"/><Gem nameSpec="Rapid Casting"/></Skill></Skills>',
    '<Skills><SkillSet id="1"/><SkillSet id="2"/></Skills>',
    '<Items><ItemSet id="1"/><ItemSet id="2"/></Items>',
    '<Config><ConfigSet id="1"/><ConfigSet id="2"/></Config>',
    '<Config><ConfigSet><Input name="x" number="1"/><Input name="x" number="2"/></ConfigSet></Config>',
    '<Items><ItemSet><Slot name="Ring 1" itemId="1"/><Slot name="Ring 1" itemId="2"/></ItemSet></Items>',
    '<Build level="1"/><Build level="2"/>',
    '<Extension><Input name="x" number="1"/><Input name="y" number="2"/></Extension>',
])
def test_sequences_and_repeated_keys_remain_ordered(semantics, body):
    import re
    children = re.findall(r'<[^<>]+/>', body)
    assert len(children) == 2
    reordered = body.replace(children[0], '\x00', 1).replace(children[1], children[0], 1).replace('\x00', children[1], 1)
    same(semantics, document(body), document(reordered), False)


def test_mixed_or_unnamed_map_children_are_not_silently_sorted(semantics):
    for extra in ['literal text', '<CustomModifierBlock title="custom"/>']:
        a = document(f'<Config><ConfigSet><Input name="a" number="1"/>{extra}<Input name="b" number="2"/></ConfigSet></Config>')
        b = document(f'<Config><ConfigSet><Input name="b" number="2"/>{extra}<Input name="a" number="1"/></ConfigSet></Config>')
        same(semantics, a, b, False)


def test_node_sets_preserve_membership_and_duplicates(semantics):
    a = document('<Tree><Spec nodes="3,1,2,2"><Overrides><AttributeOverride strNodes="8,7" dexNodes="6,5" intNodes="4,3"/></Overrides></Spec></Tree>')
    b = document('<Tree><Spec nodes="2,3,2,1"><Overrides><AttributeOverride intNodes="3,4" dexNodes="5,6" strNodes="7,8"/></Overrides></Spec></Tree>')
    same(semantics, a, b, True)
    same(semantics, a, b.replace('2,3,2,1', '3,2,1'), False)
    same(semantics, a, b.replace('strNodes="7,8"', 'strNodes="7,9"'), False)


def test_v6_tree_url_maps_keep_header_membership_and_pair_identity(semantics):
    def url(value):
        return document('<Tree><Spec><URL>' + value + '</URL></Spec></Tree>')
    a = tree_url()
    b = tree_url(nodes=(65530, 200, 1), clusters=(10, 2), pairs=((9, 90), (7, 80)))
    same(semantics, url(a), url(b), True)
    for changed in [tree_url(header=b'\0\0\0\6\3\1'), tree_url(nodes=(1, 201, 65530)),
                    tree_url(pairs=((7, 90), (9, 80))), tree_url(suffix=b'\0'), a.replace('https:', 'http:')]:
        same(semantics, url(a), url(changed), False)
    # Unrecognized versions and truncated streams remain literal strings.
    old_a = tree_url(header=b'\0\0\0\5\2\1')
    old_b = tree_url(nodes=(65530, 200, 1), header=b'\0\0\0\5\2\1')
    same(semantics, url(old_a), url(old_b), False)
    same(semantics, url(a), url(a[:-5]), False)


def test_many_sets_match_reference_without_reordering_the_set_sequences(semantics):
    rng = random.Random(414)
    slots = [f'<Slot name="slot-{n}" itemId="{n}"/>' for n in range(30)]
    inputs = [f'<Input name="input-{n}" string="line {n}\n\tquest {n}"/>' for n in range(40)]
    def make(shuffle):
        items, configs = [], []
        for index in range(16):
            selected_slots, selected_inputs = slots[:], inputs[:]
            if shuffle:
                rng.shuffle(selected_slots); rng.shuffle(selected_inputs)
            items.append(f'<ItemSet id="{index}">' + ''.join(selected_slots) + '</ItemSet>')
            configs.append(f'<ConfigSet id="{index}">' + ''.join(selected_inputs) + '</ConfigSet>')
        roots = ['<Items activeItemSet="7">' + ''.join(items) + '</Items>', '<Config activeConfigSet="9">' + ''.join(configs) + '</Config>',
                 '<Skills><SkillSet id="1"><Skill><Gem nameSpec="Spark"/><Gem nameSpec="Rapid Casting II"/></Skill></SkillSet></Skills>']
        if shuffle:
            rng.shuffle(roots)
        return document(''.join(roots))
    original = make(False)
    for _ in range(8):
        equivalent = make(True)
        same(semantics, original, equivalent, True)
        same(semantics, original, equivalent.replace('activeItemSet="7"', 'activeItemSet="8"'), False)


@pytest.mark.parametrize('bad', ['', '<PathOfBuilding/>', '<PathOfBuilding2><Gem></PathOfBuilding2>', '<PathOfBuilding2/><PathOfBuilding2/>'])
def test_invalid_or_wrong_game_xml_cannot_match_itself(semantics, bad):
    result = semantics.equivalent(bad, bad)
    assert isinstance(result, tuple) and result[0] is False and result[1]
