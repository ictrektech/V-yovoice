---
name: v-yovoice-changelog
description: 维护 V-yovoice 的根目录 CHANGELOG.md，审计 VOS 版本以来的用户可见变化，更新 Unreleased 或为指定版本整理中英文发布说明。用户要求整理更新日志、准备 VOS 版本发布说明或调用 $v-yovoice-changelog 时使用；不执行实际发布。
---

# V-yovoice 更新日志

从仓库根目录工作，先读取适用的 AGENTS.md、`CHANGELOG.md`、`ictrek.app/VERSION`、`ictrek.app/scripts/update_version.sh` 和 `scripts/release-notes.py`。以实际文件和用户指令为准；本技能针对 V-yovoice，不套用其他项目的路径或版本规则。

## 工作方式

- `$v-yovoice-changelog`：审计并维护 `## [Unreleased]`，保留已有草稿，补充可证实且缺失的用户可见变化并去重。
- `$v-yovoice-changelog 0.0.31`：整理并归档指定版本。也接受用户明确要求的 patch、minor 或 major 发布准备；按照版本脚本对 `ictrek.app/VERSION` 的计算确定目标版本。不要假设指定版本一定是下一版。
- 用户只要求整理发布说明而未指定版本时，结合上下文确定是否指下一次 patch 发布；无法确定时询问，不擅自归档。

先检查 `git status --short`，保护已有改动。以目标 HEAD 可达、对应当前 `ictrek.app/VERSION` 的 `vos-v-voice-vX.Y.Z` 标签为优先基线；若不存在，检查其他可达 VOS 标签并说明采用的基线及原因。用 `git log` 和相关 `git show` 实际 diff 审计基线到 HEAD 的变化，不仅依赖提交标题；没有可靠基线时说明范围限制。默认不将未提交代码视为已发布的实现，用户明确要求时可检查并标明。现有 Unreleased 条目即使尚无提交证据也要保留，不得静默丢弃。

按用户、部署人员可感知的结果合并相关变更，去重并精简；保留必要的兼容性、升级要求和已知限制，不写纯重构、版本维护或未经证实的承诺。保留现有历史版本正文，除非用户明确要求修改。

## 归档版本

1. 检查目标版本是否已有段落。如果已有，避免重复创建；只在用户明确要求更新该版本时修改。确认 `Unreleased` 的条目属于本次发布；有无法确定归属的内容时保留在 Unreleased 并说明。
2. 保留 `## [Unreleased]`，将本次发布内容整理到其后的唯一 `## [X.Y.Z] - YYYY-MM-DD` 段落，日期使用用户指定的日期或当前本地日期。按项目约定分别提供内容对应、非空的 `### English` 和 `### 简体中文`，使用面向用户的列表条目。保留不属于本次发布的草稿和其他未提交改动。
3. 执行 `python3 scripts/release-notes.py vX.Y.Z` 和 `git diff --check`，检查实际 diff、版本标题唯一性、双语对应与历史内容。校验失败则修正；报告未能验证的事项。

只修改根目录 `CHANGELOG.md`。完成整理和校验后，检查包含暂存、未暂存和未跟踪文件的工作区状态：仅当存在 `CHANGELOG.md` 改动且没有任何其他文件改动时，读取并遵循 `commit` skill，提交该文件；没有改动时不创建空提交。若存在其他改动，不暂存或提交任何文件，保留现场并报告原因。提交前再次检查状态，避免将其他文件带入提交。

本技能不自行更新版本文件、创建标签、推送或发布；若用户另行明确要求这些操作，按用户授权及仓库指引处理。完成后说明修改的章节、审计基线、校验结果、提交结果和仍需人工判断的内容。执行 `update_version.sh` 会提交并推送，整理说明本身不授权执行它。
