"""Flat inspect/test/apply workflow regressions (replaces stage-machine tests)."""
import json
from pathlib import Path
import pandas as pd
import pytest
from dataCleaningTools import workflow, experiments
from dataCleaningTools.models import ValidationStatus
from dataCleaningTools.tool_registry import AgentSessionState, ToolExecutor
from dataCleaningTools.versioning import DatasetVersionManager

@pytest.fixture
def flat(tmp_path):
    source=tmp_path/'input.csv'
    pd.DataFrame({'amount':['$10','$20','$30','$40'],'flag':['Yes','No','Yes','No']}).to_csv(source,index=False)
    manager=DatasetVersionManager(tmp_path/'versions')
    original=manager.register_original(source,dataset_id='sales')
    state=AgentSessionState(manager=manager,dataset_id='sales',source_ref=original,
        current_ref=manager.create_working_copy(original),required_targets={'amount':'float','flag':'boolean'},expected_columns=['amount','flag'])
    return state,ToolExecutor(state)

def call(ex,name,**args): return json.loads(ex.execute(name,args))
def trial(ex,**changes):
    return call(ex,'test_method',**{'hypothesis':'Parse currency strings','columns':['amount'],
        'operation':'clean_numeric_string','parameters':{},**changes})
def apply(ex,candidate): return call(ex,'apply_candidate',candidate_id=candidate['candidate_id'],assessment='Trial preserved values and passed the declared checks')

def test_only_five_tools_are_public(flat):
    state,ex=flat
    assert {t['function']['name'] for t in workflow.SCHEMAS_LIST}=={'inspect_data','test_method','apply_candidate','flag_for_review','finish'}
    for name in ['review_candidate','request_approval','convert_data_types','run_custom_check']:
        assert not call(ex,name)['success']
    assert not hasattr(state,'workflow_stage') and not hasattr(state,'issues')

def test_builtin_full_copy_then_apply(flat):
    state,ex=flat
    original=Path(state.source_ref.path).read_bytes()
    candidate=trial(ex)
    assert candidate['tested'] and state.current_ref.version=='V1'
    assert 'trials' not in candidate and candidate['effect']['after']['rows']==4
    assert apply(ex,candidate)['success'] and state.current_ref.version=='V2'
    assert Path(state.source_ref.path).read_bytes()==original
    assert not call(ex,'finish',summary='Still need flag')['success'] and not state.finished
    flags=trial(ex,hypothesis='Yes/No flags',columns=['flag'],operation='convert_data_types',parameters={'target_type':'boolean'})
    assert apply(ex,flags)['success']
    assert call(ex,'finish',summary='Both columns prepared')['success'] and state.validation.all_passed

def test_apply_requires_an_assessment_and_passing_trial(flat):
    state,ex=flat
    candidate=trial(ex)
    assert not call(ex,'apply_candidate',candidate_id=candidate['candidate_id'])['success']
    failed=trial(ex,operation='convert_data_types',parameters={'target_type':'float','errors':'coerce'})
    assert not failed['tested'] and not apply(ex,failed)['success']
    assert state.current_ref.version=='V1'

def test_builtin_declared_checks_cannot_be_skipped(flat):
    state,ex=flat
    candidate=trial(ex,checks=[{'column':'amount','kind':'unique'}])
    # Trial passes, then the trusted implementation deliberately changes for full execution.
    assert candidate['tested']
    original=workflow.run_builtin
    def changed(frame,operation,parameters):
        out=original(frame,operation,parameters)
        out.df['amount']=10
        return out
    from unittest.mock import patch
    with patch.object(workflow,'run_builtin',changed): result=apply(ex,candidate)
    assert not result['success'] and state.current_ref.version=='V1'

def test_flagged_columns_are_exceptions_not_clean(flat):
    state,ex=flat
    assert call(ex,'flag_for_review',columns=['amount','flag'],reason='Business meaning undocumented')['success']
    assert not trial(ex)['success']
    done=call(ex,'finish',summary='Requires human decisions')
    assert done['success'] and len(done['exceptions'])==2 and state.finished
    assert state.validation.status==ValidationStatus.PARTIAL and not state.validation.all_passed
    assert not call(ex,'flag_for_review',columns=['unknown'],reason='Missing')['success']

def test_flag_after_trial_blocks_application(flat):
    state,ex=flat
    candidate=trial(ex)
    call(ex,'flag_for_review',columns=['amount'],reason='Currency unit ambiguous')
    assert not apply(ex,candidate)['success'] and state.current_ref.version=='V1'

def test_findings_are_advisory_and_finish_is_bounded(flat):
    state,ex=flat
    state.profiling_summary='Suspected outliers require investigation'
    assert not call(ex,'finish',summary='Not cleaned')['success'] and not state.finished
    assert not call(ex,'finish',summary='Blocked')['success'] and state.finished
    assert state.finish_attempts==2

def test_versions_and_methods_cannot_change_after_trial(flat):
    state,ex=flat
    candidate=trial(ex)
    state.method_candidates[candidate['candidate_id']]['parameters']['errors']='ignore'
    assert not apply(ex,candidate)['success']
    state.method_candidates.clear()
    candidate=trial(ex)
    Path(state.current_ref.path).write_text('amount,flag\n$9,Yes\n',encoding='utf-8')
    assert not apply(ex,candidate)['success']

def test_duplicate_and_failure_budget(flat):
    state,ex=flat
    candidate=trial(ex)
    assert not trial(ex)['success']
    state.failures[state.method_candidates[candidate['candidate_id']]['key']]=3
    state.method_candidates.clear()
    assert 'three times' in trial(ex)['error']

def test_noop_never_creates_a_new_version(flat):
    state,ex=flat
    candidate=trial(ex,operation='trim_whitespace',parameters={})
    assert candidate['tested']
    result=apply(ex,candidate)
    assert result['no_op'] and state.current_ref.version=='V1'

def test_generated_candidate_uses_internal_experiment_id_and_mandatory_checks(flat,monkeypatch):
    state,ex=flat
    calls=[]
    def runner(frame,code,**kwargs):
        calls.append((len(frame),code))
        after=frame.copy();after['amount']=pd.to_numeric(after.amount.str.replace('$','',regex=False))
        return {'success':True,'df':after,'image_id':'sha256:test','repeatable':True}
    monkeypatch.setattr(experiments,'run_isolated_transform',runner)
    code="def transform(df):\n    df['amount']=pd.to_numeric(df.amount.str.replace('$','',regex=False))\n    return df\n"
    candidate=call(ex,'test_method',hypothesis='Currency parser',columns=['amount'],code=code,checks=[{'column':'amount','kind':'no_missing'}])
    assert candidate['tested'] and candidate['candidate_id']=='c1'
    stored=state.method_candidates['c1']
    assert stored['experiment_id'] in state.experiments and stored['experiment_id']!='c1'
    assert {'column':'amount','kind':'numeric'} in stored['checks']
    assert apply(ex,candidate)['success'] and len(calls)==3

def test_generated_missing_obligation_cannot_be_omitted(flat,monkeypatch):
    state,ex=flat
    frame=state.manager.load(state.current_ref);frame.loc[0,'amount']=None;frame.to_csv(state.current_ref.path,index=False)
    state.required_missing=['amount']
    def runner(frame,code,**kwargs):
        after=frame.copy();after['amount']=pd.to_numeric(after.amount.str.replace('$','',regex=False))
        return {'success':True,'df':after,'image_id':'sha256:test','repeatable':True}
    monkeypatch.setattr(experiments,'run_isolated_transform',runner)
    candidate=call(ex,'test_method',hypothesis='Only parse',columns=['amount'],code='def transform(df):\n    return df\n',checks=[{'column':'amount','kind':'numeric'}])
    assert not candidate['tested'] and state.current_ref.version=='V1'

def test_unknown_arguments_do_not_reach_execution(flat):
    state,ex=flat
    assert not call(ex,'inspect_data',view='column')['success']
    assert not call(ex,'test_method',hypothesis='missing method',columns=['amount'])['success']
    assert not call(ex,'test_method',hypothesis='invalid',columns=['amount'],code='def transform(df):\n    return df')['success']
