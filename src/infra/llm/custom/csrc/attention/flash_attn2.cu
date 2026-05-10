#include "flash_attn2.cuh"

namespace vllm_clone {
namespace attn {

// ─────────────────────────────────────────────────────────────────────────────
// Flash Attention 2 forward — contiguous KV, GQA-aware
//
// Thread layout (one warp = one Q-row):
//
//   threadIdx.x   warp_id = threadIdx.x / 32
//   ─────────     lane    = threadIdx.x % 32
//
//   Each lane owns VEC = HEAD_DIM/32 consecutive D-elements of its Q-row.
//
// GROUP_SIZE optimisation:
//   blockIdx.y = kv_head_id  (0 .. H_kv-1)
//   For group g in [0, GROUP_SIZE):
//     q_head = kv_head_id * GROUP_SIZE + g
//   K/V SMEM tile is loaded ONCE and reused by all GROUP_SIZE Q heads,
//   cutting K/V HBM reads by GROUP_SIZE× vs. separate per-head dispatch.
//
//   GROUP_SIZE=1 → identical behaviour to the original MHA kernel.
//
// FA2 causal skip:
//   if (causal && kv_start > q_row) break
//   All scores would be −∞, contributing nothing to online-softmax state.
// ─────────────────────────────────────────────────────────────────────────────

template <int HEAD_DIM, int BLOCK_M, int BLOCK_N, int GROUP_SIZE>
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
    constexpr int VEC = HEAD_DIM / WARP_SIZE;

    const int q_tile   = blockIdx.x;
    const int kv_head  = blockIdx.y;   // KV head index (0 .. H_kv-1)
    const int batch_id = blockIdx.z;
    const int warp_id  = threadIdx.x / WARP_SIZE;
    const int lane     = threadIdx.x % WARP_SIZE;

    const int q_row = q_tile * BLOCK_M + warp_id;
    if (q_row >= Sq) return;

    // ── Load GROUP_SIZE Q rows into registers (one per Q head in this group) ──
    float q_frag[GROUP_SIZE][VEC];
    #pragma unroll
    for (int g = 0; g < GROUP_SIZE; ++g) {
        const int q_head = kv_head * GROUP_SIZE + g;
        const __half* q_ptr = Q + batch_id * sqB + q_head * sqH + q_row * sqS;
        #pragma unroll
        for (int v = 0; v < VEC; ++v)
            q_frag[g][v] = __half2float(q_ptr[lane * VEC + v]);
    }

    // ── GROUP_SIZE independent online-softmax states ──────────────────────────
    float m_i[GROUP_SIZE], l_i[GROUP_SIZE];
    float acc[GROUP_SIZE][VEC];
    #pragma unroll
    for (int g = 0; g < GROUP_SIZE; ++g) {
        m_i[g] = -1e20f;
        l_i[g] =  0.0f;
        #pragma unroll
        for (int v = 0; v < VEC; ++v) acc[g][v] = 0.f;
    }

    // ── Shared memory — one K/V tile, amortised over GROUP_SIZE Q heads ───────
    __shared__ float k_smem[BLOCK_N][HEAD_DIM];
    __shared__ float v_smem[BLOCK_N][HEAD_DIM];

    // ── KV-tile loop ──────────────────────────────────────────────────────────
    for (int kv_start = 0; kv_start < Sk; kv_start += BLOCK_N) {

        if (causal && kv_start > q_row) break;

        const int tile_len = min(BLOCK_N, Sk - kv_start);

        // Cooperative SMEM load — uses kv_head (shared across all Q heads)
        const __half* k_base = K + batch_id * skB + kv_head * skH;
        const __half* v_base = V + batch_id * svB + kv_head * svH;

        for (int idx = threadIdx.x; idx < tile_len * HEAD_DIM; idx += blockDim.x) {
            const int r = idx / HEAD_DIM;
            const int c = idx % HEAD_DIM;
            k_smem[r][c] = __half2float(k_base[(kv_start + r) * skS + c]);
            v_smem[r][c] = __half2float(v_base[(kv_start + r) * svS + c]);
        }
        __syncthreads();

        // ── Per-token inner loop — GROUP_SIZE Q heads against same k/v_smem ───
        for (int j = 0; j < tile_len; ++j) {
            if (causal && (kv_start + j) > q_row) break;

            #pragma unroll
            for (int g = 0; g < GROUP_SIZE; ++g) {
                float partial = 0.f;
                #pragma unroll
                for (int v = 0; v < VEC; ++v)
                    partial += q_frag[g][v] * k_smem[j][lane * VEC + v];

                float score   = warp_reduce_sum(partial) * scale;
                float m_new   = fmaxf(m_i[g], score);
                float exp_s   = expf(score  - m_new);
                float rescale = expf(m_i[g] - m_new);
                l_i[g]        = l_i[g] * rescale + exp_s;
                m_i[g]        = m_new;

                #pragma unroll
                for (int v = 0; v < VEC; ++v)
                    acc[g][v] = acc[g][v] * rescale + exp_s * v_smem[j][lane * VEC + v];
            }
        }

        __syncthreads();
    }

    // ── Write GROUP_SIZE outputs to their respective Q-head slots ─────────────
    #pragma unroll
    for (int g = 0; g < GROUP_SIZE; ++g) {
        const int q_head = kv_head * GROUP_SIZE + g;
        __half* o_ptr = O + batch_id * soB + q_head * soH + q_row * soS;
        #pragma unroll
        for (int v = 0; v < VEC; ++v)
            o_ptr[lane * VEC + v] = __float2half(acc[g][v] / l_i[g]);
    }
}


// ─────────────────────────────────────────────────────────────────────────────
// Paged Attention 2 forward — paged KV cache, GQA-aware
//
// Identical to fa2_fwd_kernel in structure.
// The only change vs. fa2_fwd: K/V SMEM load reads through block_table
// indirection instead of contiguous stride.  The GROUP_SIZE loop and
// online-softmax body are byte-for-byte the same.
// ─────────────────────────────────────────────────────────────────────────────

template <int HEAD_DIM, int BLOCK_M, int PAGE_SIZE, int GROUP_SIZE>
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
    float scale,
    int   q_start_pos
) {
    constexpr int VEC = HEAD_DIM / WARP_SIZE;

    const int q_tile   = blockIdx.x;
    const int kv_head  = blockIdx.y;
    const int batch_id = blockIdx.z;
    const int warp_id  = threadIdx.x / WARP_SIZE;
    const int lane     = threadIdx.x % WARP_SIZE;

    const int q_row = q_tile * BLOCK_M + warp_id;
    if (q_row >= Sq) return;

    // ── Load GROUP_SIZE Q rows ────────────────────────────────────────────────
    float q_frag[GROUP_SIZE][VEC];
    #pragma unroll
    for (int g = 0; g < GROUP_SIZE; ++g) {
        const int q_head = kv_head * GROUP_SIZE + g;
        const __half* q_ptr = Q + batch_id * sqB + q_head * sqH + q_row * sqS;
        #pragma unroll
        for (int v = 0; v < VEC; ++v)
            q_frag[g][v] = __half2float(q_ptr[lane * VEC + v]);
    }

    const int ctx_len = context_lens[batch_id];

    float m_i[GROUP_SIZE], l_i[GROUP_SIZE];
    float acc[GROUP_SIZE][VEC];
    #pragma unroll
    for (int g = 0; g < GROUP_SIZE; ++g) {
        m_i[g] = -1e20f;
        l_i[g] =  0.0f;
        #pragma unroll
        for (int v = 0; v < VEC; ++v) acc[g][v] = 0.f;
    }

    __shared__ float k_smem[PAGE_SIZE][HEAD_DIM];
    __shared__ float v_smem[PAGE_SIZE][HEAD_DIM];

    // ── Page loop — load K/V once per page, apply to all GROUP_SIZE Q heads ───
    for (int page_idx = 0; page_idx < max_pages; ++page_idx) {
        const int kv_start = page_idx * PAGE_SIZE;
        if (kv_start >= ctx_len) break;

        const int phys     = block_table[batch_id * stBB + page_idx * stBN];
        const int tile_len = min(PAGE_SIZE, ctx_len - kv_start);

        // Load from physical block using kv_head (shared by all Q heads)
        const __half* k_page = K_cache + phys * skB + kv_head * skH;
        const __half* v_page = V_cache + phys * svB + kv_head * svH;

        for (int idx = threadIdx.x; idx < tile_len * HEAD_DIM; idx += blockDim.x) {
            const int slot = idx / HEAD_DIM;
            const int d    = idx % HEAD_DIM;
            k_smem[slot][d] = __half2float(k_page[slot * skP + d]);
            v_smem[slot][d] = __half2float(v_page[slot * svP + d]);
        }
        __syncthreads();

        // ── Per-token inner loop — byte-for-byte identical to fa2_fwd ─────────
        for (int j = 0; j < tile_len; ++j) {
            const int abs_kv_pos = kv_start + j;

            #pragma unroll
            for (int g = 0; g < GROUP_SIZE; ++g) {
                // Causal mask: KV position must not exceed this Q-row's position.
                // q_start_pos == -1 disables causal masking (full bidirectional).
                const int abs_q_pos = q_start_pos + q_row;
                if (q_start_pos >= 0 && abs_kv_pos > abs_q_pos) break;

                float partial = 0.f;
                #pragma unroll
                for (int v = 0; v < VEC; ++v)
                    partial += q_frag[g][v] * k_smem[j][lane * VEC + v];

                float score   = warp_reduce_sum(partial) * scale;
                float m_new   = fmaxf(m_i[g], score);
                float exp_s   = expf(score  - m_new);
                float rescale = expf(m_i[g] - m_new);
                l_i[g]        = l_i[g] * rescale + exp_s;
                m_i[g]        = m_new;

                #pragma unroll
                for (int v = 0; v < VEC; ++v)
                    acc[g][v] = acc[g][v] * rescale + exp_s * v_smem[j][lane * VEC + v];
            }
        }
        __syncthreads();
    }

    // ── Write GROUP_SIZE outputs ──────────────────────────────────────────────
    #pragma unroll
    for (int g = 0; g < GROUP_SIZE; ++g) {
        const int q_head = kv_head * GROUP_SIZE + g;
        __half* o_ptr = O + batch_id * soB + q_head * soH + q_row * soS;
        #pragma unroll
        for (int v = 0; v < VEC; ++v)
            o_ptr[lane * VEC + v] = __float2half(acc[g][v] / l_i[g]);
    }
}


// ─────────────────────────────────────────────────────────────────────────────
// Explicit instantiations
//
// BLOCK_M=4     → 4 warps per block = 128 threads
// BLOCK_N=16/32 → KV tile size
// HEAD_DIM=64   → Qwen-0.5B / small models
// HEAD_DIM=128  → LLaMA / most production models
// GROUP_SIZE    → 1=MHA, 2/4/8=GQA, H_q=MQA
// ─────────────────────────────────────────────────────────────────────────────

#define FA2_INST(HD, BM, BN, GS) \
    template __global__ void fa2_fwd_kernel<HD, BM, BN, GS>( \
        const __half*, const __half*, const __half*, __half*, \
        int, int, int, int, int, int, int, int, int, int, int, int, int, int, int, \
        float, bool)

#define PA2_INST(HD, BM, PS, GS) \
    template __global__ void paged_attn2_fwd_kernel<HD, BM, PS, GS>( \
        const __half*, const __half*, const __half*, __half*, \
        const int*, const int*, \
        int, int, int, int, int, int, int, int, int, int, int, int, int, int, int, \
        float)

// MHA (GROUP_SIZE=1) + common GQA configs (2, 4, 8)
FA2_INST(64,  4, 16, 1);  FA2_INST(64,  4, 16, 2);  FA2_INST(64,  4, 16, 4);  FA2_INST(64,  4, 16, 8);
FA2_INST(64,  4, 32, 1);  FA2_INST(64,  4, 32, 2);  FA2_INST(64,  4, 32, 4);  FA2_INST(64,  4, 32, 8);
FA2_INST(128, 4, 16, 1);  FA2_INST(128, 4, 16, 2);  FA2_INST(128, 4, 16, 4);  FA2_INST(128, 4, 16, 8);
FA2_INST(128, 4, 32, 1);  FA2_INST(128, 4, 32, 2);  FA2_INST(128, 4, 32, 4);  FA2_INST(128, 4, 32, 8);

PA2_INST(64,  4, 16, 1);  PA2_INST(64,  4, 16, 2);  PA2_INST(64,  4, 16, 4);  PA2_INST(64,  4, 16, 8);
PA2_INST(128, 4, 16, 1);  PA2_INST(128, 4, 16, 2);  PA2_INST(128, 4, 16, 4);  PA2_INST(128, 4, 16, 8);

} // namespace attn
} // namespace vllm_clone
