#!/bin/bash
# =============================================================================
# docker/vllm/entrypoint.sh
#
# 将 Docker 环境变量转换为 `vllm serve` CLI 参数，然后 exec 服务进程。
# 所有变量均有默认值，覆盖时只需在 docker-compose.yml 或 .env 文件中设置。
# =============================================================================
set -euo pipefail

# ── 必填 ──────────────────────────────────────────────────────────────────────
MODEL="${VLLM_MODEL:?环境变量 VLLM_MODEL 未设置，请在 .env 中指定模型名称}"

# ── 服务器 ────────────────────────────────────────────────────────────────────
HOST="${VLLM_HOST:-0.0.0.0}"
PORT="${VLLM_PORT:-8000}"

# ── 并行 & 显存 ────────────────────────────────────────────────────────────────
TENSOR_PARALLEL="${VLLM_TENSOR_PARALLEL:-1}"
PIPELINE_PARALLEL="${VLLM_PIPELINE_PARALLEL:-1}"
GPU_MEM_UTIL="${VLLM_GPU_MEM_UTIL:-0.90}"

# ── 精度 & 量化 ────────────────────────────────────────────────────────────────
DTYPE="${VLLM_DTYPE:-auto}"
QUANTIZATION="${VLLM_QUANTIZATION:-}"       # 空 = 不启用量化

# ── 上下文长度 ────────────────────────────────────────────────────────────────
MAX_MODEL_LEN="${VLLM_MAX_MODEL_LEN:-}"     # 空 = 使用模型默认值

# ── LoRA ──────────────────────────────────────────────────────────────────────
ENABLE_LORA="${VLLM_ENABLE_LORA:-false}"
MAX_LORA_RANK="${VLLM_MAX_LORA_RANK:-16}"

# ── Eager mode ────────────────────────────────────────────────────────────────
ENFORCE_EAGER="${VLLM_ENFORCE_EAGER:-false}"

# ── 组装参数数组 ──────────────────────────────────────────────────────────────
ARGS=(
    "--model"                   "$MODEL"
    "--host"                    "$HOST"
    "--port"                    "$PORT"
    "--tensor-parallel-size"    "$TENSOR_PARALLEL"
    "--pipeline-parallel-size"  "$PIPELINE_PARALLEL"
    "--gpu-memory-utilization"  "$GPU_MEM_UTIL"
    "--dtype"                   "$DTYPE"
)

[[ -n "$MAX_MODEL_LEN"  ]] && ARGS+=("--max-model-len"  "$MAX_MODEL_LEN")
[[ -n "$QUANTIZATION"   ]] && ARGS+=("--quantization"   "$QUANTIZATION")
[[ "$ENABLE_LORA"  == "true" ]] && ARGS+=("--enable-lora" "--max-lora-rank" "$MAX_LORA_RANK")
[[ "$ENFORCE_EAGER" == "true" ]] && ARGS+=("--enforce-eager")

echo "=== vLLM 服务启动 ==="
echo "  模型:  $MODEL"
echo "  地址:  $HOST:$PORT"
echo "  TP:    $TENSOR_PARALLEL  PP: $PIPELINE_PARALLEL"
echo "  显存:  $GPU_MEM_UTIL  dtype: $DTYPE"
[[ -n "$QUANTIZATION" ]] && echo "  量化:  $QUANTIZATION"
echo ""

exec python3.11 -m vllm.entrypoints.openai.api_server "${ARGS[@]}"
