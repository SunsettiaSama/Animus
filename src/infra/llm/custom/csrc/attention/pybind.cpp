#include <torch/extension.h>
#include <c10/cuda/CUDAGuard.h>
#include "flash_attn2.cuh"

using namespace vllm_clone::attn;

// ─────────────────────────────────────────────────────────────────────────────
// Internal helpers
// ─────────────────────────────────────────────────────────────────────────────

static inline int cdiv(int a, int b) { return (a + b - 1) / b; }

// Runtime dispatch by HEAD_DIM (64 or 128).
#define DISPATCH_HEAD_DIM(D, FUNC)                                    \
    if      ((D) == 64)  { FUNC(64);  }                              \
    else if ((D) == 128) { FUNC(128); }                              \
    else TORCH_CHECK(false, "vllm_clone: unsupported head_dim=", (D),\
                     "; expected 64 or 128")

// Runtime dispatch by GROUP_SIZE (1, 2, 4, 8).
// GROUP_SIZE=1 → MHA.  2/4/8 → common GQA configs.
#define DISPATCH_GROUP_SIZE(G, FUNC)                                         \
    if      ((G) == 1) { FUNC(1); }                                          \
    else if ((G) == 2) { FUNC(2); }                                          \
    else if ((G) == 4) { FUNC(4); }                                          \
    else if ((G) == 8) { FUNC(8); }                                          \
    else TORCH_CHECK(false, "vllm_clone: unsupported group_size=", (G),      \
                     "; expected 1, 2, 4, or 8")


// ─────────────────────────────────────────────────────────────────────────────
// fa2_fwd
//
//   q  : [B, H_q,  Sq, D]  float16, CUDA, contiguous
//   k  : [B, H_kv, Sk, D]  float16, CUDA, contiguous
//   v  : [B, H_kv, Sk, D]  float16, CUDA, contiguous
//   causal     : apply causal mask (auto-regressive generation)
//   group_size : H_q / H_kv  (1 for MHA)
//
// Grid: (ceil(Sq/BLOCK_M), H_kv, B)
//   Each thread block handles one KV head and processes GROUP_SIZE Q heads
//   together, loading the K/V tile into SMEM only once.
// ─────────────────────────────────────────────────────────────────────────────

torch::Tensor fa2_fwd(
    torch::Tensor q,
    torch::Tensor k,
    torch::Tensor v,
    bool          causal,
    int           group_size
) {
    TORCH_CHECK(q.is_cuda() && k.is_cuda() && v.is_cuda(),
                "fa2_fwd: all tensors must be on CUDA");
    TORCH_CHECK(q.scalar_type() == at::ScalarType::Half,
                "fa2_fwd: expected float16 tensors");
    TORCH_CHECK(q.is_contiguous() && k.is_contiguous() && v.is_contiguous(),
                "fa2_fwd: tensors must be contiguous");
    TORCH_CHECK(group_size >= 1,
                "fa2_fwd: group_size must be >= 1");
    TORCH_CHECK(q.size(1) == k.size(1) * group_size,
                "fa2_fwd: H_q (", q.size(1), ") must equal H_kv * group_size (",
                k.size(1), " * ", group_size, ")");

    const int B    = q.size(0);
    const int H_kv = k.size(1);
    const int Sq   = q.size(2);
    const int Sk   = k.size(2);
    const int D    = q.size(3);

    TORCH_CHECK(D % WARP_SIZE == 0,
                "fa2_fwd: head_dim must be a multiple of 32, got ", D);

    const float scale = 1.f / sqrtf(static_cast<float>(D));
    auto out = torch::empty_like(q);

    const at::cuda::CUDAGuard guard(q.device());
    cudaStream_t stream = at::cuda::getCurrentCUDAStream();

    constexpr int BLOCK_M = 4;
    constexpr int BLOCK_N = 16;
    const dim3 grid(cdiv(Sq, BLOCK_M), H_kv, B);   // ← H_kv, not H_q
    const dim3 block(BLOCK_M * WARP_SIZE);

// Inner macro: instantiate for a fixed (HD, GS) pair.
#define RUN_FA2_INNER(HD, GS)                                                \
    fa2_fwd_kernel<HD, BLOCK_M, BLOCK_N, GS><<<grid, block, 0, stream>>>(   \
        reinterpret_cast<const __half*>(q.data_ptr()),                       \
        reinterpret_cast<const __half*>(k.data_ptr()),                       \
        reinterpret_cast<const __half*>(v.data_ptr()),                       \
        reinterpret_cast<      __half*>(out.data_ptr()),                     \
        Sq, Sk,                                                              \
        (int)q.stride(0),   (int)q.stride(1),   (int)q.stride(2),          \
        (int)k.stride(0),   (int)k.stride(1),   (int)k.stride(2),          \
        (int)v.stride(0),   (int)v.stride(1),   (int)v.stride(2),          \
        (int)out.stride(0), (int)out.stride(1), (int)out.stride(2),         \
        scale, causal)

// Outer macro: dispatch GROUP_SIZE at runtime, then call inner.
#define RUN_FA2(HD) \
    DISPATCH_GROUP_SIZE(group_size, \
        if      (group_size == 1) { RUN_FA2_INNER(HD, 1); } \
        else if (group_size == 2) { RUN_FA2_INNER(HD, 2); } \
        else if (group_size == 4) { RUN_FA2_INNER(HD, 4); } \
        else                      { RUN_FA2_INNER(HD, 8); })

    DISPATCH_HEAD_DIM(D, RUN_FA2);
#undef RUN_FA2_INNER
#undef RUN_FA2

    return out;
}


// ─────────────────────────────────────────────────────────────────────────────
// paged_attn2_fwd
//
//   q           : [B, H_q,  Sq, D]                float16, CUDA
//   k_cache     : [num_phys_blocks, H_kv, PS, D]  float16, CUDA
//   v_cache     : same layout
//   block_table : [B, max_pages]                  int32,   CUDA
//   context_lens: [B]                             int32,   CUDA
//   group_size  : H_q / H_kv  (1 for MHA)
// ─────────────────────────────────────────────────────────────────────────────

torch::Tensor paged_attn2_fwd(
    torch::Tensor q,
    torch::Tensor k_cache,
    torch::Tensor v_cache,
    torch::Tensor block_table,
    torch::Tensor context_lens,
    int           group_size,
    int           q_start_pos   // -1 → no causal mask (prefill w/ full context)
                                // >=0 → abs. position of q[0] (decode or verify)
) {
    TORCH_CHECK(q.is_cuda() && k_cache.is_cuda() && v_cache.is_cuda(),
                "paged_attn2_fwd: tensors must be on CUDA");
    TORCH_CHECK(q.scalar_type() == at::ScalarType::Half,
                "paged_attn2_fwd: expected float16");
    TORCH_CHECK(group_size >= 1,
                "paged_attn2_fwd: group_size must be >= 1");
    TORCH_CHECK(q.size(1) == k_cache.size(1) * group_size,
                "paged_attn2_fwd: H_q (", q.size(1),
                ") must equal H_kv * group_size (",
                k_cache.size(1), " * ", group_size, ")");

    const int B         = q.size(0);
    const int H_kv      = k_cache.size(1);
    const int Sq        = q.size(2);
    const int D         = q.size(3);
    const int max_pages = block_table.size(1);

    TORCH_CHECK(D % WARP_SIZE == 0,
                "paged_attn2_fwd: head_dim must be a multiple of 32, got ", D);

    const float scale = 1.f / sqrtf(static_cast<float>(D));
    auto out = torch::empty_like(q);

    const at::cuda::CUDAGuard guard(q.device());
    cudaStream_t stream = at::cuda::getCurrentCUDAStream();

    constexpr int BLOCK_M   = 4;
    constexpr int PAGE_SIZE = 16;
    const dim3 grid(cdiv(Sq, BLOCK_M), H_kv, B);   // ← H_kv, not H_q
    const dim3 block(BLOCK_M * WARP_SIZE);

#define RUN_PA2_INNER(HD, GS)                                                     \
    paged_attn2_fwd_kernel<HD, BLOCK_M, PAGE_SIZE, GS><<<grid, block, 0, stream>>>( \
        reinterpret_cast<const __half*>(q.data_ptr()),                            \
        reinterpret_cast<const __half*>(k_cache.data_ptr()),                      \
        reinterpret_cast<const __half*>(v_cache.data_ptr()),                      \
        reinterpret_cast<      __half*>(out.data_ptr()),                          \
        block_table.data_ptr<int>(),                                              \
        context_lens.data_ptr<int>(),                                             \
        Sq, max_pages,                                                            \
        (int)q.stride(0),       (int)q.stride(1),       (int)q.stride(2),       \
        (int)k_cache.stride(0), (int)k_cache.stride(1), (int)k_cache.stride(2), \
        (int)v_cache.stride(0), (int)v_cache.stride(1), (int)v_cache.stride(2), \
        (int)out.stride(0),     (int)out.stride(1),     (int)out.stride(2),      \
        (int)block_table.stride(0), (int)block_table.stride(1),                  \
        scale, q_start_pos)

#define RUN_PA2(HD) \
    DISPATCH_GROUP_SIZE(group_size, \
        if      (group_size == 1) { RUN_PA2_INNER(HD, 1); } \
        else if (group_size == 2) { RUN_PA2_INNER(HD, 2); } \
        else if (group_size == 4) { RUN_PA2_INNER(HD, 4); } \
        else                      { RUN_PA2_INNER(HD, 8); })

    DISPATCH_HEAD_DIM(D, RUN_PA2);
#undef RUN_PA2_INNER
#undef RUN_PA2

    return out;
}


// ─────────────────────────────────────────────────────────────────────────────
// pybind11 module
// ─────────────────────────────────────────────────────────────────────────────

PYBIND11_MODULE(TORCH_EXTENSION_NAME, m) {
    m.doc() = "vllm-clone custom attention kernels (FA2 + Paged Attention 2, GQA-aware)";

    m.def("fa2_fwd",
          &fa2_fwd,
          "Flash Attention 2 forward (contiguous KV, GQA-aware)",
          py::arg("q"), py::arg("k"), py::arg("v"),
          py::arg("causal")     = true,
          py::arg("group_size") = 1);

    m.def("paged_attn2_fwd",
          &paged_attn2_fwd,
          "Paged Attention 2 forward (paged KV cache, GQA-aware, causal-batch-prefill)",
          py::arg("q"),
          py::arg("k_cache"),
          py::arg("v_cache"),
          py::arg("block_table"),
          py::arg("context_lens"),
          py::arg("group_size")   = 1,
          py::arg("q_start_pos")  = -1);
}
