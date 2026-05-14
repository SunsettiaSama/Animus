"""Mock LLM执行器，用于在没有API密钥时测试节点行为"""
from __future__ import annotations

from typing import Any, Mapping


class MockLLMCodeExecutor:
    """Mock执行器，返回预定义的Python函数"""

    def __init__(self, config_path: str):
        self.generated_code = {}

    def run(self, spec, inputs: Mapping[str, Any]) -> Any:
        """根据task_id返回预定义的mock函数"""
        task_id = spec.task_id
        
        mock_functions = {
            "task_0": self._mock_get_type_info,
            "task_1": self._mock_process_string,
            "task_2": self._mock_calc_stats,
            "task_3": self._mock_group_by_type,
            "task_4": self._mock_filter_by_types,
            "task_5": self._mock_transform_to_stats,
            "task_6": self._mock_aggregate_results,
            "task_7": self._mock_validate_transform,
            "task_8": self._mock_format_report,
            "task_9": self._mock_full_analysis,
        }
        
        if task_id not in mock_functions:
            raise ValueError(f"未知的task_id: {task_id}")
        
        func_factory = mock_functions[task_id]
        return func_factory(inputs)

    def _mock_get_type_info(self, inputs):
        def get_type_info(*args):
            return {i: type(arg).__name__ for i, arg in enumerate(args)}
        return get_type_info

    def _mock_process_string(self, inputs):
        get_type_info = inputs.get("task_0")
        
        def process_string(s: str) -> dict:
            return {
                "original": s,
                "reversed": s[::-1],
                "upper": s.upper(),
                "lower": s.lower(),
                "type_info": get_type_info(s) if get_type_info else {"0": "str"},
            }
        return process_string

    def _mock_calc_stats(self, inputs):
        def calc_stats(numbers: list) -> dict:
            if not numbers:
                return {"sum": 0, "mean": 0, "min": None, "max": None, "count": 0}
            return {
                "sum": sum(numbers),
                "mean": sum(numbers) / len(numbers),
                "min": min(numbers),
                "max": max(numbers),
                "count": len(numbers),
            }
        return calc_stats

    def _mock_group_by_type(self, inputs):
        def group_by_type(items: list) -> dict:
            result = {}
            for item in items:
                type_name = type(item).__name__
                if type_name not in result:
                    result[type_name] = []
                result[type_name].append(item)
            return result
        return group_by_type

    def _mock_filter_by_types(self, inputs):
        group_by_type = inputs.get("task_3")
        
        def filter_by_types(items: list, allowed_types: list) -> list:
            grouped = group_by_type(items) if group_by_type else {}
            result = []
            for type_name in allowed_types:
                result.extend(grouped.get(type_name, []))
            return result
        return filter_by_types

    def _mock_transform_to_stats(self, inputs):
        calc_stats = inputs.get("task_2")
        group_by_type = inputs.get("task_3")
        
        def transform_to_stats(items: list) -> dict:
            grouped = group_by_type(items) if group_by_type else {}
            type_counts = {k: len(v) for k, v in grouped.items()}
            
            numbers = [x for x in items if isinstance(x, (int, float)) and not isinstance(x, bool)]
            numeric_stats = calc_stats(numbers) if calc_stats and numbers else {}
            
            return {
                "type_counts": type_counts,
                "numeric_stats": numeric_stats,
            }
        return transform_to_stats

    def _mock_aggregate_results(self, inputs):
        transform_to_stats = inputs.get("task_5")
        
        def aggregate_results(data_list: list[list]) -> dict:
            all_stats = []
            total_items = 0
            
            for data in data_list:
                if transform_to_stats:
                    stats = transform_to_stats(data)
                    all_stats.append(stats)
                    total_items += sum(stats.get("type_counts", {}).values())
            
            return {
                "batch_count": len(data_list),
                "total_items": total_items,
                "individual_stats": all_stats,
            }
        return aggregate_results

    def _mock_validate_transform(self, inputs):
        transform_to_stats = inputs.get("task_5")
        
        def validate_transform(items: list) -> dict:
            if transform_to_stats:
                stats = transform_to_stats(items)
                type_counts = stats.get("type_counts", {})
                total = sum(type_counts.values())
                valid = total == len(items)
            else:
                valid = False
                total = 0
            
            return {
                "valid": valid,
                "details": {
                    "expected_count": len(items),
                    "actual_count": total,
                    "match": valid,
                },
            }
        return validate_transform

    def _mock_format_report(self, inputs):
        process_string = inputs.get("task_1")
        validate_transform = inputs.get("task_7")
        
        def format_report(validation: dict) -> str:
            title = "VALIDATION REPORT"
            if process_string:
                title_processed = process_string(title)
                title = title_processed.get("upper", title)
            
            valid = validation.get("valid", False)
            details = validation.get("details", {})
            
            report = f"{title}\n{'='*len(title)}\n\n"
            report += f"Status: {'✓ VALID' if valid else '✗ INVALID'}\n\n"
            report += "Details:\n"
            for k, v in details.items():
                report += f"  - {k}: {v}\n"
            
            return report
        return format_report

    def _mock_full_analysis(self, inputs):
        get_type_info = inputs.get("task_0")
        group_by_type = inputs.get("task_3")
        filter_by_types = inputs.get("task_4")
        transform_to_stats = inputs.get("task_5")
        aggregate_results = inputs.get("task_6")
        validate_transform = inputs.get("task_7")
        format_report = inputs.get("task_8")
        
        def full_analysis(items: list) -> dict:
            result = {}
            
            if get_type_info:
                result["input_info"] = get_type_info(*items)
            
            if group_by_type:
                result["grouped"] = group_by_type(items)
            
            if filter_by_types:
                result["filtered_numbers"] = filter_by_types(items, ["int", "float"])
            
            if transform_to_stats:
                result["stats"] = transform_to_stats(items)
            
            if aggregate_results:
                result["aggregated"] = aggregate_results([items])
            
            if validate_transform:
                result["validation"] = validate_transform(items)
            
            if format_report and "validation" in result:
                result["report"] = format_report(result["validation"])
            
            return result
        
        return full_analysis

    def get_generated_code(self, task_id: str) -> str:
        return f"# Mock code for {task_id}\n# (真实执行时会调用LLM生成代码)"
