# V-yovoice DSH 插件发布

插件与 VOS 包分别发布。使用已提交的插件源码和 `integrations/v-harness/tool-v-yovoice/harness-compatibility.json` 中锁定的干净宿主源码，按插件 README 执行 `build:release`，确认 `dist/dsh-plugin/compatibility.json` 中 `releaseEligible` 为 `true`。在目标宿主的隔离 profile 中安装最终归档验收，核对转写和播放的既有实机验证。

将生成的版本化 `.tgz`、`.sha256` 和 `compatibility.json` 上传到 `harness-plugin-vX.Y.Z` Release，保留用于版本锁定和回滚。不要将插件 Release 标记为仓库 Latest；VOS Release 使用该标记。

不再创建或更新 `harness-plugin-latest`、`v-yovoice.tgz` 等可变稳定包。用户必须使用
`harness-plugin-vX.Y.Z` Release 下的版本化归档，并在升级前核对 `compatibility.json`。
历史插件 Release 已移除；不要重建或复用旧标签。

## npm 包

GitHub Release 完成后，将同一个版本化归档发布到 npm。npm 发布在本机 Mac 终端执行；浏览器只用于登录和发布确认，归档由终端上传。

发布前核对 canonical registry。本机默认 registry 是 npmmirror，以下命令都必须显式指定 `--registry=https://registry.npmjs.org`：

```sh
npm whoami --registry=https://registry.npmjs.org
npm view @ictrek/dsh-tool-v-yovoice@X.Y.Z version --registry=https://registry.npmjs.org
```

`whoami` 返回 `401` 或 `ENEEDAUTH` 表示登录已失效，不是发布失败。重新登录时在 PTY 中读取 `Login at:` 后的 URL，交给用户自行打开；不要使用 `--auth-type=legacy`，也不要用 CUA 操作浏览器：

```sh
npm login --auth-type=web --browser=false \
  --registry=https://registry.npmjs.org --scope=@ictrek
```

`npm view` 返回 `E404` 表示该版本尚未发布，可以继续；返回版本号表示已存在，先核对已有 tarball 和 integrity，不要重复发布。

登录完成后发布最终归档。`--browser=false` 让 npm 只打印 auth URL，不自动打开浏览器，也不会绕过 2FA：

```sh
npm publish dist/dsh-plugin/ictrek-dsh-tool-v-yovoice-X.Y.Z.tgz \
  --registry=https://registry.npmjs.org --access public --tag latest --browser=false
```

如果输出 `Authenticate your account at:`，读取该 URL 交给用户完成确认；命令会继续等待，不要按 `Ctrl+C`。若 npm 改为要求终端 OTP，才输入一次性验证码，不要改用 legacy 登录。

发布成功只代表上传完成。npm 可能先更新 metadata，tarball 仍短暂返回 `404`；不要重复发布。重复执行下面的检查来轮询 canonical tarball，最多等待 15 分钟；`404` 时 `curl -f` 返回非零，继续等待：

```sh
curl -fsSI "https://registry.npmjs.org/@ictrek/dsh-tool-v-yovoice/-/dsh-tool-v-yovoice-X.Y.Z.tgz"
```

tarball 可下载后，从 registry 重新打包，核对名称、版本和 DSH 版本范围：

```sh
workdir="$(mktemp -d)"
npm pack @ictrek/dsh-tool-v-yovoice@X.Y.Z \
  --registry=https://registry.npmjs.org --pack-destination "$workdir"
tar -xOf "$workdir/ictrek-dsh-tool-v-yovoice-X.Y.Z.tgz" package/package.json
```

确认 `dist-tags.latest` 为目标版本，且 registry 的 `dist.integrity` 与本地归档的 sha512 一致：

```sh
npm view @ictrek/dsh-tool-v-yovoice dist-tags.latest version \
  --registry=https://registry.npmjs.org
npm view @ictrek/dsh-tool-v-yovoice@X.Y.Z dist.integrity \
  --registry=https://registry.npmjs.org
printf 'sha512-'
openssl dgst -sha512 -binary dist/dsh-plugin/ictrek-dsh-tool-v-yovoice-X.Y.Z.tgz \
  | openssl base64 -A
printf '\n'
```

第二条 `dist.integrity` 输出应与本地归档算出的 `sha512-...` 完全相同。npm 的 `latest` 指向新版本；GitHub 插件 Release 仍不设 Latest。
