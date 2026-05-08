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
// Grid:  (ceil(Sq/BLOCK_M),  H,  B)
// Block: (BLOCK_M * WARP_SIZE,)      ← one warp per Q-row
//
// Each warp w processes Q-row (q_tile*BLOCK_M + w):
//   • q_frag[VEC] lives in registers throughout — no re-load
//   • K/V tiles are cooperatively staged into SMEM by all block threads
//   • FA2 causal skip: if kv_start > q_row, break (entire tile = −∞)
//   • warp_reduce_sum collapses the VEC partial products into one score scalar
// ─────────────────────────────────────────────────────────────────────────────
template <int HEAD_DIM, int BLOCK_M, int BLOCK_N>
__global__ void fa2_fwd_kernel(
    const __half* __restrict__ Q,      // [B, H, Sq, D]
    const __half* __restrict__ K,      // [B, H, Sk, D]
    const __half* __restrict__ V,      // [B, H, Sk, D]
    __half*       __restrict__ O,      // [B, H, Sq, D]
    int Sq, int Sk,
    // strides (in elements, not bytes)
    int sqB, int sqH, int sqS,         // Q  batch / head / seq
    int skB, int skH, int skS,         // K
    int svB, int svH, int svS,         // V
    int soB, int soH, int soS,         // O
    float scale,
    bool  causal
);


// ─────────────────────────────────────────────────────────────────────────────
// Paged Attention 2 — paged KV cache
//
// K_cache / V_cache layout: [num_phys_blocks, H, PAGE_SIZE, D]
// block_table:               [B, max_pages]   int32
// context_lens:              [B]              int32
//
// Structurally identical to fa2_fwd_kernel.
// The only change: K/V SMEM load reads through block_table indirection
// instead of contiguous stride — the online-softmax body is untouched.
// ─────────────────────────────────────────────────────────────────────────────
template <int HEAD_DIM, int BLOCK_M, int PAGE_SIZE>
__global__ void paged_attn2_fwd_kernel(
    const __half* __restrict__ Q,
    const __half* __restrict__ K_cache,
    const __half* __restrict__ V_cache,
    __half*       __restrict__ O,
    const int*    __restrict__ block_table,    // [B, max_pages]
    const int*    __restrict__ context_lens,   // [B]
    int Sq, int max_pages,
    int sqB, int sqH, int sqS,
    int skB, int skH, int skP,   // K_cache: block / head / page-slot strides
    int svB, int svH, int svP,
    int soB, int soH, int soS,
    int stBB, int stBN,          // block_table: batch / page strides
    float scale
);

} // namespace attn
} // namespace vllm_clone
