# 原生配乐的 V-Scheduler 接入交接

V-Voice 合入 V-Music 的 4 个原生权重模型，仍使用 `com.ictrek.v-voice`
服务身份。不要复制旧 V-Music 的凭据、执行器审批或预算。

## V-Voice 已提供

- `/api/v1/discovery` 的 `scheduler.sync_models` 声明
  `ace-step-1.5-turbo`、`stable-audio-3-small-music`、
  `stable-audio-3-medium`、`musicgen-small`，类型 `model.infer`。
- 就绪且硬件适配的模型才出现在公共模型发现目录，端点
  `audio/music/generations`；未下载或校验中的模型不能被误认为就绪。
- `scheduler.execution_settings.music` 声明实际固定运行方式：provider、
  Torch 线程/interop 线程、单并发、单模型、8 steps 和运行时标识
  `pytorch-music-v1`。模型每次使用独立子进程，退出后才确认停止、释放许可。
- 新 binding 只接受与上述参数匹配的音乐校准；其他语音模型的已有 binding
  保持兼容。直接调用和网关许可交接复用已有准入边界，不重复预约。
- 管理面仍调用 V-Scheduler 内置模型仓库，ModelScope 仓库 ID 和共享导出路径
  保持原样，没有独立 Model Hub 依赖。

## V-Scheduler 需要由其维护进程处理

当前 `backend/src/voice.rs` 的 V-Voice 自动绑定逻辑还需：

1. 对这 4 个模型支持输入度量 `duration_seconds`、`prompt_characters`、
   `negative_prompt_characters`，均为有限数值；排除词可为空（上限可为 0）。
   MusicGen 本身最长 30 秒，其他模型最多 300 秒；批准范围可以更小。
2. 审批时核对 `scheduler.execution_settings.music` 与当前节点上的实测配置，
   下发 binding 时保留同一 `execution_settings.music`。不能只匹配 ONNX
   的 `num_threads`、`cpu_models`；缺少实测记录的模型不要自动批准。
3. 为 V-Voice 的这些模型配置实际硬件、执行器、资源峰值和网关逐模型
   `permit` 策略。网关从 discovery 发现 `music` 类型和该端点，并把已核验
   permit 移交 V-Voice，继续验证许可和停止确认。
4. 验证模型已安装但尚未批准时返回不可推理；批准后，界面直调与网关调用各只
   占用一次许可；线程参数变化后应拒绝旧校准；失败/租约失效时子进程必须停止，
   不得提前释放资源预算。

本文是契约交接，不是校准数据。没有以上批准不能声称完整生产调度链路已验收。
