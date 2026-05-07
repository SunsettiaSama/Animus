import torch
import triton
import triton.language as tl

@triton.jit
def dot_kernel(
    a_ptr, b_ptr, output_ptr,
    n_elements,
    BLOCK_SIZE: tl.constexpr
):
    pid = tl.program_id(0)                    # 获取当前 block 的索引
    block_start = pid * BLOCK_SIZE
    offsets = block_start + tl.arange(0, BLOCK_SIZE)
    mask = offsets < n_elements

    # 加载两个向量的对应块
    a_vals = tl.load(a_ptr + offsets, mask=mask)
    b_vals = tl.load(b_ptr + offsets, mask=mask)

    # 计算块内点积
    product = a_vals * b_vals
    block_sum = tl.sum(product, axis=0)        # 块内求和

    # 注意：这里只是每个 block 输出一个部分和，最后还需要在 CPU 或另一个 kernel 中合并
    # 为了简单，我们使用原子操作将块结果加到全局输出（但效率不高）
    # 更好的做法：先每个 block 输出到 output_ptr[pid]，然后在 CPU 上合并
    if pid == 0:
        # 偷懒做法：只用一个 block 计算全量（适合小向量）
        # 实际大向量应该用多个 block + 原子加或者后续归约
        pass

# 更实用的多 block 版本 + 归约
@triton.jit
def dot_kernel_multi_block(
    a_ptr, b_ptr, partial_sums_ptr,
    n_elements,
    BLOCK_SIZE: tl.constexpr
):
    pid = tl.program_id(0)
    block_start = pid * BLOCK_SIZE
    offsets = block_start + tl.arange(0, BLOCK_SIZE)
    mask = offsets < n_elements

    a_vals = tl.load(a_ptr + offsets, mask=mask, other=0.0)
    b_vals = tl.load(b_ptr + offsets, mask=mask, other=0.0)

    product = a_vals * b_vals
    block_sum = tl.sum(product, axis=0)

    # 每个 block 把自己的部分和写回 partial_sums_ptr[pid]
    tl.store(partial_sums_ptr + pid, block_sum)

def dot_product(a: torch.Tensor, b: torch.Tensor) -> torch.Tensor:
    """使用 Triton 计算向量点积"""
    assert a.shape == b.shape
    assert a.is_cuda and b.is_cuda
    n = a.numel()

    # 计算需要的 block 数量
    BLOCK_SIZE = 256
    grid = (triton.cdiv(n, BLOCK_SIZE),)

    # 存储每个 block 的部分和
    partial_sums = torch.empty(grid[0], dtype=a.dtype, device='cuda')

    # 启动 kernel
    dot_kernel_multi_block[grid](a, b, partial_sums, n, BLOCK_SIZE=BLOCK_SIZE)

    # 在 CPU 上合并部分和（也可以写一个简单的归约 kernel）
    result = partial_sums.sum().item()
    return torch.tensor(result, device='cpu')

# 测试
if __name__ == '__main__':
    n = 1024
    a = torch.randn(n, device='cuda', dtype=torch.float32)
    b = torch.randn(n, device='cuda', dtype=torch.float32)

    # PyTorch 原生
    expected = torch.dot(a, b).cpu().item()

    # Triton 实现
    out = dot_product(a, b).item()

    print(f"PyTorch: {expected:.6f}, Triton: {out:.6f}, diff: {abs(expected-out):.2e}")