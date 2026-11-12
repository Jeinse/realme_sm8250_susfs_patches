#!/usr/bin/env bash
# Apply the reviewed Entropy-1.7 SUSFS core + inline-hook patch.
# Upstream attribution and source revisions are recorded in SOURCE_MANIFEST.json.
set -euo pipefail

readonly PATCH_FILE='entropy-1.7-susfs-2.4.0-jack.patch'
readonly PATCH_SHA256='d3e94cdb3c78e20c2413acc6b8da96694ae5ebdca70211849970146716eba2a1'
readonly TESTED_BASE='12a4f30d3027b12ce27dec8c72b56b2a570e0812'

usage() {
    cat <<'EOF'
Usage: bash susfs_inline_hook_patches.sh [--check] [--ref COMMIT_SHA] [KERNEL_ROOT]

Apply the reviewed SUSFS 2.3.0 core and inline hooks to Entropy-1.7.
KERNEL_ROOT defaults to the current directory.
--check validates without changing kernel source files.
--ref pins remote patch downloads to the same full commit as this script.
Already-applied patches are detected and skipped.
Defconfig and BakaSU driver setup remain under your control.
EOF
}

die() {
    printf 'Error: %s\n' "$*" >&2
    exit 1
}

check_only=false
kernel_arg=''
patch_ref=${SUSFS_PATCHES_REF:-main}
while (($#)); do
    case "$1" in
        --check) check_only=true ;;
        --ref) (($# >= 2)) || die '--ref requires a full commit SHA.'
            patch_ref=$2
            shift ;;
        -h|--help) usage; exit 0 ;;
        --) shift; (($# <= 1)) || die 'Expected one kernel directory.'
            if (($#)); then
                [[ -z "$kernel_arg" ]] || die 'Expected one kernel directory.'
                kernel_arg=$1
            fi
            break ;;
        -*) die "Unknown option: $1" ;;
        *) [[ -z "$kernel_arg" ]] || die 'Expected one kernel directory.'
            kernel_arg=$1 ;;
    esac
    shift
done

if [[ "$patch_ref" != main && ! "$patch_ref" =~ ^[0-9a-f]{40}$ ]]; then
    die 'Patch ref must be main or a full lowercase commit SHA.'
fi
readonly PATCH_URL="https://raw.githubusercontent.com/Jeinse/realme_sm8250_susfs_patches/${patch_ref}/patches/${PATCH_FILE}"

for tool in git sha256sum awk mktemp; do
    command -v "$tool" >/dev/null 2>&1 || die "Required command not found: $tool"
done

kernel_dir=$(cd -- "${kernel_arg:-.}" && pwd -P) || die 'Kernel directory does not exist.'
[[ -f "$kernel_dir/Makefile" && -d "$kernel_dir/fs" && -d "$kernel_dir/arch/arm64" ]] ||
    die 'Run this script from an ARM64 kernel root or pass its path.'
git_root=$(git -C "$kernel_dir" rev-parse --show-toplevel 2>/dev/null) || die 'Kernel directory must be a Git checkout.'
git_root=$(cd -- "$git_root" && pwd -P)
[[ "$git_root" == "$kernel_dir" ]] || die 'KERNEL_ROOT must be the root of the kernel checkout.'
kernel_version=$(awk '$1 == "VERSION" { major=$3 } $1 == "PATCHLEVEL" { minor=$3 } END { print major "." minor }' "$kernel_dir/Makefile")
[[ "$kernel_version" == '4.19' ]] || die "Expected a 4.19 kernel; found ${kernel_version}."

patch_path=''
script_source=${BASH_SOURCE[0]:-}
if [[ -n "$script_source" && -f "$script_source" ]]; then
    script_dir=$(cd -- "$(dirname -- "$script_source")" && pwd -P)
    if [[ -f "$script_dir/patches/$PATCH_FILE" ]] &&
       { [[ "$patch_ref" == main ]] || [[ "$(git -C "$script_dir" rev-parse HEAD 2>/dev/null)" == "$patch_ref" ]]; }; then
        patch_path="$script_dir/patches/$PATCH_FILE"
    fi
fi

temp_dir=''
cleanup() {
    if [[ -n "$temp_dir" ]]; then
        rm -rf -- "$temp_dir"
    fi
}
trap cleanup EXIT
if [[ -z "$patch_path" ]]; then
    command -v curl >/dev/null 2>&1 || die 'curl is required when the local patch is unavailable.'
    temp_dir=$(mktemp -d)
    patch_path="$temp_dir/$PATCH_FILE"
    curl --fail --location --silent --show-error --retry 3 "$PATCH_URL" --output "$patch_path"
fi
actual_sha=$(sha256sum < "$patch_path")
actual_sha=${actual_sha%% *}
[[ "$actual_sha" == "$PATCH_SHA256" ]] || die 'Patch checksum mismatch; no kernel files were changed.'

if git -C "$kernel_dir" apply --reverse --check --whitespace=nowarn "$patch_path" >/dev/null 2>&1; then
    printf 'SUSFS core and inline hooks are already applied; skipped.\n'
    exit 0
fi

if ! git -C "$kernel_dir" apply --check --whitespace=nowarn "$patch_path"; then
    printf '\nTested baseline: %s\n' "$TESTED_BASE" >&2
    die 'Patch does not apply cleanly. Check the kernel revision and existing hooks; no kernel files were changed.'
fi
if [[ "$check_only" == true ]]; then
    printf 'Check passed; kernel source files were not changed.\n'
    exit 0
fi

# No --reject or --whitespace=fix: keep application atomic and preserve upstream bytes.
git -C "$kernel_dir" apply --whitespace=nowarn "$patch_path"
printf 'Applied SUSFS 2.3.0 core and inline hooks. Configure SUSFS mode and integrate BakaSU before building.\n'
