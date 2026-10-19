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

## 229 隔离联调入口

- 隔离容器：`v-voice-music-handoff-qa`，VOS 网络地址
  `http://v-voice-music-handoff-qa:7070`；主机仅绑定 `127.0.0.1:22709`。
- 独立数据与 binding：`/home/jhu/dev/build/v-yovoice/music-merge/handoff-data`；
  共享权重和生产卷只读挂载，并以独立目录覆盖 `/data`，不复制原应用凭据。
- `VVOICE_SCHEDULER_UPSTREAM_URL` 固定为隔离地址的 `/v1`。
  discovery 的生产兼容地址仍为 `v-voice-backend`；联调必须显式指定上述隔离地址，
  不得由此覆盖生产服务注册或 binding。
- 使用新 Go 二进制，binding 更新仍验证真实 Scheduler 的 VOS 应用身份。
  不伪造校准记录，不关闭 Scheduler 准入。
- 当前隔离资源上限 CPU 4 核、内存 12 GiB；这不是批准预算或模型峰值结论。
  真实校准前应按节点余量协调隔离资源上限，避免把容器内存限制当成硬件不支持。

源码同步后，在 229 执行以下只读探针（不执行推理）：

```bash
python3 /home/jhu/dev/repos/V-yovoice/scripts/check-native-music-handoff.py
```

探针的 `READ_ONLY_PASS` 仅表示接口及四模型声明完整，文件仍可能在后台校验。
批准后可显式执行真实十秒生成，输出路径必须不存在：

```bash
python3 /home/jhu/dev/repos/V-yovoice/scripts/check-native-music-handoff.py \
  --generate musicgen-small \
  --output /home/jhu/dev/build/v-yovoice/music-merge/musicgen-approved.wav
```

输出 WAV 格式检查不代替听音、时长、资源峰值、单次许可及停止确认验收。
重建隔离容器前必须先检查现有测试是否活跃；启动脚本遇到同名容器会拒绝覆盖：
`bash scripts/start-native-music-handoff.sh <已核对的生产V-Voice容器名>`。
该测试镜像不属于正式发布镜像，不能据此声称六平台构建或版本发布完成。

### 受控校准 worker

`scripts/calibrate-native-music-worker.py` 只用于 Scheduler 的外层校准编排。
外层先申请并续租真实许可、限制容器 CPU/RAM，再设置
`VVOICE_EXTERNAL_CALIBRATION_PERMIT=active` 启动此脚本；这个环境标识只是误用防护，
不是授权凭据。不要把它放入生产 Compose，也不要关闭生产 API 准入。
使用镜像内主 Python 启动包装器，原生子进程自动使用 `VVOICE_MUSIC_PYTHON`。
必须传递真实 `VVOICE_PROVIDER`、音乐 Torch 线程参数和只读共享模型目录。

脚本先校验固定文件，生成十秒 WAV 并记录输入实值、execution_settings、文件清单、
输出时长/哈希以及子进程 PID、Linux starttime 和 boot ID。`native-started` 标记只表示
子进程已创建，**不表示模型导入/加载结束**，不能用于推理阶段 CPU 峰值归因。
SIGTERM/SIGINT 或独立输出目录中的 `cancel` 文件触发杀进程组并 wait；
停止证据写入 `calibration-stop.json`，成功证据写入 `calibration-result.json`。
外层仍必须确认容器及其后代全部退出后才能释放许可；worker 不申请第二份许可。
每次运行使用新的输出目录，不复用旧证据。
