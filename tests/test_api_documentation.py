"""核对文档路径、二进制媒体和原生响应字段，不启动推理。"""
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from vvoice.main import app

client=TestClient(app)

def response_schema(path,method='get',status='200'):
    spec=app.openapi()
    return spec, spec['paths'][path][method]['responses'][status]['content']['application/json']['schema']

def validate(spec,schema,value):
    Draft202012Validator({'$ref':'#/target','target':schema,'components':spec['components']}).validate(value)

def test_guide_and_proxy_relative_schema():
    assert client.get('/api-guide').status_code==200
    assert 'openapi.json' in client.get('/docs').text
    assert "url: '/openapi.json'" not in client.get('/docs').text
    spec=app.openapi()
    assert spec['servers']==[{'url':'.'}]
    body=spec['paths']['/v1/audio/streaming/transcriptions']['post']['requestBody']
    assert 'application/octet-stream' in body['content']
    assert 'audio/wav' in spec['paths']['/v1/audio/speech']['post']['responses']['200']['content']


def test_model_hotword_and_speaker_shapes(monkeypatch,tmp_path):
    from vvoice import main
    from vvoice.hotwords import HotwordStore
    from vvoice.speakers import SpeakerStore
    monkeypatch.setattr(main,'hotword_store',HotwordStore(tmp_path))
    monkeypatch.setattr(main,'speaker_store',SpeakerStore(tmp_path))
    created=client.post('/api/v1/hotwords',json={'name':'Docs test','phrases':['VOS']})
    spec,schema=response_schema('/api/v1/hotwords','post','201');validate(spec,schema,created.json())
    listed=client.get('/api/v1/hotwords');spec,schema=response_schema('/api/v1/hotwords');validate(spec,schema,listed.json())
    speakers=client.get('/api/v1/speakers');spec,schema=response_schema('/api/v1/speakers');validate(spec,schema,speakers.json())
    async def models():return [{'key':'docs','name':'Docs','kind':'asr','status':'not_installed','progress':None,'total_bytes':None,'downloaded_bytes':None}]
    monkeypatch.setattr(main,'list_models',models)
    reply=client.get('/api/v1/models');spec,schema=response_schema('/api/v1/models');validate(spec,schema,reply.json())
    deleted=client.delete('/api/v1/hotwords/'+created.json()['id'])
    spec,schema=response_schema('/api/v1/hotwords/{set_id}','delete');validate(spec,schema,deleted.json())
    assert deleted.status_code==200
