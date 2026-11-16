#!/bin/sh
# What can this machine run the Steward gateway on? Run this on a host that has no gateway yet. It looks for an
# NVIDIA GPU (nvidia-smi -L, then /dev/nvidia*), Docker's NVIDIA runtime (docker info), an AMD GPU (/dev/kfd, render
# nodes, rocminfo), an Intel GPU and an NPU, then names the next step. Read-only: it installs nothing and writes
# nothing. It prints the same lines as `steward-gateway hardware`. Guide: docs/guides/gpu.md.
# STEWARD_DETECT_ROOT exists only for the tests; leave it unset.

LC_ALL=C
export LC_ALL
R="${STEWARD_DETECT_ROOT:-}"

# vendor KIND NODE: the node's PCI vendor id, lowercase, with no spaces (empty when unreadable). WSL2 has render
# nodes with no vendor file, so check first: sh reports a failed `<` before a later 2>/dev/null takes effect.
vendor() {
    [ -r "$R/sys/class/$1/$2/device/vendor" ] || return 0
    tr -d ' \t\r\n' < "$R/sys/class/$1/$2/device/vendor" 2>/dev/null | tr 'A-Z' 'a-z'
}

# render_node VENDOR: the first render node of that vendor that also exists in /dev/dri.
render_node() {
    for path in "$R"/sys/class/drm/renderD*; do
        [ -e "$path" ] || continue
        node="${path##*/}"
        if [ "$(vendor "drm" "$node")" = "$1" ] && [ -e "$R/dev/dri/$node" ]; then
            printf '%s\n' "$node"
            return 0
        fi
    done
    return 0
}

NVIDIA=""     # empty when no NVIDIA GPU was found
NVIDIA_NAME=""
RUNTIME=""    # found, missing or unknown; empty when there is no NVIDIA GPU or no docker
AMD=""
GID=""
INTEL=""
NPU=""

# NVIDIA: the driver's own list first. /dev/dxg alone never counts, because WSL exposes every vendor through it.
if command -v nvidia-smi >/dev/null 2>&1; then
    out=$(nvidia-smi -L 2>/dev/null) || out=""
    NVIDIA_NAME=$(printf '%s\n' "$out" | sed -n 's/^GPU [0-9][0-9]*: \(..*\) (UUID.*/\1/p' | head -n 1)
    [ -n "$NVIDIA_NAME" ] && NVIDIA=1
fi
if [ -z "$NVIDIA" ]; then
    for path in "$R"/dev/nvidia[0-9]*; do
        [ -e "$path" ] || continue
        digits="${path##*/nvidia}"
        case "$digits" in
            *[!0-9]*) ;;
            *) NVIDIA=1 ;;
        esac
    done
fi

if [ -n "$NVIDIA" ] && command -v docker >/dev/null 2>&1; then
    if out=$(docker info --format '{{json .Runtimes}}' 2>/dev/null); then
        if printf '%s\n' "$out" | grep -q '"nvidia"'; then RUNTIME=found; else RUNTIME=missing; fi
    else
        RUNTIME=unknown
    fi
fi

# AMD: the compute device and a render node that really exists.
AMD_NODE=$(render_node 0x1002)
if [ -e "$R/dev/kfd" ] && [ -n "$AMD_NODE" ]; then
    AMD="$AMD_NODE"
    if command -v rocminfo >/dev/null 2>&1; then
        out=$(rocminfo 2>/dev/null) || out=""
        gfx=$(printf '%s\n' "$out" | grep -o 'gfx[A-Za-z0-9_]*' | head -n 1)
        [ -n "$gfx" ] && AMD="$gfx"
    fi
    # Quiet when stat fails or has no -c; then the render group line says how to find the number by hand.
    GID=$(stat -c %g "$R/dev/kfd" 2>/dev/null) || GID=""
    case "$GID" in
        ''|*[!0-9]*) GID="" ;;
    esac
fi

INTEL=$(render_node 0x8086)

for path in "$R"/dev/accel/accel*; do
    [ -e "$path" ] || continue
    node="${path##*/}"
    case "$(vendor accel "$node")" in
        0x8086) NPU="Intel NPU ($node)" ;;
        0x1022) NPU="AMD NPU ($node)" ;;
        *) NPU="NPU ($node)" ;;
    esac
    break
done

FOUND=""
if [ -n "$NVIDIA" ]; then
    if [ -n "$NVIDIA_NAME" ]; then
        printf '%s\n' "Found: NVIDIA GPU ($NVIDIA_NAME)"
    else
        printf '%s\n' "Found: NVIDIA GPU"
    fi
    FOUND=1
fi
case "$RUNTIME" in
    found) printf '%s\n' "Found: Docker's NVIDIA runtime"; FOUND=1 ;;
    missing) printf '%s\n' "Missing: Docker's NVIDIA runtime (the NVIDIA Container Toolkit)"; FOUND=1 ;;
    unknown) printf '%s\n' "Unknown: Docker's NVIDIA runtime (docker info didn't answer)"; FOUND=1 ;;
esac
if [ -n "$AMD" ]; then
    printf '%s\n' "Found: AMD GPU ($AMD)"
    if [ -n "$GID" ]; then
        printf '%s\n' "Found: render group $GID (STEWARD_RENDER_GID)"
    else
        printf '%s\n' "Unknown: render group (STEWARD_RENDER_GID). ls -ln /dev/kfd shows its number, in the fourth column."
    fi
    FOUND=1
fi
if [ -n "$INTEL" ]; then
    printf '%s\n' "Found: Intel GPU ($INTEL)"
    FOUND=1
fi
if [ -n "$NPU" ]; then
    printf '%s\n' "Found: $NPU"
    FOUND=1
fi
[ -n "$FOUND" ] || printf '%s\n' "Found: no GPU or NPU"

if [ "$RUNTIME" = missing ]; then
    printf '%s\n' "Next: install NVIDIA's Container Toolkit, then follow docs/guides/gpu.md, \"NVIDIA\"."
elif [ -n "$NVIDIA" ]; then
    printf '%s\n' "Next: docs/guides/gpu.md, \"NVIDIA\"."
elif [ -n "$AMD" ]; then
    printf '%s\n' "Next: docs/guides/gpu.md, \"AMD\" (not yet tested on real hardware)."
elif [ -n "$INTEL" ] || [ -n "$NPU" ]; then
    printf '%s\n' "Next: nothing yet. Steward finds it but doesn't use it yet, because Ollama's and torch's support for Intel GPUs and for NPUs is still experimental. The gateway runs on the CPU."
else
    printf '%s\n' "Next: nothing to do. The gateway runs on the CPU."
fi
exit 0
