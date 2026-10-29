# 8094 本地改动分享

本仓库用于逐行评审和获取 8094 当前使用的全部代码改动，不是完整 LazyMind 应用。

- 原项目：https://github.com/LazyAGI/LazyMind
- 对应基线：`2ddbde2742cc5dca427d3412c02d662cfe1f18fa`。
- `main` 保存此次变更涉及的已跟踪文件在该基线中的原版。
- `codex/8094-local-updates-20261028` 保存 8094 当前全部本地修改，共 69 个文件。
- PR 只显示相对 2ddbde27 的本地增量；源码保留原路径，便于直接应用补丁。
- 本地配置、密钥、数据库、用户素材、生成产物及日志均未包含。

## 主要内容

- PPT 工作流：源文档快速阅读、要求提取、有序多图绑定、局部编辑和风格流程修复。
- 文档预览：首次解析失败后可自动恢复正常富文本显示。
- 执行可靠性：租约过期宽限与重试、精确取消、远程执行器状态收口。
- 状态一致性：系统中断、用户暂停和失败状态分离，左侧工作流与右侧子任务一致。
- 数据库：保留 8094 当前工作区中的本地迁移文件。

## 将改动应用到完整项目

获取 PR #1 的补丁：

```bash
gh pr diff 1 --repo gagaein/lazymind-local-updates --patch > /tmp/8094-local-updates.patch
```

在完整 LazyMind 项目中，从上述基线建立单独分支，再应用补丁：

```bash
git switch -c codex/8094-local-updates 2ddbde2742cc5dca427d3412c02d662cfe1f18fa
git submodule update --init --recursive
git apply --check /tmp/8094-local-updates.patch
git apply /tmp/8094-local-updates.patch
```

现有项目有未提交内容时，先保留这些内容；不要覆盖工作区。安装和启动请沿用完整项目的文档及本机配置。

## 验证范围

相同改动已在完整 8094 工作区验证：

- Go：`workflow/displaystate`、`tasktiming`、`taskcenter`、`workflow` 全部通过。
- 前端：5 个相关测试文件，173 项测试通过。
- Python：169 项测试和 22 个子测试通过。
- 69 个 PR 文件与 8094 当前工作区逐字节一致，Git 差异检查通过。

上述结果为本地专项检查；未重新验收真实飞书在线导入和完整 PPT 生成，也不代表全仓既有 TypeScript 错误已清零。

## 来源与许可

所含 LazyMind 源码来自上述项目并保留原文件说明；原项目 Apache-2.0 许可见 `LICENSE`。
