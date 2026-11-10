"""文档元数据与业务序列化分离，保留原生语音返回的扩展字段。"""
from copy import deepcopy
from fastapi.openapi.utils import get_openapi
from fastapi.routing import APIRoute

S={"type":"string"}; B={"type":"boolean"}; I={"type":"integer"}; N={"type":"number"}
def obj(fields, required=None):
    return {"type":"object","properties":deepcopy(fields),"required":list(fields) if required is None else required,"additionalProperties":True}
def arr(item):return {"type":"array","items":item}
def ref(name):return {"$ref":"#/components/schemas/"+name}
def null(schema):return {"anyOf":[schema,{"type":"null"}]}

def build_openapi(app):
    if app.openapi_schema:return app.openapi_schema
    spec=get_openapi(title=app.title,version=app.version,routes=app.routes,servers=[{"url":"."}],description="VOS speech, shared model management and private workbench. See api-guide#en or api-guide#zh for identity, scheduling, errors, WebSocket and full workflows. Desktop/CLI APIs have a separate contract.")
    schemas=spec.setdefault('components',{}).setdefault('schemas',{})
    model=obj({"key":S,"name":S,"kind":S,"status":S,"family":S,"backend":S,"modelscope_repo":S,"languages":arr(S),"description":S,"streaming":B,"translation":B,"loaded":B,"inference_ready":B,"inference_error":S,"error":S,"progress":null(N),"downloaded_bytes":null(I),"total_bytes":null(I),"import_required":B,"voices":{"type":"object","additionalProperties":obj({"sid":I,"language":S})},"hotwords":obj({"supported":B,"formats":arr(S),"score":B,"default_score":N},["supported"]),"timestamps":obj({"word":B,"segment":B,"source":S})},["key","name","kind","status"])
    public=obj({"id":S,"object":S,"owned_by":S,"kind":S,"capabilities":arr(S),"endpoints":arr(S),"languages":arr(S),"hotwords":model['properties']['hotwords'],"timestamps":model['properties']['timestamps'],"streaming":obj({"supported":B,"transports":arr(S),"hotwords":B}),"voices":obj({"endpoint":S,"default":S,"count":I})},["id","object","owned_by","kind","capabilities","endpoints","languages"])
    hotword=obj({"id":S,"name":S,"phrases":arr(S),"phrase_count":I,"created_at":S,"updated_at":S,"formats":arr(obj({"format":S,"file":S,"bytes":I}))})
    speaker=obj({"id":S,"name":S,"model":S,"created_at":S,"dimension":I})
    ranked=obj({"id":S,"name":S,"score":N})
    transcript=obj({"text":S,"language":S,"duration":N,"words":arr(obj({"word":S,"start":N,"end":N})),"segments":arr(obj({"id":I,"text":S,"start":N,"end":N},["text","start","end"])),"tokens":arr(S),"timestamps":arr(N),"emotion":S,"event":S,"streaming":B,"hotwords":obj({"requested":B,"supported":B,"applied":B,"sets":arr(obj({"id":S,"name":S})),"score_applied":null(N),"ignored":B}),"speaker":obj({"model":S,"threshold":N,"identified":B,"speaker":null(ranked),"score":N,"ranked":arr(ranked)},[])},["text"])
    scheduler=obj({"protocol_version":I,"input_limits_version":I,"mixed_input_limits_version":I,"app_id":S,"binding_endpoint":S,"lifecycle_protocol_version":I,"executor_base_url":S,"upstream_url":S,"sync_models":arr(obj({"id":S,"kind":S,"task_type":S})),"async_models":arr(obj({"id":S,"family":S,"task_type":S,"weight_bytes":I})),"num_threads":I,"max_concurrent_inference":I,"cpu_models":arr(S),"provider":S})
    schemas.update(VoiceManagedModel=model,VoicePublicModel=public,VoiceHotwordSet=hotword,VoiceSpeaker=speaker,VoiceTranscript=transcript,VoiceSchedulerContract=scheduler)
    discovery=obj({"service_id":S,"name":S,"protocol":S,"visibility":S,"multi_tenant":B,"authentication":S,"base_url":S,"health_path":S,"models":arr(ref('VoicePublicModel')),"scheduler":ref('VoiceSchedulerContract')})
    shapes={
      'health':obj({"status":S,"version":S,"provider":S}),
      'ready':obj({"ready":B,"model_hub_root":B,"scheduler":obj({"configured":B,"binding_revision":I,"protocol_version":I,"approved_model_count":I},["configured"])}),
      'about':obj({"app_id":S,"app_version":S,"profile":S,"provider":S,"port":I,"supported_asr_families":I,"supported_tts_families":I,"supported_speaker_families":I,"streaming_asr":B,"max_loaded_models":I,"max_concurrent_inference":I,"max_concurrent_per_model":I}),
      'discovery':discovery,'managed_models':arr(ref('VoiceManagedModel')),
      'creative_model_inventory':arr(ref('VoiceManagedModel')),
      'input_limits':obj({"limits":null(obj({"duration_seconds":N,"sample_rate":N,"hotwords_characters":N,"input_bytes":N})),"max_upload_bytes":I}),
      'scheduler_binding_status':obj({'protocol_version':I,'binding_revision':I,'configured':B,'approved_model_count':I}),'scheduler_binding_update':obj({'protocol_version':I,'binding_revision':I,'configured':B,'approved_model_count':I}),
      'stop':obj({"status":S,"tasks":arr(S)}),'unload':obj({"status":S,"model":S}),
      'list_hotword_sets':arr(ref('VoiceHotwordSet')),'create_hotword_set':ref('VoiceHotwordSet'),'import_hotword_set':ref('VoiceHotwordSet'),'get_hotword_set':ref('VoiceHotwordSet'),'update_hotword_set':ref('VoiceHotwordSet'),
      'delete_hotword_set':obj({"status":S,"id":S}),'openai_models':obj({"object":S,"data":arr(ref('VoicePublicModel'))}),
      'managed_speakers':arr(ref('VoiceSpeaker')),'enroll_speaker':ref('VoiceSpeaker'),'delete_speaker':obj({"status":S,"id":S}),
      'audio_speakers':obj({"object":S,"model":S,"default_threshold":N,"speakers":arr(ref('VoiceSpeaker')),"data":arr(ref('VoiceSpeaker'))}),
      'speakers_identify':obj({"object":S,"model":S,"threshold":N,"identified":B,"speaker":null(ranked),"score":N,"ranked":arr(ranked)}),
      'speakers_verify':obj({"object":S,"model":S,"speaker":ref('VoiceSpeaker'),"threshold":N,"score":N,"verified":B}),
      'voices':obj({"object":S,"model":S,"default_voice":S,"voices":arr(obj({"id":S,"name":S,"sid":I,"language":S},["id","name"])),"data":arr(obj({"id":S,"name":S,"sid":I,"language":S},["id","name"]))}),
    }
    for route in app.routes:
        if not isinstance(route,APIRoute) or not route.include_in_schema:continue
        for method in route.methods:
            op=spec['paths'][route.path][method.lower()];name=route.endpoint.__name__;code=str(route.status_code or 200)
            if name in shapes:
                op['responses'][code]={"description":"Native JSON response; extension catalog fields remain available.","content":{"application/json":{"schema":shapes[name]}}}
            elif name in {'transcriptions','translations','streaming_transcriptions','legacy_transcribe'}:
                op['responses'][code]={"description":"json returns text only; verbose_json keeps native model metadata, available word/segment timestamps and optional hotword/speaker blocks. Times are seconds. text/srt/vtt return text; supported formats depend on this operation. HTTP chunked upload returns one final response, not SSE.","content":{"application/json":{"schema":ref('VoiceTranscript')},"text/plain":{"schema":S}}}
            elif name=='speech':
                op['responses'][code]={"description":"Binary audio in response_format; raw pcm is not a WAV container.","content":{media:{"schema":{"type":"string","format":"binary"}} for media in ('audio/mpeg','audio/wav','audio/ogg','audio/aac','audio/flac','application/octet-stream')}}
            elif name=='export_hotword_set':
                op['responses'][code]={"description":"UTF-8 hotword file; Content-Disposition supplies its name.","content":{"text/plain":{"schema":S}}}
            elif name=='pull':
                op['responses'][code]={"description":"202 means download accepted, not installed. Existing task returns status=active/detail; otherwise the native V-Scheduler weight-service task response is forwarded. See its /openapi.json and poll /api/v1/models for ready/error.","content":{"application/json":{"schema":obj({"status":S,"detail":S,"task_id":S,"model_id":S,"phase":S},[])}}}
            elif name=='workbench_call':
                op['responses'][code]={"description":"Check error even on HTTP200. result is method-specific: state.get returns state/catalog metadata, generation returns job ID; poll until confirmed success before reading media. See the complete workbench workflow and native schema in the guide.","content":{"application/json":{"schema":{"oneOf":[obj({"result":{"description":"Native method result; data contract is linked from the guide."}}),obj({"error":{"description":"Native localized msg.Encode error."}})]}}}}
            if name=='streaming_transcriptions':op['requestBody']={"required":True,"content":{"application/octet-stream":{"schema":{"type":"string","format":"binary"}}}}
            op['responses'].setdefault('default',{"description":"Check status and Content-Type: public speech uses FastAPI detail, user workbench/automatic binding can return plain text. 400 malformed request, 401 identity, 403 permission, 404 missing, 409 not ready/conflict, 413 input limit, 422 unsupported/calibration, 429 capacity and 503 binding/service unavailable. Do not bypass scheduling to hide the failure.","content":{"application/json":{"schema":obj({"detail":{},"error":{}},[])},"text/plain":{"schema":S}}})
    app.openapi_schema=spec
    return spec
