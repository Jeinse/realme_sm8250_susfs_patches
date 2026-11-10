# 自动跟踪、人工构建与真机测试

## 自动流程做什么

`Sync Jack SUSFS candidate (source checks only)` 每天 UTC 03:17（北京时间约 11:17）检查一次，也可以从 Actions 页面手动执行；适配器或同步脚本合入 main 时也会检查一次。GitHub 的定时任务可能延后；无需为了跟踪更新一直运行 Android-Builder。

只比较 Jack 的两个实际输入文件内容：

- `Patches/Patch/susfs_patch_to_4.19.patch`
- `Patches/susfs_inline_hook_patches.sh`

Jack 其他文件变化不会单独触发补丁重做。手动执行时可以指定完整 `jack_commit`；勾选 `force` 可以对相同输入重新验证。

发现变化后，生成器固定使用 `config/sources.json` 中记录的内核和 BakaSU 提交。先在干净基线上应用上游主补丁，再核对这次人工审查过的七个拒绝块。校验包含每一行上下文和新增/删除内容，只有行号漂移不影响校验。任何块发生内容变化、出现新冲突或少了已审核块，都会停止，而不是推测新的适配方法。

`compat/entropy-1.7-fixups.patch` 只补这七处已知差异。完成后执行上游原始 inline 脚本，使用固定 BakaSU 提供检测视图。新增的三个 SUSFS 文件必须仍与上游补丁内嵌源码逐字节相同。

自动验证包括：

1. 脚本语法、限定的修改范围、已审核冲突指纹。
2. BakaSU 官方 inline hook 检查。这里的 `make -f ... validate` 只执行符号/钩子检查，不调用内核 Makefile，不编译 C 文件。
3. 新补丁在第二份干净源码上的应用检查、实际应用、反向检查与结果一致性。
4. 候选补丁、入口常量、来源清单和校验值的一致性。

**没有自动编译目标文件、完整内核、模块或镜像，也不会触发 Android-Builder，更不会自动刷机、合并 PR 或更新稳定补丁。**所有新候选的编译与真机状态明确记录为 `pending`。

## 如何取得候选版本

检查通过后，在本仓库创建新的 `candidate/jack-...` 分支和 Draft PR。候选分支不会被后续运行强制覆盖；已有人工修改时发布器停止。关闭但未合并的 PR 也不会每天被自动重开。

如果 GitHub 阻止 `GITHUB_TOKEN` 创建 PR，候选分支仍会保留，Actions Summary 会给出比较链接。可以手动创建 PR，或到仓库 **Settings → Actions → General → Workflow permissions** 允许 Actions 创建 PR。无需为正常流程添加个人访问令牌。只给发布 job 内容与 PR 写权限；执行上游脚本的生成 job 没有写权限和发布凭据。

失败时到该次 Actions 运行下载 `jack-susfs-source-candidate` 日志，稳定 `main` 不受影响。它可能包含只有部分应用的诊断文件，**只有成功生成 `report.json` 且发布成功的候选分支才能用于测试**。

## 用 Android-Builder 手动构建

先打开 Draft PR，复制正文中 **Candidate revision to build** 的完整 40 位提交号。不要仅复制 Jack 的提交号，也不要继续使用指向稳定 `main` 的调用命令，否则构建的仍是旧稳定补丁。

把 Android-Builder 的“应用 SUSFS 补丁”步骤临时改为下面形式，在内核根目录运行：

```bash
SUSFS_PATCHES_REV=替换成候选分支的完整40位提交号
curl -fLSs "https://raw.githubusercontent.com/Jeinse/realme_sm8250_susfs_patches/${SUSFS_PATCHES_REV}/susfs_inline_hook_patches.sh" \
  | bash -s -- --ref "$SUSFS_PATCHES_REV"
```

`--ref` 让脚本与远程补丁来自同一个提交。本地克隆并检出同一个提交再执行脚本也可以。不要仅固定入口 URL、却继续下载 `main` 的补丁。

同时确认：

- 内核基线与 PR 记录一致，或者只增加了你的设备 defconfig 等已知改动；源码没有已经提交的旧 SUSFS。新版完整补丁不能直接叠加到旧版上。
- BakaSU 使用 PR 记录的精确提交，避免在验证 Jack 更新时同时更换驱动版本。`setup.sh` 支持传入提交号；可以用固定提交的 setup 脚本并把同一提交号传给它。
- 保留你实际要使用的设备配置、工具链、LTO/CFI 设置；不要为了让候选过编译而静默关闭原有功能。
- 本仓库的脚本仍不修改 defconfig。继续使用 Android-Builder 中你已有的配置步骤。

然后手动启动 Android-Builder，完成全内核和模块/镜像构建。将构建运行链接填入 PR 正文。

## 刷机验证与发布

由你保留可回退镜像，刷入候选并验证设备启动、Root 授权、模块挂载、文件操作、休眠唤醒，以及实际启用的 SUSFS 功能。源码检查通过、甚至成功开机，都不代表所有运行场景正确。

在 PR 中记录设备、ROM、构建链接、测试结果和实际测试的候选提交。若补丁又有变化，应重新构建和验证对应的新提交。测试完成后由你将 Draft PR 标记为 Ready 并合并；本仓库没有自动晋升或自动合并逻辑。

正式构建也建议固定补丁仓库的具体发布提交，并保留上一版镜像及各来源提交号。日常监测不要求立即升级稳定版本。

## 适配器需要人工更新的情况

上游改写了已审核的七个块、钩子函数签名变化、新增脚本修改文件、SUSFS 版本格式改变，或你要更新内核/BakaSU 固定提交时，都可能停止生成。这时应审查差异，更新 `compat/` 或 `config/sources.json`，重做验证，再提交适配器变更。

不要通过删除指纹检查、增加 `|| true`、接受残留 `.rej` 或扩大模糊匹配来绕过失败。

## 本地复现

只需 Python 3、Git、Bash、Make，以及能够读取这三个公共 GitHub 仓库的网络。不需要安装交叉编译器。

```bash
python3 -m unittest discover -s tests -v
python3 scripts/sync_jack.py verify-repository
python3 scripts/sync_jack.py check --cache /tmp/susfs-cache --out /tmp/susfs-candidate
python3 scripts/sync_jack.py generate --cache /tmp/susfs-cache --out /tmp/susfs-candidate
```

`generate` 输出只用于候选和审查，不会写入稳定补丁。`--jack-ref` 可指定完整上游提交，`--force` 用于重放相同输入。
