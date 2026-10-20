"""L3 策略层：变量→决策，纯函数无副作用。"""

from agent.soul.heartbeat.policy.inject_policy import should_offer_inject
from agent.soul.heartbeat.policy.liveness_policy import FAILING_THRESHOLD, judge_liveness
from agent.soul.heartbeat.policy.sleep_policy import may_sleep

__all__ = ["should_offer_inject", "may_sleep", "judge_liveness", "FAILING_THRESHOLD"]
