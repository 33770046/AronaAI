# -*- mode: python ; coding: utf-8 -*-
# 本项目对 _pyinstaller_hooks_contrib 自带 stdhooks/hook-torch.py 的覆盖版本
# （沿用原逻辑，原文件版权归 PyInstaller Development Team，
#  GPL-2.0-or-later）。
#
# 为什么要覆盖
# ------------
# 官方 hook 会收集 torch/lib 下的全部文件：Windows 上 torch 2.14.0+cu126
# 合计 3.9 GB。从 _C.pyd 出发做静态 PE 导入表遍历（含 IAT 闭包与延迟加载
# 目录），实际可达的只有约 2.7 GB。够不到的那部分分两类：
#
#   * cuDNN 9 的子库（cudnn_*64_9.dll，约 960 MB）。torch_cuda.dll 硬依赖的
#     那个 0.3 MB cudnn64_9.dll，其导入表里只有 KERNEL32；子库是它按需
#     LoadLibrary() 起来的，也就是第一次调用 cuDNN API 时才加载。
#     App/tts/tts_child.py 里设了 torch.backends.cudnn.enabled = False，
#     ATen 全程走原生 CUDA 卷积，这些调用不会发生。（已核实：gsv_tts 中
#     没有任何 nn.LSTM / ctc_loss / torch.compile / backends.cudnn 的用法。）
#   * 完全无人引用的孤立库（cusolverMg、curand、nvrtc .alt、nvperf_host、
#     cufftw 等），加载闭包里没有任何文件提到它们。
#
# torch_cuda.dll 硬导入的那些（cublas64_12、cublasLt64_12、cudnn64_9、
# cufft64_11、cusolver64_11、cusparse64_12、nvrtc64_120_0、nvjitlink、
# torch_cpu、c10 等）必须保留：它们 delay=0，删掉任何一个都会让
# import torch 在加载器层面失败。在没有重新跑导入表分析 + GPU 冒烟测试
# 之前，不要往 _DROP_DLLS 里加名字。
# 另有一处例外（默认开启）：_STUB_DLLS 把 cusparse/cusolver 换成约 18 KB 的
# PE 桩文件，导出表与原来一致；设 USE_TORCH_STUBS=0 则保留真实 DLL。

import os
import sys

from PyInstaller.utils.hooks import (
    PY_DYLIB_PATTERNS,
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
    is_module_satisfies,
    logger,
)

# 第三阶段瘦身（默认开启）：把剩余最大的两个 CUDA DLL ——
# cusparse64_12（274 MB）+ cusolver64_11（132 MB），合计 406 MB ——
# 换成手写的 PE32+ 桩文件（约 18 KB）。桩导出了 torch_cuda.dll 绑定的
# 全部符号，函数体统一是 `mov eax, 1; ret`，返回错误状态 1。
# 稠密的 GPT-SoVITS 推理从不调用稀疏 / 稠密求解器 API；万一真调到了，
# torch 的 CHECK 宏会抛出一个可捕获的 Python 异常，而不是拿未初始化的
# 输出参数往下算。
# （cufft64_11 没有做桩：参考音频频谱图 -> torch.stft -> cuFFT 这条链是
#  常走的，冒烟测试里会报 `CUFFT_INVALID_PLAN`。）
# 默认开启；构建时设 USE_TORCH_STUBS=0 可改为打包完整 CUDA DLL 集合。
_STUB_DLLS = frozenset(
    ("cusparse64_12.dll", "cusolver64_11.dll")
)
_USE_STUBS = os.environ.get("USE_TORCH_STUBS", "1") != "0"
_STUB_PATHS = {}
if _USE_STUBS:
    _here = os.path.dirname(os.path.abspath(__file__))
    if _here not in sys.path:
        sys.path.insert(0, _here)
    from gen_torch_stubs import ensure_stubs

    _STUB_PATHS, _stub_counts = ensure_stubs(os.path.join(_here, "stubs"))
    logger.info(
        "hook-torch: USE_TORCH_STUBS (default on) -> %s",
        ", ".join(f"{k} ({v} exports)" for k, v in _stub_counts.items()),
    )

# 关于 torch.compile 那一套：这里不过滤 torch._dynamo/_inductor。
# transformers 的 Hubert -> masking_utils 链路在模块级就会急切导入
# torch._dynamo（约 95 个 dynamo 模块 + 17 个 inductor 模块），而整条约
# 5.6MB 的栈在 PYZ 里并不大；在 AronaAI.spec 里排除它会让预热流程崩溃
# （打包后冒烟测试验证过）。Python 侧唯一的排除项是 networkx（在 spec 层）。

# 按需加载的 cuDNN 子库，以及加载器够不到的孤立库（见文件头）。
# 名字统一小写，按 basename 匹配。
_DROP_DLLS = frozenset(
    name.lower()
    for name in (
        # cuDNN 9 的按需子库（约 960 MB）——第一次调用 cuDNN API 时才加载，
        # 而 cudnn.enabled = False 时永远不会走到那一步。
        "cudnn_engines_precompiled64_9.dll",
        "cudnn_engines_runtime_compiled64_9.dll",
        "cudnn_adv64_9.dll",
        "cudnn_ops64_9.dll",
        "cudnn_heuristic64_9.dll",
        "cudnn_cnn64_9.dll",
        # 注意：cudnn_graph64_9.dll 是保留的（2.3 MB，自包含，只导入
        # KERNEL32）。torch 做 SDPA 探测时，cudnn64_9.dll 这个 shim 会经由它
        # 去解析 cudnnGetVersion；缺了它，shim 会直接让进程原生崩溃
        # （0xC0000409），而不是抛出可捕获的异常。有它在，gsv 的
        # CUDNN_ATTENTION 尝试会干净地失败并回退到 EFFICIENT_ATTENTION
        # （见 tests/dev_tts_smoke.py 验证）。
        # 其余孤立项：在可达闭包的任何导入表 / 延迟加载表里都找不到。
        "cusolvermg64_11.dll",
        "curand64_10.dll",
        "nvrtc64_120_0.alt.dll",
        "nvperf_host.dll",
        "cufftw64_11.dll",
        "nvtoolsext64_1.dll",
        "libiompstubs5md.dll",
        "caffe2_nvrtc.dll",
        "torch_global_deps.dll",
        "fmt-c.dll",
    )
)

if is_module_satisfies("PyInstaller >= 6.0"):
    module_collection_mode = "pyz+py"
    warn_on_missing_hiddenimports = False

    datas = collect_data_files(
        "torch",
        excludes=[
            "**/*.h",
            "**/*.hpp",
            "**/*.cuh",
            "**/*.lib",
            "**/*.cpp",
            "**/*.pyi",
            "**/*.cmake",
            # DLL 只能通过下面那份过滤过的 `binaries` 进来：
            # collect_data_files() 也会把 torch/lib/*.dll 当数据返回，而
            # Analysis 会把名字看起来像二进制文件的数据项重新归为 BINARY，
            # 那样黑名单就被悄悄绕过了。
            "**/*.dll",
            "**/*.dylib",
            "**/*.so",
            "**/*.so.*",
        ],
    )
    hiddenimports = collect_submodules("torch")

    binaries = []
    dropped = []
    for src, dest in collect_dynamic_libs(
        "torch", search_patterns=PY_DYLIB_PATTERNS + ["*.so.*"]
    ):
        base = os.path.basename(src).lower()
        if base in _DROP_DLLS:
            dropped.append((base, os.path.getsize(src)))
            continue
        if base in _STUB_PATHS:
            binaries.append((_STUB_PATHS[base], dest))
            continue
        binaries.append((src, dest))
    if dropped:
        mb = sum(size for _, size in dropped) / 1048576
        logger.info(
            "hook-torch: dropped %d lazy/orphan DLL(s), %.0f MB: %s",
            len(dropped),
            mb,
            ", ".join(sorted(name for name, _ in dropped)),
        )

    # MKL：PyPI 的 cu126 wheel 并不依赖它，只有当 torch 发行版（conda 那种）
    # 自己声明了依赖时才收集。逻辑与官方 hook 保持一致。
    try:
        import importlib.metadata as _ilmd

        import packaging.requirements as _reqmod

        _reqs = _ilmd.requires("torch") or []
        _needs_mkl = any(
            _reqmod.Requirement(r).name == "mkl" for r in _reqs
        )
        if _needs_mkl:
            _libbin = os.path.join(
                os.path.dirname(os.path.dirname(os.__file__)),
                "Library",
                "bin",
            )
            if os.path.isdir(_libbin):
                mkl_binaries = [
                    (
                        os.path.join(_libbin, f),
                        ".",
                    )
                    for f in os.listdir(_libbin)
                    if f.lower().endswith(".dll")
                ]
                logger.info(
                    "hook-torch: collecting %d MKL/dependency DLLs",
                    len(mkl_binaries),
                )
                binaries += mkl_binaries
    except Exception as exc:  # pragma: no cover - build-time only
        logger.warning("hook-torch: MKL detection failed: %s", exc)
else:  # pragma: no cover - PyInstaller 5.x not supported by this project
    raise SystemExit("hook-torch override requires PyInstaller >= 6")
