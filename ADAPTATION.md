# 手动适配记录

基线是未修改的 bijoyv9 `Entropy-1.7@12a4f30d3027b12ce27dec8c72b56b2a570e0812`，没有先应用之前的 BakaSU 手动钩子。

## 主补丁：7 个拒绝块

| 文件 | 原补丁不能直接应用的原因 | 本次处理 |
| --- | --- | --- |
| `fs/Makefile` | 上游已有 `fs_types.o fs_context.o fs_parser.o`，对象列表上下文不同 | 保留现有对象列表，在列表后原样加入 `obj-$(CONFIG_KSU_SUSFS) += susfs.o` |
| `fs/namespace.c`，头部 | 已回移 `linux/fs_context.h` | 保留该头文件，把 SUSFS include、extern 和宏块放到对应位置 |
| `fs/namespace.c`，挂载分配 | 原补丁在旧 `vfs_kern_mount()` 中的 `alloc_vfsmnt(name)` 前后插入钩子；此基线的实际分配已移至 `vfs_create_mount(struct fs_context *fc)` | 将同一钩子块放在 `vfs_create_mount()` 的分配点；在同一条件宏内新增局部 `const char *name = fc->source;`，从而保留 Jack 钩子中 `susfs_alloc_non_unshare_ksu_vfsmnt(name ?:"none")` 原句；现有正常分配和 `fs_context` 流程不变 |
| `fs/proc/task_mmu.c`，`pagemap_read()` | 已使用 `mmap_read_lock_killable()` 和 `mmap_read_unlock()` | 保留已有锁接口，在同一临界区中原样加入 SUS_MAP 检查和跳转标签 |
| `fs/super.c`，头部 | 已回移 `linux/fs_context.h` | 保留现有头文件，补齐原样的 SUSFS include/extern 块 |
| `mm/memory.c`，头部 | 已使用 `linux/pgtable.h`，且原补丁末尾上下文与此基线不同 | 在现有头文件之后原样加入 SUSFS 条件 include |
| `mm/memory.c`，`__access_remote_vm()` | 已使用 `mmap_read_lock_killable()` | 保留现有锁接口，原样加入 `vma = find_vma()` 和 SUS_MAP 检查块 |

除了挂载分配点所需的条件局部变量，没有修改上述钩子的表达式、返回值、函数签名或分支逻辑。没有把新的内核接口退回旧实现。

## Inline 脚本

在主补丁全部补齐后，从内核根目录执行固定提交的原始脚本。脚本执行时临时提供当前 BakaSU 的 `drivers/kernelsu` 视图，以使其按实际驱动接口检测 `setresuid` 等分支。

- `fs/exec.c`、`fs/open.c`、`fs/read_write.c`、`fs/stat.c`、`drivers/input/input.c`、`kernel/reboot.c`、`kernel/sys.c`、`security/selinux/hooks.c` 的生成代码保持原样。
- `filename_lookup()` 在此内核中已经不是 static，不需要另改导出方式；脚本为 `fs/stat.c` 补上了 `internal.h`。
- 当前 BakaSU 没有 `ksu_hide_setprocattr`，按脚本原判断跳过该分支。
- `security/security.c` 和 `security/selinux/ss/services.c` 的旧内核兼容分支按脚本原判断跳过。
- 未叠加 Jack 的一加设备 `susfs_fixed.patch`。

脚本原始输出和编译验证见 `verification/`。脚本提示成功本身不能证明钩子完整，本次额外执行了 BakaSU 官方检查和全部改动 C 文件的目标编译。
