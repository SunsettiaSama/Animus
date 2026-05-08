#include "flash_attn2.cuh"

namespace vllm_clone {
namespace attn {

// ─────────────────────────────────────────────────────────────────────────────
// Flash Attention 2 forward — contiguous KV
//
// Thread layout (one warp = one Q-row):
//
//   threadIdx.x   warp_id = threadIdx.x / 32
//   ─────────     lane    = threadIdx.x % 32
//
//   Each lane owns VEC = HEAD_DIM/32 consecutive D-elements of its Q-row.
//   The dot product  q[row] · k[j]  is computed as:
//
//     partial = Σ_{v=0}^{VEC-1}  q_frag[v] * k_smem[j][lane*VEC + v]
//     score   = warp_reduce_sum(partial) * scale      ← __shfl_xor_sync tree
//
//   After warp_reduce_sum all 32 lanes carry the same scalar `score`,
//   so m_i / l_i / rescale are broadcast-consistent across the warp.
//   Only acc[v] differs per lane (it tracks its VEC output elements).
//
// FA2 causal skip:
//   if (causal && kv_start > q_row) break;
//   This exits the KV-tile loop early — no score computation, no SMEM load.
//   Proof of safety: all scores would be −∞ → exp(−∞)=0 → zero contribution
//   to l_i and acc → online-softmax state unchanged → safe to skip.
// ─────────────────────────────────────────────────────────────────────────────

template <int HEAD_DIM, int BLOCK_M, int BLOCK_N>
__global__ void fa2_fwd_kernel(
    const __half* __restrict__ Q,
    const __half* __restrict__ K,
    const __half* __restrict__ V,
    __half*       __restrict__ O,
    int Sq, int Sk,
    int sqB, int sqH, int sqS,
    int skB, int skH, int skS,
    int svB, int svH, int svS,
    int soB, int soH, int soS,
    float scale, bool causal
) {
    constexpr int VEC = HEAD_DIM / WARP_SIZE;   // D-elements owned by each lane

    const int q_tile   = blockIdx.x;
    const int head_id  = blockIdx.y;
    const int batch_id = blockIdx.z;
    const int warp_id  = threadIdx.x / WARP_SIZE;   // = Q-row within tile
    const int lane     = threadIdx.x % WARP_SIZE;

    const int q_row = q_tile * BLOCK_M + warp_id;
    if (q_row >= Sq) return;

    // ── Load Q row into registers (held for entire KV loop) ──────────────────
    float q_frag[VEC];
    const __half* q_ptr = Q + batch_id * sqB + head_id * sqH + q_row * sqS;
    #pragma unroll
    for (int v = 0; v < VEC; ++v)
        q_frag[v] = __half2float(q_ptr[lane * VEC + v]);

    // ── Online-softmax running state ──────────────────────────────────────────
    float m_i = -1e20f;   // running row-max
    float l_i =  0.0f;    // running exp-sum
    float acc[VEC];        // running weighted-V accumulator
    #pragma unroll
    for (int v = 0; v < VEC; ++v) acc[v] = 0.f;

    // ── Shared memory — holds one K/V tile at a time ──────────────────────────
    // Size: 2 × BLOCK_N × HEAD_DIM × 4 bytes = 2 × 16 × 64 × 4 = 8 KB  (fine)
    __shared__ float k_smem[BLOCK_N][HEAD_DIM];
    __shared__ float v_smem[BLOCK_N][HEAD_DIM];

    // ── KV-tile loop ──────────────────────────────────────────────────────────
    for (int kv_start = 0; kv_start < Sk; kv_start += BLOCK_N) {

        // FA2 causal skip — entire tile is beyond q_row's horizon
        if (causal && kv_start > q_row) break;

        const int tile_len = min(BLOCK_N, Sk - kv_start);

        // ── Cooperative SMEM load ────────────────────────────────────────────
        // All BLOCK_M*32 threads stride through the BLOCK_N*HEAD_DIM elements.
        // With 128 threads and 1024 elements (BLOCK_N=16, HEAD_DIM=64)
        // each thread loads exactly 8 elements — no tail handling needed.
        const __half* k_base = K + batch_id * skB + head_id * skH;
        const __half* v_base = V + batch_id * svB + head_id * svH;

        for (int idx = threadIdx.x; idx < tile_len * HEAD_DIM; idx += blockDim.x) {
            const int r = idx / HEAD_DIM;
            const int c = idx % HEAD_DIM;
            k_smem[r][c] = __half2float(k_base[(kv_start + r) * skS + c]);
            v_smem[r][c] = __half2float(v_base[(kv_start + r) * svS + c]);
        }
        __syncthreads();

        // ── Per-token inner loop ─────────────────────────────────────────────
        for (int j = 0; j < tile_len; ++j) {
            // Causal mask at token granularity (boundary tile only)
            if (causal && (kv_start + j) > q_row) break;

            // Step 1: partial dot product — each lane computes VEC multiplies
            float partial = 0.f;
            #pragma unroll
            for (int v = 0; v < VEC; ++v)
                partial += q_frag[v] * k_smem[j][lane * VEC + v];

            // Step 2: warp reduction via __shfl_xor_sync tree
            //   After this call every lane holds the full dot product.
            float score = warp_reduce_sum(partial) * scale;

            // Step 3: online-softmax update (Dao 2022 §3.1)
            //   m_i, l_i, rescale are identical across all lanes (same score).
            float m_new   = fmaxf(m_i, score);
            float exp_s   = expf(score - m_new);
            float rescale = expf(m_i   - m_new);
            l_i = l_i * rescale + exp_s;
            m_i = m_new;

            // Step 4: weighted-V accumulation — lane-local, no communication
            #pragma unroll
            for (int v = 0; v < VEC; ++v)
                acc[v] = acc[v] * rescale + exp_s * v_smem[j][lane * VEC + v];
        }

        __syncthreads();   // guard before next tile overwrites k/v_smem
    }

    // ── Write output ──────────────────────────────────────────────────────────
    __half* o_ptr = O + batch_id * soB + head_id * soH + q_row * soS;
    #pragma unroll
    for (int v = 0; v < VEC; ++v)
        o_ptr[lane * VEC + v] = __float2half(acc[v] / l_i);
}


// ─────────────────────────────────────────────────────────────────────────────
// Paged Attention 2 forward — paged KV cache
//
// Identical to fa2_fwd_kernel in all respects EXCEPT the SMEM load:
//
//   Contiguous:   k_base[(kv_start + r) * stride + c]
//   Paged:        K_cache[block_table[b, page_idx], head, slot, c]
//
// The online-softmax body (steps 1-4) is byte-for-byte the same.
// This is the central claim of the paged-attention paper: paging only
// changes the addressing mode, not the computation.
// ─────────────────────────────────────────────────────────────────────────────

template <int HEAD_DIM, int BLOCK_M, int PAGE_SIZE>
__global__ void paged_attn2_fwd_kernel(
    const __half* __restrict__ Q,
    const __half* __restrict__ K_cache,
    const __half* __restrict__ V_cache,
    __half*       __restrict__ O,
    const int*    __restrict__ block_table,
    const int*    __restrict__ context_lens,
    int Sq, int max_pages,
    int sqB, int sqH, int sqS,
    int skB, int skH, int skP,
    int svB, int svH, int svP,
    int soB, int soH, int soS,
    int stBB, int stBN,
    float scale
) {
    constexpr int VEC = HEAD_DIM / WARP_SIZE;

    const int q_tile   = blockIdx.x;
    const int head_id  = blockIdx.y;
    const int batch_id = blockIdx.z;
    const int warp_id  = threadIdx.x / WARP_SIZE;
    const int lane     = threadIdx.x % WARP_SIZE;

    const int q_row = q_tile * BLOCK_M + warp_id;
    if (q_row >= Sq) return;

    // ── Load Q ────────────────────────────────────────────────────────────────
    float q_frag[VEC];
    const __half* q_ptr = Q + batch_id * sqB + head_id * sqH + q_row * sqS;
    #pragma unroll
    for (int v = 0; v < VEC; ++v)
        q_frag[v] = __half2float(q_ptr[lane * VEC + v]);

    const int ctx_len = context_lens[batch_id];

    float m_i = -1e20f, l_i = 0.f;
    float acc[VEC];
    #pragma unroll
    for (int v = 0; v < VEC; ++v) acc[v] = 0.f;

    __shared__ float k_smem[PAGE_SIZE][HEAD_DIM];
    __shared__ float v_smem[PAGE_SIZE][HEAD_DIM];

    // ── Page loop ─────────────────────────────────────────────────────────────
    for (int page_idx = 0; page_idx < max_pages; ++page_idx) {
        const int kv_start = page_idx * PAGE_SIZE;
        if (kv_start >= ctx_len) break;

        // block_table lookup: logical page → physical block id
        const int phys     = block_table[batch_id * stBB + page_idx * stBN];
        const int tile_len = min(PAGE_SIZE, ctx_len - kv_start);

        // ── Cooperative SMEM load from physical block ────────────────────────
        const __half* k_page = K_cache + phys * skB + head_id * skH;
        const __half* v_page = V_cache + phys * svB + head_id * svH;

        for (int idx = threadIdx.x; idx < tile_len * HEAD_DIM; idx += blockDim.x) {
            const int slot = idx / HEAD_DIM;
            const int d    = idx % HEAD_DIM;
            k_smem[slot][d] = __half2float(k_page[slot * skP + d]);
            v_smem[slot][d] = __half2float(v_page[slot * svP + d]);
        }
        __syncthreads();

        // ── Per-token inner loop — byte-for-byte identical to fa2_fwd ─────────
        for (int j = 0; j < tile_len; ++j) {
            float partial = 0.f;
            #pragma unroll
            for (int v = 0; v < VEC; ++v)
                partial += q_frag[v] * k_smem[j][lane * VEC + v];

            float score   = warp_reduce_sum(partial) * scale;
            float m_new   = fmaxf(m_i, score);
            float exp_s   = expf(score - m_new);
            float rescale = expf(m_i   - m_new);
            l_i = l_i * rescale + exp_s;
            m_i = m_new;

            #pragma unroll
            for (int v = 0; v < VEC; ++v)
                acc[v] = acc[v] * rescale + exp_s * v_smem[j][lane * VEC + v];
        }
        __syncthreads();
    }

    // ── Write output ──────────────────────────────────────────────────────────
    __half* o_ptr = O + batch_id * soB + head_id * soH + q_row * soS;
    #pragma unroll
    for (int v = 0; v < VEC; ++v)
        o_ptr[lane * VEC + v] = __float2half(acc[v] / l_i);
}


// ─────────────────────────────────────────────────────────────────────────────
// Explicit instantiations
//
// BLOCK_M=4   → 4 warps per block = 128 threads (good occupancy on A100/H100)
// BLOCK_N=16  → one PAGE_SIZE worth of KV per tile
// HEAD_DIM    → 64 (Qwen-0.5B) or 128 (LLaMA-7B / most production models)
// ─────────────────────────────────────────────────────────────────────────────

#define FA2_INST(HD, BM, BN) \
    template __global__ void fa2_fwd_kernel<HD, BM, BN>( \
        const __half*, const __half*, const __half*, __half*, \
        int, int, int, int, int, int, int, int, int, int, int, int, int, int, int, \
        float, bool)

#define PA2_INST(HD, BM, PS) \
    template __global__ void paged_attn2_fwd_kernel<HD, BM, PS>( \
        const __half*, const __half*, const __half*, __half*, \
        const int*, const int*, \
        int, int, int, int, int, int, int, int, int, int, int, int, int, int, int, \
        float)

FA2_INST(64,  4, 16);
FA2_INST(64,  4, 32);
FA2_INST(128, 4, 16);
FA2_INST(128, 4, 32);

PA2_INST(64,  4, 16);
PA2_INST(128, 4, 16);

} // namespace attn
} // namespace vllm_clone
