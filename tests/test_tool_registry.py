"""Host-only approval boundary and public tool dispatch."""
import json
from pathlib import Path
import pandas as pd
import pytest
from dataCleaningTools.tool_registry import AgentSessionState,ToolExecutor
from dataCleaningTools.versioning import DatasetVersionManager

def executor(tmp_path):
    source=tmp_path/'data.csv';pd.DataFrame({'name':[' Alice ','Bob'],'score':[1,2]}).to_csv(source,index=False)
    manager=DatasetVersionManager(tmp_path/'versions');original=manager.register_original(source,dataset_id='test')
    state=AgentSessionState(manager=manager,dataset_id='test',source_ref=original,current_ref=manager.create_working_copy(original))
    return state,ToolExecutor(state)

def test_model_cannot_select_an_approval_id_or_grant_permission(tmp_path):
    state,ex=executor(tmp_path)
    for name,args in [('request_approval',{'step_id':'chosen'}),('drop_column',{'columns':['score'],'step_id':'chosen'})]:
        assert not json.loads(ex.execute(name,args))['success']
    assert not state.approved_step_ids and state.current_ref.version=='V1'

def test_approval_is_a_stable_hash_of_exact_method(tmp_path):
    state,ex=executor(tmp_path)
    args={'columns':['score'],'step_id':'model-chosen'}
    rejected=json.loads(ex.execute_trusted('drop_column',args))
    assert rejected['approval_required'] and rejected['step_id']!='model-chosen'
    assert json.loads(ex.execute_trusted('drop_column',args))['step_id']==rejected['step_id']
    state.approved_step_ids.add(rejected['step_id']) # host action only
    changed=json.loads(ex.execute_trusted('drop_column',{'columns':['name'],'step_id':rejected['step_id']}))
    assert changed['approval_required'] and state.current_ref.version=='V1'
    accepted=json.loads(ex.execute_trusted('drop_column',args))
    assert accepted['success'] and 'score' not in state.manager.load(state.current_ref)
    assert len(state.pending_approvals)==1 # the different name-removal remains pending

def test_measurements_and_rejected_attempts_remain_in_trace(tmp_path):
    state,ex=executor(tmp_path)
    result=json.loads(ex.execute_trusted('trim_whitespace',{'columns':['name']}))
    assert result['accepted'] and result['evidence_ids']
    assert state.events[-1]['evidence']
    trace=json.loads((Path(state.current_ref.path).parent/'execution_trace.json').read_text())
    assert 'issues' not in trace and 'workflow_stage' not in trace
    assert 'flagged' in trace and 'failures' in trace


@pytest.mark.parametrize('failure',['type','missing','schema'])
def test_empty_finish_assessment_cannot_override_dataset_failures(tmp_path,failure):
    state,ex=executor(tmp_path)
    if failure=='type':
        state.required_targets={'name':'boolean'}
    elif failure=='missing':
        frame=state.manager.load(state.current_ref)
        frame.loc[0,'score']=None
        frame.to_csv(state.current_ref.path,index=False)
        state.required_missing=['score']
    else:
        state.expected_columns=['name','score','required_extra']
    state.model_unresolved=['Old model concern']
    result=json.loads(ex.execute('finish',{'summary':'No concerns claimed','unresolved':[]}))
    assert not result['success'] and not state.validation.all_passed
    assert state.validation.status.value=='failed'
    assert any(not rule.passed for rule in state.validation.rules)
    assert not state.model_unresolved


@pytest.mark.parametrize('protection',['human_review','approval','host_failure'])
def test_empty_finish_assessment_preserves_independent_exceptions(tmp_path,protection):
    state,ex=executor(tmp_path)
    if protection=='human_review':
        json.loads(ex.execute('flag_for_review',{'columns':['name'],'reason':'Business meaning unknown'}))
    elif protection=='approval':
        state.pending_approvals=['Approval required for structural change']
    else:
        state.unresolved=['Host execution failure']
    state.model_unresolved=['Old model concern']
    result=json.loads(ex.execute('finish',{'summary':'No concerns claimed','unresolved':[]}))
    assert result['validation']['status']=='partial' and not state.validation.all_passed
    assert state.validation.exceptions and 'Old model concern' not in state.validation.exceptions
    if protection=='human_review': assert state.flagged['name']=='Business meaning unknown'
    elif protection=='approval': assert state.pending_approvals
    else: assert state.unresolved==['Host execution failure']
