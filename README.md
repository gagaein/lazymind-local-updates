# 8094 本地改动分享

本仓库用于逐行评审和获取 8094 当前使用的全部代码改动，不是完整 LazyMind 应用。

- 原项目：https://github.com/LazyAGI/LazyMind
- 对应基线：`6d18bbbb183fabc37de41116fbb6f92a907a6aa7`
- `main` 保存此次变更涉及的 9 个文件在基线中的原版。
- `codex/8094-local-updates-20261028` 保存这 9 个文件的当前修改版。
- PR 只显示这 9 个文件的差异；源码保留原路径，便于应用补丁。
- 本地配置、密钥、数据库、用户素材、生成产物及日志均未包含。

## 主要内容

源文档导入与修订保留、显式要求和图片清单传递、有序多图绑定和复用、必需图片检查，以及需求分析与派生控制标记的批量发布。

## 将改动应用到完整项目

先获取 PR 的补丁（将 `<PR编号>` 替换为实际编号，需要本私有仓库的访问权限）：

```bash
gh pr diff <PR编号> --repo gagaein/lazymind-local-updates --patch > /tmp/8094-local-updates.patch
```

在完整 LazyMind 项目中，从上述基线建立单独分支，再应用补丁：

```bash
git switch -c codex/8094-local-updates 6d18bbbb183fabc37de41116fbb6f92a907a6aa7
git submodule update --init --recursive
git apply --check /tmp/8094-local-updates.patch
git apply /tmp/8094-local-updates.patch
```

现有项目有未提交内容时，先保留这些内容；不要覆盖工作区。安装和启动请沿用完整项目的文档及本机配置。

## 验证范围

相同补丁已在完整基线代码上验证：页面提示词与图片绑定 48 项、风格和源文档契约 25 项、局部编辑 72 项，合计 145 项测试通过。工作流 YAML 和 Git 差异检查通过。9 个修改文件与 8094 当前文件逐字节一致。

上述结果为本地专项检查；未重新验收真实飞书在线导入和完整 PPT 生成。

## 来源与许可

所含 LazyMind 源码来自上述项目并保留原文件说明；原项目 Apache-2.0 许可见 `LICENSE`。
