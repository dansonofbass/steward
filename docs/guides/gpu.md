# Speed up the gateway with a GPU

A GPU makes redaction and the local model much faster. Steward never installs drivers or toolkits: you install the vendor's own. Steward never publishes a GPU image either: your machine builds one once, from Steward's release source.

This page is for the gateway described in [the gateway guide](gateway.md). Nothing here is needed for it to work; the CPU image is the default.

## Find out what you have

Download the release's detection script, read it, then run it. It only looks: it installs nothing and writes nothing.

```
curl -fsSLO https://raw.githubusercontent.com/steward-money/steward/v0.1.0/deploy/gateway/detect-gpu.sh
less detect-gpu.sh
sh detect-gpu.sh
```

On a machine where the gateway is already installed, `steward-gateway hardware` prints the same. On an NVIDIA machine with Docker's NVIDIA runtime it looks like this:

```
This gateway runs on: cuda
Found: NVIDIA GPU (NVIDIA GeForce RTX 3080 Ti)
Found: Docker's NVIDIA runtime
Next: docs/guides/gpu.md, "NVIDIA".
```

Each `Next:` line points at a section below.

## Licenses

Steward's own code is AGPL. When you build a GPU gateway, you download the vendor's packages yourself, from PyPI and PyTorch's index, under the vendor's own licenses. Steward never redistributes them. Until `.env` says you accept them (`STEWARD_GPU_LICENSE_ACCEPTED`, set in the steps below), Steward won't build or run its GPU gateway.

Ollama's images are separate: Ollama distributes them from its own registry, under [Ollama's license](https://github.com/ollama/ollama/blob/main/LICENSE). `STEWARD_GPU_LICENSE_ACCEPTED` doesn't cover them, and Compose may download a GPU profile's Ollama image before it refuses to build the gateway. The `ollama/ollama` image carries GPU runtime libraries even when it runs on the CPU, as the plain `ollama` service does.

| What | Package | License |
|---|---|---|
| CUDA libraries | `cuda-bindings` | Apache-2.0 |
| CUDA libraries | `cuda-pathfinder` | Apache-2.0 |
| CUDA libraries | `cuda-toolkit` | No license is listed on PyPI. It only pulls in the other CUDA packages in this table, which come under NVIDIA's [CUDA Toolkit EULA](https://docs.nvidia.com/cuda/eula/index.html). |
| CUDA libraries | `nvidia-cublas` | NVIDIA's [CUDA Toolkit EULA](https://docs.nvidia.com/cuda/eula/index.html) |
| CUDA libraries | `nvidia-cuda-cupti` | NVIDIA's [CUDA Toolkit EULA](https://docs.nvidia.com/cuda/eula/index.html) |
| CUDA libraries | `nvidia-cuda-nvrtc` | NVIDIA's [CUDA Toolkit EULA](https://docs.nvidia.com/cuda/eula/index.html) |
| CUDA libraries | `nvidia-cuda-runtime` | NVIDIA's [CUDA Toolkit EULA](https://docs.nvidia.com/cuda/eula/index.html) |
| CUDA libraries | `nvidia-cufft` | NVIDIA's [CUDA Toolkit EULA](https://docs.nvidia.com/cuda/eula/index.html) |
| CUDA libraries | `nvidia-cufile` | NVIDIA's [CUDA Toolkit EULA](https://docs.nvidia.com/cuda/eula/index.html) |
| CUDA libraries | `nvidia-curand` | NVIDIA's [CUDA Toolkit EULA](https://docs.nvidia.com/cuda/eula/index.html) |
| CUDA libraries | `nvidia-cusolver` | NVIDIA's [CUDA Toolkit EULA](https://docs.nvidia.com/cuda/eula/index.html) |
| CUDA libraries | `nvidia-cusparse` | NVIDIA's [CUDA Toolkit EULA](https://docs.nvidia.com/cuda/eula/index.html) |
| CUDA libraries | `nvidia-cusparselt-cu13` | NVIDIA's [CUDA Toolkit EULA](https://docs.nvidia.com/cuda/eula/index.html) |
| CUDA libraries | `nvidia-nvjitlink` | NVIDIA's [CUDA Toolkit EULA](https://docs.nvidia.com/cuda/eula/index.html) |
| CUDA libraries | `nvidia-nvshmem-cu13` | NVIDIA's [CUDA Toolkit EULA](https://docs.nvidia.com/cuda/eula/index.html) |
| CUDA libraries | `nvidia-nvtx` | Apache-2.0 |
| Deep learning kernels | `nvidia-cudnn-cu13` | NVIDIA's [cuDNN license](https://docs.nvidia.com/deeplearning/cudnn/backend/latest/reference/eula.html) |
| Multi-GPU communication | `nvidia-nccl-cu13` | Listed as NVIDIA proprietary in the package; NCCL's own source is BSD-3-Clause |
| Local model server | Ollama's image, from Ollama's own registry | [MIT](https://github.com/ollama/ollama/blob/main/LICENSE), with NVIDIA's CUDA libraries inside under the same CUDA Toolkit EULA |
| AMD | PyTorch for ROCm | BSD-3-Clause, with AMD's ROCm libraries inside, under [AMD's ROCm license terms](https://rocm.docs.amd.com/en/latest/about/license.html) |
| AMD | Ollama's ROCm image, from Ollama's own registry | [MIT](https://github.com/ollama/ollama/blob/main/LICENSE), with AMD's ROCm libraries inside, under the same ROCm license terms |

The NVIDIA Deep Learning Container license doesn't apply: no Steward image is built on an NVIDIA container. Its text is [here](https://developer.download.nvidia.com/licenses/NVIDIA_Deep_Learning_Container_License.pdf) if you want to check.

## The one-time build

The first `docker compose up -d` with a GPU profile builds the GPU gateway on your machine. You can build it ahead:

```
docker compose --profile gateway-nvidia build
docker compose --profile gateway-amd build
```

Run the one for your GPU. Expect 10 to 20 minutes on a first build and several GB of disk. On the test machine, the NVIDIA image came to 6.2 GB, and a rebuild with warm caches took about two minutes.

It downloads:

- Steward's source at this release, from GitHub;
- the Python base image;
- the gateway's Python packages from PyPI, including the vendor's GPU libraries (for AMD, PyTorch's ROCm build from PyTorch's index).

The result is `steward-gateway-cuda:local` (or `steward-gateway-rocm:local`) on your machine only. Steward never publishes it. `docker compose pull` skips it. After an upgrade, `docker compose up -d` rebuilds it from the new release, quickly where nothing changed.

## NVIDIA

1. Install NVIDIA's driver on the host ([NVIDIA's driver page](https://www.nvidia.com/Download/index.aspx)). In WSL2, the Windows driver provides the GPU.
2. Install the NVIDIA Container Toolkit, following [NVIDIA's install guide](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html), then run `sudo nvidia-ctk runtime configure --runtime=docker` and restart Docker. Docker Desktop on Windows has GPU support built in.
3. Read the licenses above, then set `STEWARD_GPU_LICENSE_ACCEPTED=nvidia` in `.env`.
4. Set `COMPOSE_PROFILES=tailscale,gateway-nvidia` (instead of `gateway` and `ollama`), then run `docker compose up -d`. The first time, that includes the build above. The key, the pairing and the models carry over: no re-pair.

From now on, in the [gateway guide](gateway.md)'s `docker compose` commands, use `gateway-nvidia` and `ollama-nvidia` in place of `gateway` and `ollama`. To pull a model, run `docker compose exec ollama-nvidia ollama pull <model>`; the gateway's start line lists the models gateway.toml names.

## AMD

This is not yet tested on real hardware. If it works for you, or doesn't, please open an issue.

1. Install AMD's ROCm driver on the host, following [AMD's install guide](https://rocm.docs.amd.com/projects/install-on-linux/en/latest/).
2. Set `STEWARD_RENDER_GID` in `.env` to the number detection printed. If it couldn't read it, `ls -ln /dev/kfd` shows it in the fourth column.
3. Read the licenses above, then set `STEWARD_GPU_LICENSE_ACCEPTED=amd` in `.env`.
4. Set `COMPOSE_PROFILES=tailscale,gateway-amd`, then run `docker compose up -d`, which builds the ROCm gateway the first time.

From now on, in the [gateway guide](gateway.md)'s `docker compose` commands, use `gateway-amd` and `ollama-amd` in place of `gateway` and `ollama`. To pull a model, run `docker compose exec ollama-amd ollama pull <model>`; the gateway's start line lists the models gateway.toml names.

## Check it worked

In Steward, Settings › Get Steward ready › Ask says "Runs on an NVIDIA GPU." (or the AMD line).

Or run `docker compose exec gateway-nvidia steward-gateway hardware`; its first line is `This gateway runs on: cuda`.

If it still says the CPU, the gateway's start line (`docker compose logs gateway-nvidia`) names what to check.

## Intel GPUs and NPUs

Steward finds them but doesn't use them yet: Ollama's and torch's support there is still experimental, so the gateway runs on the CPU. Detection says so plainly.
