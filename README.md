# realme_sm8250_susfs_patches

为 `bijoyv9/android_kernel_realme_sm8250:Entropy-1.7` 提供已适配的 Jack SUSFS 2.3.0 主补丁与 inline hook。

`susfs_inline_hook_patches.sh` 是合并补丁的调用入口。它应用此前验证过的补丁，包含 SUSFS 内核实现和 inline 钩子；原有钩子代码保持不变，设备适配见 [ADAPTATION.md](ADAPTATION.md)。

## 调用

在内核源码根目录执行：

```bash
curl -fLSs https://raw.githubusercontent.com/Jeinse/realme_sm8250_susfs_patches/main/susfs_inline_hook_patches.sh | bash
```

或者克隆本仓库，在本地调用，不需要额外下载补丁：

```bash
git clone --depth=1 https://github.com/Jeinse/realme_sm8250_susfs_patches.git /tmp/realme-sm8250-susfs-patches
bash /tmp/realme-sm8250-susfs-patches/susfs_inline_hook_patches.sh /你的内核源码目录
```

只检查、不修改内核源码：

```bash
bash /tmp/realme-sm8250-susfs-patches/susfs_inline_hook_patches.sh --check /你的内核源码目录
```

脚本校验补丁的 SHA-256，确认补丁可以完整应用后才修改源码。重复调用会检测并跳过已应用的补丁；遇到冲突直接停止，不接受 `.rej` 或自动清理源码。

## 使用范围

- 已验证的内核基线：`12a4f30d3027b12ce27dec8c72b56b2a570e0812`。
- 从未集成旧 KSU/SukiSU/BakaSU 手动钩子的基线开始。不要额外叠加之前的手动 BakaSU hook 补丁，也不要重复执行 Jack 原版 sed 脚本。
- 脚本不修改 defconfig，不下载或注册 BakaSU 驱动；继续使用你的驱动集成和编译流程。
- 构建入口只应用固定版本的适配结果，不会临时拉取 Jack 最新代码。独立的同步工作流会检测更新、生成源码检查通过的候选分支与 Draft PR；编译和刷机由你手动完成，测试后再合并。

## 自动同步候选，手动构建测试

已提供两个工作流：

- **Sync Jack SUSFS candidate (source checks only)**：每天一次或手动检测 Jack 两份输入，重放审核过的七处适配，检查后发布候选分支/Draft PR。
- **Validate source tools (no kernel compilation)**：检查生成工具、元数据和补丁一致性。

两者均不编译内核，不触发 Android-Builder，也不自动合并候选。未知冲突会停止，稳定补丁保持原样。

候选和正式构建均建议整体固定到本仓库的精确提交。远程入口支持 `--ref <完整提交号>`，让脚本与补丁保持同一版本。详细的 Android-Builder 调用、手工编译/刷机和 PR 合并流程见 [SYNC_AND_TEST.md](docs/SYNC_AND_TEST.md)。

## 配置由你维护

在实际参与构建的设备 defconfig 中选择：

```text
CONFIG_KSU=y
CONFIG_KSU_SUSFS=y
CONFIG_THREAD_INFO_IN_TASK=y
CONFIG_DEBUG_KERNEL=y
CONFIG_KALLSYMS=y
CONFIG_KALLSYMS_ALL=y
# CONFIG_KSU_MANUAL_HOOK is not set
# CONFIG_KSU_TRACEPOINT_HOOK is not set
```

SUSFS 子功能按需开启，并检查合并设备配置后生成的最终 `.config`。脚本不会替你修改上述选项。

## 验证范围

首次发布版本（Jack `732feefc0`）在干净基线上通过应用检查、实际应用及反向检查；27 个结果文件一致。使用 BakaSU 官方 inline 检查通过，24 个改动 C 文件在 ARM64、Clang 18.1.3、LTO、CFI 与 `-Werror` 下通过目标文件编译。这项历史编译结果不适用于后续自动生成的新候选。

完整内核链接、BakaSU 全驱动构建和真机启动不在上述历史验证范围内。新候选仅执行源码检查，其编译和真机状态始终等待你手动记录。版本及校验值见 [SOURCE_MANIFEST.json](SOURCE_MANIFEST.json)。

## 上游来源

- Jack 仓库：[JackA1ltman/NonGKI_Kernel_Build_2nd](https://github.com/JackA1ltman/NonGKI_Kernel_Build_2nd)。采用提交 `732feefc0d4132bc313d39d7a511b9b7bbe51ddb`。
- [Jack 的 4.19 主补丁](https://github.com/JackA1ltman/NonGKI_Kernel_Build_2nd/blob/732feefc0d4132bc313d39d7a511b9b7bbe51ddb/Patches/Patch/susfs_patch_to_4.19.patch)内包含 `fs/susfs.c`、`include/linux/susfs.h` 和 `include/linux/susfs_def.h`，本仓库的补丁完整保留这三个文件。
- [Jack 的 inline 脚本](https://github.com/JackA1ltman/NonGKI_Kernel_Build_2nd/blob/732feefc0d4132bc313d39d7a511b9b7bbe51ddb/Patches/susfs_inline_hook_patches.sh)。
- 原始 SUSFS 上游：[simonpunk/susfs4ksu](https://gitlab.com/simonpunk/susfs4ksu)。
- 配套检查使用 BakaSU 提交 `516d3e87fbc986ccefdde2c2765f1700612441a9`。
