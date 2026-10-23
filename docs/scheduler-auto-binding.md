# V-Voice 自动调度接入：V-Scheduler 侧协作清单

状态：交接契约 v1 已在 229 完成双方真实联调，包括自动绑定、界面与网关单次许可、
异步生成、运行中取消、凭据轮换，以及断线、忙碌和遥测过期的拒绝边界。
V-Scheduler 侧由另一个进程独立实现和发布；仅支持本契约的正式版本才能自动接入，
不能将旧版本的模型发现能力当成已具备自动授权。未实测校准的模型继续拒绝准入。

新增 `scheduler.input_limits_version=1` 发现声明。新节点批准必须匹配该能力，绑定同时下发
`input_limits_version: 1` 和逐模型 `model_limits`：Kokoro 使用 `text_characters`、
`speed_min`、`speed_max`；SenseVoice 使用 `duration_seconds`、`sample_rate`、
`hotwords_characters`、`input_bytes`。直连及网关请求在取模型计算许可前校验，
音频先限制编码字节和源采样率，再有界解码并检查时长；超限不加载模型。
当前新增节点实测范围为 Kokoro 512 字符/语速 1，以及 SenseVoice 20 秒/24kHz/
1MiB/无热词，不包括联合声纹或翻译。旧 Thor 未带此字段的既有绑定保持兼容。

识别页面通过 `GET /api/v1/models/{key}/input-limits` 读取已验证的逐模型限制与
`max_upload_bytes`，该响应不包含调度凭据。对于有界模型，浏览器使用上游音频工具
转换为 16 kHz 单声道 PCM WAV，按 `duration_seconds` 与 `input_bytes`（含 WAV 头）
取较小分段长度，逐段调用原转写接口并独立获取许可；失败或取消后不再提交后续段。
原文件仍受全局上传大小限制；无有界限制的旧审批沿用原上传流程。公共 API 保留
源采样率、文件大小及总时长校验，不自动扩大校准范围。上传中间件按已批准模型的
最大编码大小加 64 KiB 表单开销限制请求体，并由处理函数检查所选模型自己的上限。

## 混合输入校准 v1

发现声明增加 `mixed_input_limits_version: 1`。同一绑定同时包含旧审批和新有界审批时，
必须下发同版本及 `legacy_unbounded_models`；该列表只允许既有实测审批，必须与
`model_limits` 不重叠，二者的键必须恰好覆盖 `models`，重复、未知或缺失条目均拒绝。
ACE-Step、Stable Audio 两款及 MusicGen 始终要求逐模型有界审批，不能放入旧名单。
纯旧绑定不要求此扩展；没有能力声明的旧应用不能接收混合快照。

旧名单沿用原上传配置，新有界模型仍在许可前检查自己的字节、时长及文字限制；
配乐请求体始终限制为 64 KiB。校验时固定绑定快照，许可前发现快照变化则拒绝并要求重试。
已知创作目录的 `audiocpp-` 别名仅能归一输入校验，不能新增同步执行授权；
旧 Thor 的裸 ID 创作审批仍使用 `voice.generate`，未批准的同步调用仍拒绝。

## 联调前确认的 229 故障（历史原因）

- 网关 `/v1/models` 已自动列出 `v-voice/` 模型，发现功能正常。
- 网关真实 ASR 请求返回 503 `local model resource policy not approved`。
- V-Voice 界面真实 ASR 请求返回 503 `V-Scheduler configuration required`。
- 所以不能用“已发现”作为“已经可以调度”的验收证明，也不能要求用户手工分发凭据。

## V-Scheduler 侧职责（既定交接范围）

1. 复用现有 V-Voice 主动发现器。读取 `/api/v1/discovery` 的新增 `scheduler`
   接入声明；只对可信的同 VOS 已安装应用建立绑定，不能向任意注册 URL 发送凭据。
2. 按真实执行节点、现有资源准入规则和校准后的固定预算，建立 V-Voice 自己的
   submitter、同步 `model.infer` 执行器及异步 `voice.generate` 执行器。
   应用身份为 `com.ictrek.v-voice`，不要借用网关或其他应用的服务令牌。
3. 在网关私有 `models[app-v-voice/<原生模型ID>]` 中生成对应的输入限制和
   同步 permit 策略；`upstream_url` 固定为发现声明中的实际推理地址。
   V-Voice submitter 的 `permit_executors` 显式允许核验相应网关执行器。
4. Agent 为 `voice.generate` 配置 V-Voice 基址和独立 executor credential；
   原有 `/scheduler/executions/{attempt}/{start|inspect|cancel}` 协议不变。
5. 用 VOS 签发给 `com.ictrek.v-scheduler` 的应用 context access token，向
   V-Voice 下述端点推送它自己的受限授权；安装、重启、模型变化、凭据轮换后重试。
   只传服务端，不传浏览器，不写日志，不把凭据放入包或 discovery。
6. 资源不足、未校准模型、节点遥测失效或执行器不可用时仍须拒绝/排队；不能因为
   自动发现而自动信任任意模型自报预算，不能关闭资源准入。

## V-Voice 提供的交接接口

`/api/v1/discovery.scheduler` 包含 `protocol_version`、`app_id`、`binding_endpoint`、
`executor_base_url`、`upstream_url`、`sync_models[]`、`async_models[]`。
各模型声明 `id` 与 `task_type`；同步目录还含 `kind`，异步目录含 `family` 与
仅供参考的 `weight_bytes`。`provider`、`cpu_models`、`num_threads` 和并发上限
说明本应用运行配置，不是已批准资源预算。顶层 `models[]` 仍只公开实际就绪模型。

`GET /api/v1/scheduler/binding`：公开的脱敏状态，不返回凭据。

`POST /api/v1/scheduler/binding`：最大 256 KiB，JSON；Authorization 是上面的
VOS 应用令牌。V-Voice 通过本 VOS 的 userinfo 验证 `sub` 必须恰为
`com.ictrek.v-scheduler` 且 `enable=1`；普通管理员用户、匿名请求和其他应用均拒绝。
这不是通用浏览器配置接口。

请求字段如下；尖括号为说明，绝不可作为生产值：

```json
{
  "protocol_version": 1,
  "binding_revision": 1,
  "app_id": "com.ictrek.v-voice",
  "url": "http://v-router:8080/scheduler/api/v1",
  "token": "<V-Voice scoped submitter token, 32+ chars>",
  "executor_token": "<V-Voice async executor credential, 32+ chars>",
  "upstream_url": "http://v-voice-backend:7070/v1",
  "models": {
    "sensevoice-int8": "<V-Voice owned model.infer executor>",
    "speaker-campplus-zh-en": "<V-Voice owned model.infer executor>",
    "audiocpp-kokoro-82m-q8": "<V-Voice owned model.infer executor>",
    "kokoro-82m-q8": "<V-Voice owned voice.generate executor>"
  },
  "gateway_executors": {
    "sensevoice-int8": "<gateway owned model.infer executor>"
  },
  "secondary_models": {
    "sensevoice-int8": ["speaker-campplus-zh-en"]
  }
}
```

- `models` 的 ID：兼容 API 使用原生 ID（创作 TTS 的兼容 ID 带 `audiocpp-`）；
  工作台异步任务使用创作目录中的裸 ID。发现声明分别给出同步/异步 ID，不能混用。
- 多模型作品现有实现要求所有参与模型映射到同一个已覆盖联合峰值的生成执行器；
  不满足时拒绝，不擅自拆成多次独立预约。
- V-Voice 会先用新 submitter 调用现有 `GET /executors` 核验应用归属、类型、
  contract version、同步 upstream 绑定；失败不替换现有可用配置。
- URL 只接受容器环境固定的调度地址（默认上述统一网关地址），不允许请求体改成任意
  外网地址来发送凭据。上游地址必须与 V-Voice 自己的标准发现地址一致。
- revision 由 Scheduler 持久维护，每次配置变化递增；同 revision 相同内容幂等成功，
  同 revision 不同内容或倒退返回 409。服务重启不能把 revision 重置。
- V-Voice 原子写本应用 `/data/scheduler.local.json`，权限 0600，保留上一个版本以便
  回退；Python 和 Go 读取同一份配置，新任务无需重启。现有静态配置仍兼容。
- 成功返回 200：`{"protocol_version":1,"binding_revision":1,"configured":true}`。
  失败：401/403 身份不符，409 revision 冲突，422 字段不合法，503 调度预检失败。
- 轮换时保留旧凭据和已批准执行器到其活动任务/permit 确认停止，不能让轮换释放未知
  计算的预算。撤销服务身份仍由 Scheduler 负责，不能把旧配置视为离线执行许可。

## 229 双方验收（发布门槛）

- 新安装/重启无需手工编辑 JSON；binding 自动建立，状态无凭据泄露。
- 界面上传音频 → 原生 ASR 成功 → Scheduler 有恰好一笔许可及确认释放。
- 网关同一 ASR → V-Voice 验票成功，仅一笔预约，无重复扣费。
- 界面原有 TTS、声纹注册/识别/验证均进入统一资源准入；组合 ASR/声纹有联合预算。
- 创作界面 TTS/声音克隆 → 持久任务 → Agent start/inspect/cancel → 用户私有结果。
- 忙碌、无资源策略、过期遥测、伪造交接、断线和停止未知都不能绕过；取消后确认进程
  停止再释放。重启和同 revision 重试不重复注册、不重复执行。
- 新版 V-Voice 必须等以上真实节点链路通过后再发布；界面或模拟测试成功不代替它。
