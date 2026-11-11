# v-harness 音频转写插件发布

插件与 VOS 包分别发布。使用已提交的插件源码和 `integrations/v-harness/tool-audio-transcription/harness-compatibility.json` 中锁定的干净宿主源码，按插件 README 执行 `build:release`，确认 `dist/dsh-plugin/compatibility.json` 中 `releaseEligible` 为 `true`。在目标宿主的隔离 profile 中安装最终归档验收，核对转写和播放的既有实机验证。

将生成的版本化 `.tgz`、`.sha256` 和 `compatibility.json` 上传到 `harness-plugin-vX.Y.Z` Release，保留用于版本锁定和回滚。不要将插件 Release 标记为仓库 Latest；VOS Release 使用该标记。

验证版本化 Release 后，将相同归档以 `audio-transcription.tgz` 上传到固定的 `harness-plugin-latest` Release，同时上传以该文件名生成的 `audio-transcription.tgz.sha256` 和对应的 `compatibility.json`。更新已有附件前先下载备份；GitHub 的覆盖上传可能先删除旧附件，失败时应从备份恢复。不要改动版本化 Release 的历史包。

固定安装地址：`https://github.com/ictrektech/V-yovoice/releases/download/harness-plugin-latest/audio-transcription.tgz`。发布后从该地址重新下载并核对 SHA-256 与版本化归档一致，确认兼容性元数据对应实际源码和宿主版本，再检查 VOS 的仓库 Latest 未被改变。插件固定地址不保证与未来的所有宿主版本兼容，升级前须检查元数据。
