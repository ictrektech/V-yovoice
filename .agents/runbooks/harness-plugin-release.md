# V-yovoice DSH 插件发布

插件与 VOS 包分别发布。使用已提交的插件源码和 `integrations/v-harness/tool-v-yovoice/harness-compatibility.json` 中锁定的干净宿主源码，按插件 README 执行 `build:release`，确认 `dist/dsh-plugin/compatibility.json` 中 `releaseEligible` 为 `true`。在目标宿主的隔离 profile 中安装最终归档验收，核对转写和播放的既有实机验证。

将生成的版本化 `.tgz`、`.sha256` 和 `compatibility.json` 上传到 `harness-plugin-vX.Y.Z` Release，保留用于版本锁定和回滚。不要将插件 Release 标记为仓库 Latest；VOS Release 使用该标记。

不再创建或更新 `harness-plugin-latest`、`v-yovoice.tgz` 等可变稳定包。用户必须使用
`harness-plugin-vX.Y.Z` Release 下的版本化归档，并在升级前核对 `compatibility.json`。
历史插件 Release 已移除；不要重建或复用旧标签。
