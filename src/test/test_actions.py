import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from actions.executor import ActionExecutor
from actions.tools import WeatherAction


def test_register_and_available_actions():
    executor = ActionExecutor()
    executor.register(WeatherAction)
    assert "weather" in executor.available_actions


def test_weather_basic():
    executor = ActionExecutor()
    executor.register(WeatherAction)
    result = executor.run('{"action": "weather"}')
    assert result == "7月1日，晴天，温度为30~35°"


def test_weather_with_extra_args():
    executor = ActionExecutor()
    executor.register(WeatherAction)
    result = executor.run('{"action": "weather", "args": {"city": "Beijing"}}')
    assert result == "7月1日，晴天，温度为30~35°"


def test_unknown_action_raises():
    executor = ActionExecutor()
    raised = False
    try:
        executor.run('{"action": "fly_to_moon"}')
    except ValueError:
        raised = True
    assert raised


def test_malformed_json_raises():
    executor = ActionExecutor()
    raised = False
    try:
        executor.run("not json")
    except Exception:
        raised = True
    assert raised


if __name__ == "__main__":
    tests = [
        test_register_and_available_actions,
        test_weather_basic,
        test_weather_with_extra_args,
        test_unknown_action_raises,
        test_malformed_json_raises,
    ]
    for t in tests:
        t()
        print(f"  PASS  {t.__name__}")
    print(f"\n{len(tests)} tests passed.")
