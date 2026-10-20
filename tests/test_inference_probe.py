import json,sys
import pytest
from scripts import probe_inference as probe


def test_default_probe_is_zero_network_and_reports_disabled_gates(monkeypatch,capsys):
    monkeypatch.setattr(sys,'argv',['probe'])
    monkeypatch.setattr(probe,'inspect',lambda:{'configured_enabled':False})
    assert probe.main()==0
    result=json.loads(capsys.readouterr().out)
    assert result['provider_requests']==0 and result['live_verified'] is False


@pytest.mark.parametrize('server',['https://example.com','http://127.0.0.1:4000/?x=1','http://user:secret@localhost:4000'])
def test_probe_refuses_nonlocal_or_credential_bearing_origins(monkeypatch,server):
    monkeypatch.setattr(sys,'argv',['probe','--execute','--server',server])
    monkeypatch.setattr(probe,'inspect',lambda:{'configured_enabled':True})
    with pytest.raises(SystemExit):probe.main()


def test_execute_probe_cannot_pass_disabled_zero_cap_gate(monkeypatch):
    monkeypatch.setattr(sys,'argv',['probe','--execute'])
    monkeypatch.setattr(probe,'inspect',lambda:{'configured_enabled':False})
    with pytest.raises(SystemExit):probe.main()


def test_execute_probe_binds_one_request_expected_model_and_new_output(monkeypatch,tmp_path):
    import httpx
    from scripts import evaluate_live_agent
    class Fake:
        def __init__(self,**kwargs):assert kwargs['trust_env'] is False
        def __enter__(self):return self
        def __exit__(self,*args):pass
    def run(client,tasks,count,model,origin,controllers):
        assert len(tasks)==1 and count==1 and model=='fixture-model' and controllers==('direct',)
        return {'status':'mock fixture only','request_attempts':1}
    out=tmp_path/'probe.json'
    monkeypatch.setattr(probe,'inspect',lambda:{'configured_enabled':True})
    monkeypatch.setattr(httpx,'Client',Fake);monkeypatch.setattr(evaluate_live_agent,'run',run)
    monkeypatch.setattr(sys,'argv',['probe','--execute','--expected-model','fixture-model','--output',str(out)])
    assert probe.main()==0 and json.loads(out.read_text())['request_attempts']==1
    with pytest.raises(SystemExit):probe.main()
