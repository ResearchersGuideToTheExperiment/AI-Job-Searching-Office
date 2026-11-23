import pytest
from office.db import Database
from office.config import Settings
from office.evaluation import CompactDecision,compare_batch,evaluate_job
from office.ollama import OllamaClient,OllamaError
from office.models import Requirement
from test_evaluation import prepared_job


def test_failed_evaluation_resumes_and_profile_change_invalidates(tmp_path,monkeypatch):
    db=Database(tmp_path/'office.db');job=prepared_job(db)
    fact=db.save_fact(None,'research','Tested participants.',True)
    calls=[];fail=[True]
    def answer(self,schema,prompt,data,**options):
        assert schema is CompactDecision and options['max_output_tokens']==512
        category=data['criterion']['category'];calls.append(category)
        if category=='desirable' and fail[0]:
            raise OllamaError('Connection interrupted')
        return CompactDecision(result='satisfied',explanation='Direct evidence.',fact_ids=[fact],eligibility_concern=None)
    monkeypatch.setattr(OllamaClient,'structured',answer)
    with pytest.raises(OllamaError):
        evaluate_job(db,job,Settings())
    assert db.evaluation(job) is None
    fail[0]=False
    result=evaluate_job(db,job,Settings())
    assert calls==['essential','desirable','desirable']
    assert result['criteria'][0]['evidence'][0]['quote']=='Tested participants.'
    db.save_fact(fact,'research','Tested 42 participants.',True)
    evaluate_job(db,job,Settings())
    assert calls[-2:]==['essential','desirable'] and len(calls)==5


def test_output_limit_splits_once_and_saves_results(tmp_path,monkeypatch):
    db=Database(tmp_path/'office.db');calls=[]
    criterion=Requirement(category='essential',importance='mandatory',text='Research required.',source_quote='Research required.')
    batch=[{'id':i,'category':'research','text':f'Research fact {i}.'} for i in range(4)]
    def answer(self,schema,prompt,data,**options):
        facts=data['confirmed_facts'];calls.append(len(facts))
        if len(facts)>2:
            error=OllamaError('Output limit');error.kind='output_limit';raise error
        return CompactDecision(result='partial',explanation='Related evidence.',fact_ids=[facts[0]['id']],eligibility_concern=None)
    monkeypatch.setattr(OllamaClient,'structured',answer)
    result=compare_batch(db,1,OllamaClient(Settings()),criterion,batch,'test-version')
    assert len(result)==2 and calls==[4,2,2]
    compare_batch(db,1,OllamaClient(Settings()),criterion,batch,'test-version')
    assert calls==[4,2,2]


@pytest.mark.parametrize('payload,kind',[
    ({'done_reason':'length','eval_count':512,'message':{'content':'{"result":'}},'output_limit'),
    ({'done_reason':'stop','message':{'content':'{}'}},'schema')])
def test_explicit_failure_reason(monkeypatch,payload,kind):
    client=OllamaClient(Settings())
    monkeypatch.setattr(client,'test_connection',lambda:'ok')
    monkeypatch.setattr(client,'request',lambda *args,**kwargs:payload)
    with pytest.raises(OllamaError) as error:
        client.structured(CompactDecision,'Compare.',{},max_output_tokens=512)
    assert error.value.kind==kind
    assert error.value.raw_response==payload['message']['content']
