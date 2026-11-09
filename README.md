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
- 本仓库保存固定版本的适配结果，不会在构建时自动拉取 Jack 或 SUSFS 最新代码。上游更新需要重新适配和验证。

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

原补丁在干净基线上通过应用检查、实际应用及反向检查；27 个结果文件一致。使用 BakaSU 官方 inline 检查通过，24 个改动 C 文件在 ARM64、Clang 18.1.3、LTO、CFI 与 `-Werror` 下通过目标文件编译。

完整内核链接、BakaSU 全驱动构建和真机启动不在上述验证范围内。版本及校验值见 [SOURCE_MANIFEST.json](SOURCE_MANIFEST.json)。

## 上游来源

- Jack 仓库：[JackA1ltman/NonGKI_Kernel_Build_2nd](https://github.com/JackA1ltman/NonGKI_Kernel_Build_2nd)。采用提交 `732feefc0d4132bc313d39d7a511b9b7bbe51ddb`。
- [Jack 的 4.19 主补丁](https://github.com/JackA1ltman/NonGKI_Kernel_Build_2nd/blob/732feefc0d4132bc313d39d7a511b9b7bbe51ddb/Patches/Patch/susfs_patch_to_4.19.patch)内包含 `fs/susfs.c`、`include/linux/susfs.h` 和 `include/linux/susfs_def.h`，本仓库的补丁完整保留这三个文件。
- [Jack 的 inline 脚本](https://github.com/JackA1ltman/NonGKI_Kernel_Build_2nd/blob/732feefc0d4132bc313d39d7a511b9b7bbe51ddb/Patches/susfs_inline_hook_patches.sh)。
- 原始 SUSFS 上游：[simonpunk/susfs4ksu](https://gitlab.com/simonpunk/susfs4ksu)。
- 配套检查使用 BakaSU 提交 `516d3e87fbc986ccefdde2c2765f1700612441a9`。
