"""Offline tests of the opt-in probe; these never connect to native PoB."""
import copy
import pytest
from probe_native_gem_evaluator import build_cases, assert_unchanged, weapon_set_two


def test_probe_targets_verified_roles_and_preserves_source_gem_references():
    def group(index,skill,level,source=None):
        return {'index':index,'enabled':True,'source':source,'gems':[{'index':1,'skillId':skill,'name':skill,'level':level,'enabled':True}]}
    bolt=group(3,'UniqueBreachLightningBoltPlayer',19)
    bolt['gems'].append({'index':2,'name':'Cooldown Recovery II','gemId':'fixture-support','is_support':True,'enabled':True})
    skills={'activeSkillSetId':1,'groups':[bolt,group(10,'SparkPlayer',20),group(11,'PoweredByVerisiumPlayer',18),group(16,'UniqueBreachLightningBoltPlayer',19,'Item:fixture')]}
    cases,indices=build_cases(skills)
    assert indices['item_bolt']==16 and indices['bolt']==3
    assert cases[0]['params']['groupIndex']==10
    assert cases[0]['params']['setups'][1]['gems'][0]=={'refIndex':1,'level':19}
    assert [(c['params']['groupIndex'],c['params']['evaluationGroupIndex']) for c in cases[1:3]]==[(11,3),(11,10)]
    assert cases[3]['params']['groupIndex']==16
    assert cases[3]['params']['setups'][1]['gems']==[{'refIndex':1},{'gemId':'fixture-support'}]
    assert cases[4]['invalid_first'] is True
    assert skills['groups'][1]['gems'][0]['level']==20


def test_probe_checks_selected_weapon_set_and_independent_config_rollback():
    xml='<PathOfBuilding2><Items activeItemSet="4"><ItemSet id="1" useSecondWeaponSet="false"/><ItemSet id="4" useSecondWeaponSet="true"/></Items></PathOfBuilding2>'
    assert weapon_set_two(xml)
    before={'xml':xml,'stats':{'CombinedDPS':100},'config':{'input':{'enemyLevel':83}},'skills':{'mainSocketGroup':3},'info':{'name':'Fixture'}}
    after=copy.deepcopy(before)
    assert_unchanged(before,after,'fixture')
    after['config']['input']['enemyLevel']=84
    with pytest.raises(RuntimeError,match='config'):
        assert_unchanged(before,after,'fixture')
