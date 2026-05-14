"""
实际运行Flow节点的测试脚本

用法：
    cd E:\ReAct
    python src\test\agent\flow\run_flow_test.py
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Mapping

import yaml

ROOT = Path(__file__).parent.parent.parent.parent.parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from agent.flow.base.components.node_spec import (
    ExecutionLayer,
    ExecutionNodeSpec,
    MetadataLayer,
)
from agent.flow.base.components.runtime import RunnableExecutionNode
from agent.flow.base.link import assert_acyclic, index_nodes, layers, ready_ids
from agent.flow.base.types import NodeStatus

CONFIG_DIR = ROOT / "config" / "test"


class SimpleNodeExecutor:
    """简单的执行器接口，委托给LLMCodeExecutor"""

    def __init__(self, llm_executor):
        self.llm_executor = llm_executor

    def run(self, spec: ExecutionNodeSpec, inputs: Mapping[str, Any]) -> Any:
        return self.llm_executor.run(spec, inputs)


def load_tasks() -> list[dict]:
    """加载任务定义"""
    with open(CONFIG_DIR / "coding_tasks.yaml", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data["tasks"]


def create_execution_nodes(tasks: list[dict]) -> list[ExecutionNodeSpec]:
    """将任务定义转换为ExecutionNodeSpec"""
    nodes = []
    for task in tasks:
        spec = ExecutionNodeSpec(
            metadata=MetadataLayer(
                task_id=task["task_id"],
                node_type="llm_code_gen",
                depends_on=tuple(task["dependencies"]),
                tags={
                    "description": task["description"],
                    "prompt": task["prompt"],
                    "expected_output": task["expected_output_key"],
                },
            ),
            execution=ExecutionLayer(
                kind="llm_code_gen",
            ),
        )
        nodes.append(spec)
    return nodes


def run_dag_scheduler(nodes: list[ExecutionNodeSpec], executor_factory) -> dict[str, Any]:
    """简单的DAG调度器：按拓扑顺序执行节点"""
    
    assert_acyclic(nodes)
    
    node_map = index_nodes(nodes)
    status: dict[str, NodeStatus] = {}
    outputs: dict[str, Any] = {}
    
    wave_list = layers(nodes)
    print(f"\n{'='*80}")
    print(f"DAG Topology Layers (Total: {len(wave_list)} layers):")
    for i, wave in enumerate(wave_list):
        print(f"  Layer {i}: {wave}")
    print(f"{'='*80}\n")
    
    executor = executor_factory()
    
    for wave_idx, wave in enumerate(wave_list):
        print(f"\n{'-'*80}")
        print(f"Executing Layer {wave_idx}: {wave}")
        print(f"{'-'*80}")
        
        for task_id in wave:
            spec = node_map[task_id]
            
            deps = spec.depends_on
            inputs = {dep: outputs[dep] for dep in deps}
            
            print(f"\n[{task_id}] Executing...")
            print(f"  Desc: {spec.metadata.tags.get('description', '')}")
            print(f"  Deps: {sorted(deps) if deps else 'None'}")
            
            try:
                runnable = RunnableExecutionNode(spec=spec, executor=executor)
                result = runnable.run(inputs)
                
                outputs[task_id] = result
                status[task_id] = NodeStatus.done
                
                print(f"  Status: [OK] Success")
                if callable(result):
                    print(f"  Output: <function {result.__name__}>")
                else:
                    print(f"  Output: {result}")
                    
            except Exception as e:
                status[task_id] = NodeStatus.failed
                print(f"  Status: [FAIL] Failed")
                print(f"  Error: {e}")
                raise
    
    return outputs


def test_generated_functions(outputs: dict[str, Any]):
    """Test if generated functions work correctly"""
    print(f"\n\n{'='*80}")
    print("Function Testing: Verify Generated Functions")
    print(f"{'='*80}\n")
    
    test_data = [1, "hello", 2, "world", 3.14, [1, 2], {"a": 1}]
    
    try:
        if "task_9" in outputs:
            full_analysis = outputs["task_9"]
            print(f"[TEST] Calling full_analysis({test_data})")
            result = full_analysis(test_data)
            print(f"\nResult:")
            for key, value in result.items():
                print(f"  {key}: {value}")
            print("\n[OK] full_analysis executed successfully!")
        
        if "task_2" in outputs:
            calc_stats = outputs["task_2"]
            numbers = [1, 2, 3, 4, 5]
            print(f"\n[TEST] Calling calc_stats({numbers})")
            stats = calc_stats(numbers)
            print(f"Result: {stats}")
            print("[OK] calc_stats executed successfully!")
        
        if "task_1" in outputs:
            process_string = outputs["task_1"]
            test_str = "Hello World"
            print(f"\n[TEST] Calling process_string('{test_str}')")
            str_result = process_string(test_str)
            print(f"Result: {str_result}")
            print("[OK] process_string executed successfully!")
            
    except Exception as e:
        print(f"\n[FAIL] Test failed: {e}")
        raise


def main():
    """Main function"""
    print("="*80)
    print("Flow Node Real Execution Test")
    print("="*80)
    
    print("\n[1] Loading config and tasks...")
    tasks = load_tasks()
    print(f"    Loaded {len(tasks)} tasks")
    
    print("\n[2] Creating ExecutionNodeSpec...")
    nodes = create_execution_nodes(tasks)
    print(f"    Created {len(nodes)} nodes")
    
    print("\n[3] Checking API config...")
    api_config_path = CONFIG_DIR / "api_config.yaml"
    if not api_config_path.exists():
        print(f"    Error: Config not found at {api_config_path}")
        return
    
    with open(api_config_path, encoding="utf-8") as f:
        api_cfg = yaml.safe_load(f)
    api_key = api_cfg.get("llm", {}).get("api_key", "")
    if not api_key:
        use_mock = input("\n    api_config.yaml 中未配置 api_key，使用 Mock 执行器? [y/N] ").lower()
        if use_mock == "y":
            from llm_mock_executor import MockLLMCodeExecutor

            def executor_factory():
                return SimpleNodeExecutor(MockLLMCodeExecutor(str(api_config_path)))
        else:
            print("    Exiting. Please set api_key in api_config.yaml and retry.")
            return
    else:
        print(f"    [OK] Found API key: {api_key[:8]}...")
        from llm_code_executor import LLMCodeExecutor

        def executor_factory():
            return SimpleNodeExecutor(LLMCodeExecutor(str(api_config_path)))
    
    print("\n[4] Executing DAG...")
    outputs = run_dag_scheduler(nodes, executor_factory)
    
    print("\n[5] Function testing...")
    test_generated_functions(outputs)
    
    print("\n" + "="*80)
    print("[OK] All tests completed!")
    print("="*80)


if __name__ == "__main__":
    main()
