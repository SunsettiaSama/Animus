"""
Build script for vllm-clone custom CUDA attention extension.

Usage
-----
Compile once (output goes to build/):

    cd G:/ReAct/src/infra/llm/custom
    python setup.py build_ext --inplace

Or let cuda_attn.py trigger JIT compilation automatically on first import.

Requirements
------------
  • CUDA Toolkit  ≥ 11.7   (for sm_80 / A100; change -arch for older cards)
  • PyTorch       ≥ 2.0    (for at::cuda::getCurrentCUDAStream)
  • Windows: MSVC 2019+ via "x64 Native Tools Command Prompt"
  • Linux:   gcc ≥ 9
"""

import os
import sys
from pathlib import Path

from setuptools import setup
from torch.utils.cpp_extension import CUDAExtension, BuildExtension

HERE    = Path(__file__).parent
CSRC    = HERE / "csrc" / "attention"
SOURCES = [
    str(CSRC / "flash_attn2.cu"),
    str(CSRC / "pybind.cpp"),
]

# ── compiler flags ────────────────────────────────────────────────────────────

NVCC_FLAGS = [
    "-O3",
    "--use_fast_math",
    # Target A100 (sm_80). For older cards use sm_75 (Turing) or sm_70 (Volta).
    # For H100 add sm_90.
    "-gencode", "arch=compute_80,code=sm_80",
    "-gencode", "arch=compute_75,code=sm_75",   # also compile for Turing
    "-std=c++17",
    # Suppress known harmless warnings from torch headers on MSVC
    "-Xcompiler", "/wd4067" if sys.platform == "win32" else "-Wno-deprecated",
]

CXX_FLAGS_LINUX   = ["-O3", "-std=c++17"]
CXX_FLAGS_WINDOWS = ["/O2", "/std:c++17", "/wd4067", "/wd4624"]

CXX_FLAGS = CXX_FLAGS_WINDOWS if sys.platform == "win32" else CXX_FLAGS_LINUX

# ── extension ─────────────────────────────────────────────────────────────────

ext = CUDAExtension(
    name="vllm_clone_attn",
    sources=SOURCES,
    include_dirs=[str(CSRC)],
    extra_compile_args={
        "cxx":  CXX_FLAGS,
        "nvcc": NVCC_FLAGS,
    },
    # Link against cuBLAS / cuDNN only if needed; pure-CUDA kernel needs none.
)

setup(
    name="vllm_clone_attn",
    version="0.1.0",
    ext_modules=[ext],
    cmdclass={"build_ext": BuildExtension},
)
