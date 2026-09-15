from pathlib import Path
import importlib.util


def canonical(xml):
    path=Path(__file__).resolve().parents[2]/'scripts/poe2_xml_semantics.py'
    spec=importlib.util.spec_from_file_location('poe2_xml_semantics',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module.canonical(xml)


def test_native_literal_attribute_whitespace_is_not_lost_by_the_verifier():
    native='<PathOfBuilding2><Config><Input name="quest" string="Charges\n\t+1 Charm Slot"/></Config></PathOfBuilding2>'
    flattened=native.replace('\n\t','  ')
    assert canonical(native)!=canonical(flattened)


def test_item_set_slot_maps_can_reorder_but_gem_sequences_cannot():
    a='<PathOfBuilding2><Items><ItemSet><Slot name="Belt" itemId="1"/><Slot name="Helmet" itemId="2"/></ItemSet></Items></PathOfBuilding2>'
    b='<PathOfBuilding2><Items><ItemSet><Slot itemId="2" name="Helmet"/><Slot itemId="1" name="Belt"/></ItemSet></Items></PathOfBuilding2>'
    assert canonical(a)==canonical(b)
    a='<PathOfBuilding2><Skills><Skill><Gem name="Spark"/><Gem name="Rapid Casting"/></Skill></Skills></PathOfBuilding2>'
    b='<PathOfBuilding2><Skills><Skill><Gem name="Rapid Casting"/><Gem name="Spark"/></Skill></Skills></PathOfBuilding2>'
    assert canonical(a)!=canonical(b)


def test_all_native_sections_are_checked_including_calc_selection():
    a='<PathOfBuilding2><Calcs><Input name="skill_number" number="1"/></Calcs></PathOfBuilding2>'
    assert canonical(a)!=canonical(a.replace('number="1"','number="2"'))


def test_calcs_input_map_reordering_preserves_ordered_sections_and_duplicate_keys():
    prefix='<PathOfBuilding2><Calcs>'
    suffix='</Calcs></PathOfBuilding2>'
    x='<Input name="skill_number" number="1"/>'
    y='<Input name="tab" number="2"/>'
    sections='<Section id="offence"/><Section id="defence"/>'
    assert canonical(prefix+x+y+sections+suffix)==canonical(prefix+y+x+sections+suffix)
    assert canonical(prefix+x+y+sections+suffix)!=canonical(prefix+x+y+sections.replace('offence','temp').replace('defence','offence').replace('temp','defence')+suffix)
    duplicate='<Input name="skill_number" number="2"/>'
    assert canonical(prefix+x+duplicate+suffix)!=canonical(prefix+duplicate+x+suffix)
    assert canonical(prefix+x+sections+y+suffix)!=canonical(prefix+y+sections+x+suffix)


def test_unique_root_sections_can_reorder_but_repeated_input_keys_cannot():
    a='<PathOfBuilding2><Build level="90"/><Calcs/></PathOfBuilding2>'
    b='<PathOfBuilding2><Calcs/><Build level="90"/></PathOfBuilding2>'
    assert canonical(a)==canonical(b)
    a='<PathOfBuilding2><Config><ConfigSet><Input name="x" number="1"/><Input name="x" number="2"/></ConfigSet></Config></PathOfBuilding2>'
    b=a.replace('number="1"','number="temporary"').replace('number="2"','number="1"').replace('number="temporary"','number="2"')
    assert canonical(a)!=canonical(b)
