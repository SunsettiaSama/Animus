# test

功能测试，当前覆盖动作空间模块。

## 运行

```bash
cd D:\ReAct\src
python test/test_actions.py
```

## 测试列表

| 测试函数 | 验证内容 |
|---|---|
| `test_register_and_available_actions` | 注册后动作名出现在可用列表 |
| `test_weather_basic` | 基本 JSON 输入返回正确固定字符串 |
| `test_weather_with_extra_args` | 传入多余参数时不报错 |
| `test_unknown_action_raises` | 未注册动作名抛出 `ValueError` |
| `test_malformed_json_raises` | 非法 JSON 字符串抛出异常 |
