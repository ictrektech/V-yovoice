# VOS V-Voice 打包与发布

```text
检查并提交代码 -> 确定候选版本 -> 构建推送镜像、更新飞书 -> 打包预检与测试
  -> 决定正式发版 -> 整理 CHANGELOG -> update_version.sh
  -> GitHub Actions 检查并打包 -> GitHub Release -> VOS App Store
```

使用现有构建机和凭据。先完成镜像与 VOS 安装包的构建和测试，测试正常后再决定是否正式发版。

## 0. 前置条件

各构建机使用同一份已提交源码，镜像仓库已登录，飞书写表凭据可用（默认 `~/.feishu.json`，可用 `FEISHU_CONFIG_FILE` 指定）。

## 1. 检查代码并提交

从仓库根目录操作：

```bash
cd /home/czy/p/vai/apps/V-yovoice
git status --short --branch
git diff --check
```

确认本次改动及已有测试结果，提交待构建的应用代码，各构建机同步到该提交。正式 CI 会再次执行项目检查。

## 2. 确定候选版本

以下默认递增 `patch`，需要时改为 `minor` 或 `major`。本节只计算包版本，保持 CHANGELOG 的 `Unreleased` 和现有 VERSION，不检查发布说明：

```bash
RELEASE_PART=patch
CURRENT_VOS_VERSION="$(tr -d '[:space:]' < ictrek.app/VERSION)"
IFS=. read -r VOS_MAJOR VOS_MINOR VOS_PATCH <<< "$CURRENT_VOS_VERSION"
case "$RELEASE_PART" in
  patch) VOS_PATCH=$((VOS_PATCH + 1)) ;;
  minor) VOS_MINOR=$((VOS_MINOR + 1)); VOS_PATCH=0 ;;
  major) VOS_MAJOR=$((VOS_MAJOR + 1)); VOS_MINOR=0; VOS_PATCH=0 ;;
  *) echo 'invalid RELEASE_PART' >&2; exit 1 ;;
esac
RELEASE_VERSION="${VOS_MAJOR}.${VOS_MINOR}.${VOS_PATCH}"
printf '%s\n' "$RELEASE_VERSION"
```

后续在同一 shell 使用这些变量；换终端时按当前 VERSION 重新计算。

## 3. 构建并推送镜像

可先预览计划，例如本机 L4T：

```bash
bash docker/build_image.sh --sheet l4t --dry-run
```

预览显示镜像、构建步骤和飞书登记目标，不下载、不编译、不推送、不写飞书，也不检查本地 wheel 和构建产物。可与 `--build-only`、`--publish-only` 等模式组合。

在对应构建机执行，按表选择 `--sheet`：

| Profile | `--sheet` | 镜像标签 | 构建机 |
| --- | --- | --- | --- |
| `amd` | `AMD_with_mxn100` | `amd_YYYYMMDD` | x86_64 |
| `amd-cuda` | `AMD_with_cuda` | `amd_cu128_YYYYMMDD` | x86_64 CUDA |
| `arm` | `ARM_without_cuda` | `arm_YYYYMMDD` | ARM64 |
| `arm-cuda` | `ARM_with_cuda` | `arm_cu130_YYYYMMDD` | ARM64 CUDA |
| `l4t` | `l4t` | `l4t_YYYYMMDD` | Jetson L4T |
| `thor` | `thor_spark` | `thor_YYYYMMDD` | Thor / Spark |

例如 AMD CUDA：

```bash
bash docker/build_image.sh --sheet AMD_with_cuda
```

默认命令会完成构建、推送到 `swr.cn-southwest-2.myhuaweicloud.com/ictrek/v-voice`，并更新飞书对应 sheet 的 `v-voice` 列。`ARM_without_cuda` 会同时更新 `SOPHON_bm1688`。

如需分开构建和推送，改用以下两步，并在同一天执行：

```bash
bash docker/build_image.sh --sheet AMD_with_cuda --build-only
bash docker/build_image.sh --sheet AMD_with_cuda --publish-only
```

本次上游合并包含 Go 和前端改动，使用完整构建。一个 VOS 包包含六个平台，先完成所有受影响平台的镜像和飞书记录，再生成测试包；打包器从飞书读取镜像引用，CI 不会代为构建镜像。

推送镜像并更新飞书是为了让 pull 测试包能够引用和拉取镜像，此时尚未创建 GitHub Release 或发布应用商店版本。

## 4. 本地打包预检与测试

在仓库根目录执行，使用第 2 节计算的候选版本。`--version` 只设置包内版本，不修改 VERSION、不读取 CHANGELOG，也不创建标签或发布 Release：

```bash
(
  set -eo pipefail
  : "${RELEASE_VERSION:?请先执行第 2 节计算候选版本}"
  bash ictrek.app/scripts/package.sh --version "$RELEASE_VERSION"
  test -f "ictrek.app/dist/v_voice_${RELEASE_VERSION}_pull.tar"
  tar tf "ictrek.app/dist/v_voice_${RELEASE_VERSION}_pull.tar"
  tar xOf "ictrek.app/dist/v_voice_${RELEASE_VERSION}_pull.tar" app.tar.gz | tar tzf -
)
```

打包使用现有飞书读凭据（优先 `~/.feishu.components.json`，其次 `~/.feishu.json`，或由 `FEISHU_CONFIG_FILE` 指定）。V-Scheduler 依赖从已发布的 GitHub 包查询，依次使用 `GH_TOKEN`、`GITHUB_TOKEN` 或本机 `gh auth login` 已保存的登录，避免匿名 API 限流；无需手动导出 CLI 令牌。私有仓库无法读取时，可通过已授权的本机隧道设置 `VVOICE_APPSTORE_API_URL` 查询商店记录。依赖查询失败时先解决凭据或通道问题，不提前触发正式发布。

外层包应只有 `app.tar.gz`。核对 `ictrek.app/dist/staging/` 中的版本、六个平台镜像引用和依赖，产物为 `ictrek.app/dist/v_voice_X.Y.Z_pull.tar`。

将测试包用于现有 VOS 测试流程，测试发现问题则修复代码、重建受影响镜像并重新打包。这里先停下，由测试结果决定是否进入第 5 节；本手册不自动执行应用安装或升级。

## 5. 整理 CHANGELOG 并触发正式发布

仅在测试正常且已决定正式发版后执行本节。将根目录 CHANGELOG 的待发布内容归档到目标版本 `## [X.Y.Z] - YYYY-MM-DD`，保留 `Unreleased`，并包含内容对应的 `### English` 和 `### 简体中文`。

沿用第 2 节确定的版本，先检查发布说明：

```bash
python3 scripts/release-notes.py "v${RELEASE_VERSION}"
git diff --check
```

这两条命令仅在本地检查发布说明和改动格式。确认后提交代码和 CHANGELOG，保持工作区干净。确认发布分支、`origin` 正确，GitHub Actions 已配置 `FEISHU_APP_ID`、`FEISHU_APP_SECRET`、`APPSTORE_IP`、`APPSTORE_TOKEN`，再执行：

```bash
bash ictrek.app/scripts/update_version.sh "$RELEASE_PART"
```

递增类型与第 2 节保持一致，当前 VERSION 应仍为第 2 节记录的基线。

脚本更新并提交 `ictrek.app/VERSION`，创建 `vos-v-voice-vX.Y.Z`，原子推送当前分支和触发标签。GitHub Actions 随后执行检查、读取飞书镜像和已发布的 V-Scheduler 依赖、重新生成正式安装包，创建公开 `vX.Y.Z` Release，并发布到 VOS App Store。正式打包前保持测试通过的镜像引用不变，并核对 CI 解析的依赖与测试包一致；镜像或依赖变化时重新测试。

不要提前修改 VERSION 或手工创建公开标签。CHANGELOG 必须提前提交，本项目没有 `--with-changelog` 参数。

## 6. 观察 GitHub Actions

```bash
gh run list --repo ictrektech/V-yovoice --workflow vos-release.yml --limit 5
RUN_ID=123456789 # 替换为本次正式发布的实际运行编号
gh run watch "$RUN_ID" --repo ictrektech/V-yovoice --exit-status
```

## 7. 发布后核对

完成后核对 Release 和商店发布日志：

```bash
RELEASE_VERSION="$(tr -d '[:space:]' < ictrek.app/VERSION)"
gh release view "v${RELEASE_VERSION}" --repo ictrektech/V-yovoice \
  --json tagName,url,assets,body
gh run view "$RUN_ID" --repo ictrektech/V-yovoice --log \
  | rg 'v_voice_|PASS: App Store'
```

确认 Release 包含 `v_voice_X.Y.Z_pull.tar`、双语说明正确，日志同时包含商店上传成功和版本回读成功。最终报告版本、Release 链接、包名、CI run ID 和商店发布结果。

## 失败处理

- 镜像构建、推送或飞书写入失败：修复后补齐，不继续创建发布标签。构建失败可能留下中间镜像，不能直接用 `--publish-only` 发布。
- 工作区不干净或标签已存在：先处理改动或检查已有发布，不强制覆盖标签。
- CI 检查或依赖解析失败：查看对应步骤并修复，不绕过检查。
- 公开标签尚未创建：修复并推送代码；如影响镜像，先重新构建发布。保持失败版本的 VERSION 不变，然后使用下方命令重试。
- GitHub Release 已成功、商店失败：修复连接后重跑原 CI；流程会复用已有 Release 包。不要重新递增版本或移动标签。

公开标签创建前的修复重试：

```bash
RELEASE_VERSION="$(tr -d '[:space:]' < ictrek.app/VERSION)"
VVOICE_RELEASE_BRANCH=main # 替换为已推送修复的实际分支
gh workflow run vos-release.yml --repo ictrektech/V-yovoice \
  --ref "$VVOICE_RELEASE_BRANCH" -f retry_version="$RELEASE_VERSION"
```

重跑原 CI 使用 `gh run rerun "$RUN_ID" --repo ictrektech/V-yovoice`。不传 `retry_version` 的手动触发只运行依赖访问预检，不会打包发布。

## 已发布版本只替换 GitHub 安装包

仅在明确保留版本号、补发 GitHub 附件时使用。先完成镜像验证、推送和飞书回读，再备份旧附件并用原打包器生成同版本安装包：

```bash
VVOICE_RELEASE_BACKUP="$HOME/dev/build/v-yovoice/release-backups/0.0.30-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$VVOICE_RELEASE_BACKUP"
gh release download v0.0.30 --repo ictrektech/V-yovoice \
  --pattern v_voice_0.0.30_pull.tar --dir "$VVOICE_RELEASE_BACKUP"
bash ictrek.app/scripts/package.sh --version 0.0.30
```

按第 4 节检查安装包结构，并确认只更新了预期平台的镜像引用。随后替换同名附件：

```bash
gh release upload v0.0.30 ictrek.app/dist/v_voice_0.0.30_pull.tar \
  --repo ictrektech/V-yovoice --clobber
```

重新下载附件，比对 SHA256、包内版本和镜像引用，并在 Release 正文注明补发日期、镜像与源码提交。此操作不移动 Git 标签、不递增版本，也不更新 VOS App Store 或已安装实例。现有 CI 重跑会复用 GitHub 上的附件，不能代替上述替换步骤。

`--clobber` 会先删除同名旧附件再上传；上传失败时，从备份目录用同一条上传命令恢复旧包。

脚本依据：[镜像构建](../../docker/build_image.sh)、[版本发布](../../ictrek.app/scripts/update_version.sh)、[CI 流程](../../.github/workflows/vos-release.yml)、[VOS 打包说明](../../ictrek.app/README.md)。
