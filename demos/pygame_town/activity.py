"""Hourly poll: each game-hour pick a random agent, move, then act."""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import TYPE_CHECKING

from agents import DEST_CABIN, DEST_PLAZA, DEST_YARD, Agent
from crops import Crop

if TYPE_CHECKING:
    from world import World

# 活动种类：先走到地点，再执行
ACT_WATER = "water"
ACT_HARVEST = "harvest"
ACT_REST = "rest"
ACT_PLAZA = "plaza"
ACT_TEND = "tend"

PHASE_MOVE = "move"
PHASE_ACT = "act"


@dataclass
class ActivityJob:
    agent: Agent
    kind: str
    phase: str = PHASE_MOVE
    crop: Crop | None = None
    note: str = ""


class HourlyActivityPoll:
    """每游戏小时轮询一次：随机派一个空闲村民，先移动再做事。"""

    def __init__(self, world: World) -> None:
        self.world = world
        self.job: ActivityJob | None = None
        self.last_note = ""

    def poll_hour(self) -> str:
        """Called when a game-hour ticks. Returns status text."""
        if self.job is not None:
            # 上一小时任务未完成：打断并释放
            self._finish(self.job, interrupted=True)

        free = [a for a in self.world.agents if not a.busy]
        if not free:
            self.last_note = "poll: all busy"
            return self.last_note

        agent = random.choice(free)
        kind, crop, dest, target, note = self._pick_action(agent)
        agent.busy = True
        agent.destination = dest
        agent.target_xy = target
        self.job = ActivityJob(agent=agent, kind=kind, crop=crop, note=note)
        agent.set_bubble(f"去{note}…", ttl=4.0)
        self.last_note = f"poll->{agent.name}:{kind}"
        return self.last_note

    def _pick_action(self, agent: Agent) -> tuple[str, Crop | None, str, tuple[float, float], str]:
        owned = self.world.crops_for(agent.home_id)
        ready = [c for c in owned if c.ready and not c.harvested]
        dry = [c for c in owned if not c.watered and not c.ready and not c.harvested]

        options: list[str] = [ACT_REST, ACT_PLAZA, ACT_TEND]
        if dry:
            options.append(ACT_WATER)
        if ready:
            options.append(ACT_HARVEST)

        kind = random.choice(options)
        points = self.world.home_points(agent.home_id)

        if kind == ACT_WATER:
            crop = random.choice(dry)
            return kind, crop, DEST_YARD, self.world.crop_xy(crop), "浇水"
        if kind == ACT_HARVEST:
            crop = random.choice(ready)
            return kind, crop, DEST_YARD, self.world.crop_xy(crop), "收菜"
        if kind == ACT_REST:
            return kind, None, DEST_CABIN, points[DEST_CABIN], "歇息"
        if kind == ACT_PLAZA:
            return kind, None, DEST_PLAZA, points[DEST_PLAZA], "广场"
        # tend yard
        return kind, None, DEST_YARD, points[DEST_YARD], "看田"

    def update(self) -> str:
        """Advance move→act when the agent arrives. Returns optional status."""
        job = self.job
        if job is None:
            return ""
        if job.phase != PHASE_MOVE:
            return ""
        if not job.agent.at_destination():
            return ""
        job.phase = PHASE_ACT
        msg = self._perform(job)
        self._finish(job, interrupted=False)
        return msg

    def _perform(self, job: ActivityJob) -> str:
        agent = job.agent
        kind = job.kind
        if kind == ACT_WATER and job.crop is not None:
            if job.crop.water():
                agent.set_bubble("浇好了。", ttl=5.0)
                return f"{agent.name} watered"
            agent.set_bubble("这株不用浇了。", ttl=4.0)
            return f"{agent.name} water skip"
        if kind == ACT_HARVEST and job.crop is not None:
            if job.crop.harvest():
                self.world.harvest_count += 1
                job.crop.reset_plant()
                agent.set_bubble("收了一把！", ttl=5.0)
                return f"{agent.name} harvested"
            agent.set_bubble("还没收成。", ttl=4.0)
            return f"{agent.name} harvest skip"
        if kind == ACT_REST:
            agent.set_bubble("歇一会儿…", ttl=6.0)
            return f"{agent.name} rest"
        if kind == ACT_PLAZA:
            agent.set_bubble("在广场逛逛。", ttl=5.0)
            return f"{agent.name} plaza"
        agent.set_bubble("田里看看。", ttl=5.0)
        return f"{agent.name} tend"

    def _finish(self, job: ActivityJob, *, interrupted: bool) -> None:
        job.agent.busy = False
        if interrupted:
            job.agent.set_bubble("换事先走。", ttl=3.0)
        self.job = None
