"""LLM驱动的代码生成执行器，用于测试节点行为"""
from __future__ import annotations

import re
from typing import Any, Mapping

import httpx
import yaml


class LLMCodeExecutor:
    """使用LLM API生成并执行Python代码"""

    def __init__(self, config_path: str):
        with open(config_path, encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        
        self.llm_config = cfg["llm"]
        self.api_key = self.llm_config.get("api_key", "")
        
        self.base_url = self.llm_config["base_url"]
        self.model = self.llm_config["model"]
        self.temperature = self.llm_config.get("temperature", 0.2)
        self.max_tokens = self.llm_config.get("max_tokens", 2000)
        self.timeout = self.llm_config.get("timeout", 60)
        
        self.generated_code = {}  # task_id -> 生成的代码

    def run(self, spec, inputs: Mapping[str, Any]) -> Any:
        """
        根据spec生成代码并执行
        
        Args:
            spec: ExecutionNodeSpec，包含任务描述和提示
            inputs: 上游节点的输出（函数引用）
        
        Returns:
            生成的函数
        """
        task_id = spec.task_id
        prompt = spec.metadata.tags.get("prompt", "")
        
        system_prompt = """你是一个Python代码生成专家。根据用户需求生成Python函数。

要求：
1. 只生成函数定义，不要有额外说明
2. 函数必须完整可执行
3. 如果需要使用其他函数，它们会作为globals提供
4. 使用type hints
5. 包含简要docstring

格式：直接输出Python代码，用```python包裹"""

        user_prompt = f"""任务ID: {task_id}

{prompt}

可用的依赖函数：{list(inputs.keys())}

请生成完整的Python函数代码。"""

        code = self._call_llm(system_prompt, user_prompt)
        
        self.generated_code[task_id] = code
        
        func = self._execute_code(code, inputs)
        return func

    def _call_llm(self, system: str, user: str) -> str:
        """调用LLM API"""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                )
                resp.raise_for_status()
                result = resp.json()
                content = result["choices"][0]["message"]["content"]
                
                code_match = re.search(r"```python\n(.*?)\n```", content, re.DOTALL)
                if code_match:
                    return code_match.group(1)
                return content
                
        except Exception as e:
            raise RuntimeError(f"LLM API调用失败: {e}")

    def _execute_code(self, code: str, inputs: Mapping[str, Any]) -> Any:
        """执行生成的代码，返回定义的函数"""
        local_scope = {}
        global_scope = dict(inputs)
        
        try:
            exec(code, global_scope, local_scope)
            
            if not local_scope:
                raise ValueError("代码未定义任何函数")
            
            func_name = list(local_scope.keys())[0]
            return local_scope[func_name]
            
        except Exception as e:
            raise RuntimeError(f"代码执行失败: {e}\n\n生成的代码:\n{code}")

    def get_generated_code(self, task_id: str) -> str:
        """获取某个任务生成的代码"""
        return self.generated_code.get(task_id, "")
