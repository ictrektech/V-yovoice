"""应用只转交调度意图；预算及管理员身份由 V-Scheduler 核验。"""
from fastapi import HTTPException

HEADER_FIELDS = {'x-vscheduler-priority': 'priority', 'x-vscheduler-preemptible': 'preemptible', 'x-vscheduler-allow-preemption': 'allow_preemption', 'x-vscheduler-force-admission': 'force_admission'}

def options_from_headers(headers):
    options = {"priority": "interactive"}
    for header, field in HEADER_FIELDS.items():
        if header not in headers:
            continue
        value = headers[header]
        if field == 'priority':
            if value not in {'background', 'interactive', 'high'}:
                raise HTTPException(422, 'Invalid scheduling priority')
        else:
            if value not in {'true', 'false'}:
                raise HTTPException(422, 'Scheduling flags must be true or false')
            value = value == 'true'
        options[field] = value
    return options

def operator_headers(options, authorization):
    if not options.get('force_admission'):
        return {}
    if not authorization.startswith('Bearer '):
        raise HTTPException(403, 'Force admission requires administrator authorization')
    # 仅在当前请求转交身份，不写入任务、执行记录或日志。
    return {'X-VScheduler-Admin-Authorization': authorization}


def queue_wait_seconds(headers):
    value = headers.get('x-vscheduler-queue-wait-seconds', '30')
    if not isinstance(value, str) or not value.isascii() or not value.isdecimal() or int(value) > 300:
        raise HTTPException(422, 'Queue wait must be an integer from 0 to 300 seconds')
    return int(value)
