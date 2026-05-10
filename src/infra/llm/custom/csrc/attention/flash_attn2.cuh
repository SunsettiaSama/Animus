#pragma once

#include <cuda.h>
#include <cuda_fp16.h>

namespace vllm_clone {
namespace attn {

static constexpr int WARP_SIZE = 32;

// ─────────────────────────────────────────────────────────────────────────────
// Warp-level primitives
//
// __shfl_xor_sync is the key FA2 primitive unavailable in Triton.
// After the reduction loop every lane in the warp holds the same value —
// this broadcasts the dot-product scalar without touching shared memory.
// ─────────────────────────────────────────────────────────────────────────────

__device__ __forceinline__ float warp_reduce_sum(float v) {
    #pragma unroll
    for (int mask = 16; mask > 0; mask >>= 1)
        v += __shfl_xor_sync(0xffffffff, v, mask);
    return v;
}

__device__ __forceinline__ float warp_reduce_max(float v) {
    #pragma unroll
    for (int mask = 16; mask > 0; mask >>= 1)
        v = fmaxf(v, __shfl_xor_sync(0xffffffff, v, mask));
    return v;
}

static __device__ __forceinline__ int cdiv_dev(int a, int b) {
    return (a + b - 1) / b;
}


// ─────────────────────────────────────────────────────────────────────────────
// Flash Attention 2 — contiguous KV  [B, H, S, D]
//
// Grid:  (ceil(Sq/BLOCK_M),  H_kv,  B)
// Block: (BLOCK_M * WARP_SIZE,)      ← one warp per Q-row
//
// GROUP_SIZE = H_q / H_kv.
//   MHA  → GROUP_SIZE=1, blockIdx.y iterates H_q (= H_kv) heads.
//   GQA  → GROUP_SIZE>1, blockIdx.y iterates H_kv heads; each block
//           processes GROUP_SIZE Q heads sharing one KV head.
//   MQA  → GROUP_SIZE=H_q, one KV head serves all Q heads.
//
// K/V tile is loaded into SMEM once and reused by all GROUP_SIZE Q heads,
// reducing K/V HBM reads by exactly GROUP_SIZE× compared to per-head dispatch.
// ─────────────────────────────────────────────────────────────────────────────
template <int HEAD_DIM, int BLOCK_M, int BLOCK_N, int GROUP_SIZE>
__global__ void fa2_fwd_kernel(
    const __half* __restrict__ Q,      // [B, H_q,  Sq, D]
    const __half* __restrict__ K,      // [B, H_kv, Sk, D]
    const __half* __restrict__ V,      // [B, H_kv, Sk, D]
    __half*       __restrict__ O,      // [B, H_q,  Sq, D]
    int Sq, int Sk,
    int sqB, int sqH, int sqS,         // Q  strides: batch / head / seq
    int skB, int skH, int skS,         // K  strides  (H_kv dimension)
    int svB, int svH, int svS,         // V  strides
    int soB, int soH, int soS,         // O  strides  (H_q  dimension)
    float scale,
    bool  causal
);


// ─────────────────────────────────────────────────────────────────────────────
// Paged Attention 2 — paged KV cache
//
// K_cache / V_cache layout: [num_phys_blocks, H_kv, PAGE_SIZE, D]
// block_table:               [B, max_pages]   int32
// context_lens:              [B]              int32
//
// Grid:  (ceil(Sq/BLOCK_M),  H_kv,  B)
// Same GROUP_SIZE semantics as fa2_fwd_kernel.
// K/V SMEM load uses block_table indirection instead of contiguous stride;
// the online-softmax body (and GROUP_SIZE loop) is untouched.
// ─────────────────────────────────────────────────────────────────────────────
template <int HEAD_DIM, int BLOCK_M, int PAGE_SIZE, int GROUP_SIZE>
__global__ void paged_attn2_fwd_kernel(
    const __half* __restrict__ Q,          // [B, H_q,  Sq, D]
    const __half* __restrict__ K_cache,    // [num_blocks, H_kv, PAGE_SIZE, D]
    const __half* __restrict__ V_cache,
    __half*       __restrict__ O,          // [B, H_q,  Sq, D]
    const int*    __restrict__ block_table,  // [B, max_pages]
    const int*    __restrict__ context_lens, // [B]
    int Sq, int max_pages,
    int sqB, int sqH, int sqS,
    int skB, int skH, int skP,   // K_cache: block / head / page-slot strides
    int svB, int svH, int svP,
    int soB, int soH, int soS,
    int stBB, int stBN,          // block_table: batch / page strides
    float scale,
    int   q_start_pos            // absolute position of Q[0] in the sequence
                                 // decode: q_start_pos = context_len - 1
                                 // prefill/verify: q_start_pos = offset before Q
                                 // -1 disables causal masking (full attention)
);

} // namespace attn
} // namespace vllm_clone
