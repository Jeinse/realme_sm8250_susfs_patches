# realme SM8250 SUSFS 补丁

面向 realme SM8250、Linux 4.19 `Entropy-1.7` 的 SUSFS 补丁与自动更新工具。项目跟踪 Jack 的 4.19 主补丁和 inline hook 脚本，将内核实现、钩子及设备兼容改动合并为可直接应用的补丁。

`main` 保存当前发布版本，`candidate/...` 保存待测试版本。内核基线、驱动版本和补丁来源均记录在 [SOURCE_MANIFEST.json](SOURCE_MANIFEST.json)。

## 自动适配原理

1. **检测更新**：每天或手动检查 Jack 的主补丁与 inline 脚本，仅在这两个文件的内容变化时生成新候选；也可手动强制重做。
2. **重现适配**：在固定版本的干净内核上应用主补丁，核对七处已审核的冲突内容，再应用对应的设备修正并执行上游 inline 脚本。
3. **检查结果**：执行 BakaSU 官方钩子检查，确认三个 SUSFS 核心文件与 Jack 主补丁中的源码逐字节一致，再用另一份干净源码验证补丁应用、反向检查和结果一致性。
4. **提交候选**：检查通过后创建候选分支和草稿合并请求（PR）。完整编译、刷机测试及合并由维护者完成。

自动适配的基础是复用已审核规则。出现新冲突，或已审核冲突块的内容变化时，流程会停止，待维护者更新规则后再生成候选。自动流程只做源码检查，不编译内核，也不自动合并。

## 使用

在干净的目标内核源码根目录，以 Bash 执行当前发布版本：

```bash
set -o pipefail
curl -fLSs "https://raw.githubusercontent.com/Jeinse/realme_sm8250_susfs_patches/main/susfs_inline_hook_patches.sh" | bash
```

候选测试或需要固定版本的构建，应使用 PR 中记录的**补丁仓库完整提交号**，使脚本和补丁来自同一版本：

```bash
set -o pipefail
SUSFS_PATCHES_REV='替换为补丁仓库的完整40位提交号'
curl -fLSs "https://raw.githubusercontent.com/Jeinse/realme_sm8250_susfs_patches/${SUSFS_PATCHES_REV}/susfs_inline_hook_patches.sh" \
  | bash -s -- --ref "$SUSFS_PATCHES_REV"
```

入口脚本支持 `--check` 仅检查，默认在校验补丁 SHA-256、确认可以完整应用后修改源码；已应用的相同补丁会跳过，发生冲突则停止。基线中不应叠加旧的手动 KSU/SUSFS 钩子。

BakaSU 驱动集成和内核配置（defconfig）由构建流程维护。Android-Builder 调用、版本固定及测试步骤见 [构建与测试说明](docs/SYNC_AND_TEST.md)。历史验证结果以对应提交的来源清单为准，不代表后续候选已通过编译或真机测试。

## 文件说明

| 文件 | 作用 |
| --- | --- |
| [README.md](README.md) | 项目概览、使用方法与维护入口。 |
| [susfs_inline_hook_patches.sh](susfs_inline_hook_patches.sh) | 构建时的应用入口，负责补丁下载、校验、应用检查及重复调用处理。 |
| [patches/*.patch](patches/) | 按版本保存的完整补丁，包含 SUSFS 内核实现、inline 钩子和设备适配；当前入口使用的文件由来源清单记录。 |
| [SOURCE_MANIFEST.json](SOURCE_MANIFEST.json) | 记录对应版本的上游提交、补丁与入口校验值，以及验证状态。 |
| [config/sources.json](config/sources.json) | 设置上游地址、跟踪分支、内核和 BakaSU 固定提交，以及 inline 脚本允许改动的文件范围。 |
| [compat/entropy-1.7-rejections.json](compat/entropy-1.7-rejections.json) | 保存七处已审核冲突的内容校验值，用于识别相关上游代码是否发生变化。 |
| [compat/entropy-1.7-fixups.patch](compat/entropy-1.7-fixups.patch) | 对上述七处冲突应用已审核的 Entropy-1.7 兼容改动。 |
| [scripts/sync_jack.py](scripts/sync_jack.py) | 检测上游变化、重现适配、生成完整补丁并输出源码检查报告。 |
| [scripts/publish_candidate.py](scripts/publish_candidate.py) | 核对生成结果，创建候选分支和草稿 PR，保留已有人工修改。 |
| [.github/workflows/sync-jack-susfs.yml](.github/workflows/sync-jack-susfs.yml) | 定时及手动同步入口，分别安排候选生成与发布任务。 |
| [.github/workflows/validate.yml](.github/workflows/validate.yml) | 在提交、PR 或手动运行时检查单元测试、补丁元数据和入口一致性。 |
| [tests/test_sync.py](tests/test_sync.py) | 检查冲突识别、版本参数、校验失败和候选发布边界等行为。 |
| [ADAPTATION.md](ADAPTATION.md) | 记录设备差异、钩子落点及七处兼容改动的依据。 |
| [docs/SYNC_AND_TEST.md](docs/SYNC_AND_TEST.md) | 说明同步操作、人工构建、刷机验证、合并及失败排查。 |
| [verification/wrapper-checks.json](verification/wrapper-checks.json) | 入口脚本的历史检查记录，包括重复调用、冲突及校验失败处理。 |
| [.gitignore](.gitignore) | 排除 Python 缓存和本地 `candidate-output/` 生成目录。 |

候选分支另含 `verification/candidate-source-checks.json`，记录该次生成的来源、校验值、源码检查结果，以及待完成的人工构建和真机测试。

## 修改与扩展

来源配置、设备兼容规则、补丁生成和候选发布分别维护，便于单独调整：

| 调整内容 | 修改位置 |
| --- | --- |
| 更换跟踪分支、内核或 BakaSU 版本 | `config/sources.json`。 |
| 更新设备兼容改动 | 两个 `compat/` 文件，并同步维护 `ADAPTATION.md`；冲突数量变化时还需调整生成器和测试。 |
| 修改检查频率或工作流步骤 | `.github/workflows/`。 |
| 增加检查、调整生成或发布逻辑 | `scripts/` 和 `tests/test_sync.py`。 |
| 移植其他设备或内核 | 同步更新来源配置、兼容规则，以及生成器和入口脚本中的内核版本、架构、路径和命名约束。 |

当前实现围绕单一 Entropy-1.7 基线编写。新增设备需要独立适配和验证；适配逻辑应维护在配置与兼容规则中，再由生成器输出版本补丁。

修改配置或规则后，可在 Actions 手动执行同步并勾选 `force` 重新生成候选。提交前的基础检查：

```bash
python3 -m unittest discover -s tests -v
python3 scripts/sync_jack.py verify-repository
```

新候选经完整构建和真机验证后，再手动合并到 `main`。

## 上游来源

- 内核基线：[bijoyv9/android_kernel_realme_sm8250](https://github.com/bijoyv9/android_kernel_realme_sm8250)，`Entropy-1.7` 分支。
- 4.19 补丁及 inline 脚本：[JackA1ltman/NonGKI_Kernel_Build_2nd](https://github.com/JackA1ltman/NonGKI_Kernel_Build_2nd)。
- 钩子检查：[Baka-SU/BakaSU](https://github.com/Baka-SU/BakaSU)。
- 原始 SUSFS 项目：[simonpunk/susfs4ksu](https://gitlab.com/simonpunk/susfs4ksu)。
