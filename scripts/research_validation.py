"""Small reference probes; independent of the BedWars Arena implementation.

Requires the isolated environment and pinned reference files listed in
reports/2026-10-25-reference-validation.md. No packages are installed here.
"""

from __future__ import annotations

import asyncio
from functools import cache
import hashlib
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import platform
import random
import socket
import subprocess
import sys
import time
import traceback


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "artifacts/research-validation-2026-10-25"
os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"


def digest(value):
    import numpy as np

    def convert(item):
        if isinstance(item, np.ndarray):
            return {"dtype": str(item.dtype), "shape": item.shape, "data": item.tolist()}
        if isinstance(item, np.generic):
            return item.item()
        if isinstance(item, bytes):
            return {"bytes": item.hex()}
        raise TypeError(type(item).__name__)

    return hashlib.sha256(json.dumps(value, sort_keys=True, default=convert).encode()).hexdigest()


def pettingzoo_probe():
    import numpy as np
    from gymnasium import spaces
    from pettingzoo import ParallelEnv
    from pettingzoo.test import parallel_api_test

    class LifecycleFixture(ParallelEnv):
        """Scripted waiting/return fixture, not BedWars rules or an engine."""

        metadata = {"name": "reference_lifecycle_fixture"}
        possible_agents = ["p0", "p1"]

        @cache
        def observation_space(self, agent):
            return spaces.Dict({"observation": spaces.Discrete(2), "action_mask": spaces.MultiBinary(2)})

        @cache
        def action_space(self, agent):
            return spaces.Discrete(2)

        def observations(self, agents):
            return {a: {"observation": int(a == "p0" and self.t in (2, 3)),
                        "action_mask": np.array([1, 0 if a == "p0" and self.t in (2, 3) else 1], dtype=np.int8)} for a in agents}

        def reset(self, seed=None, options=None):
            self.agents = self.possible_agents[:]
            self.t = 0
            return self.observations(self.agents), {a: {} for a in self.agents}

        def step(self, actions):
            previous = self.agents[:]
            if self.t in (2, 3) and "p0" in previous:
                assert actions["p0"] == 0, "Waiting player must use NOOP"
            self.t += 1
            done = self.t >= 6
            if done:
                self.agents = []
            return (self.observations(previous), dict.fromkeys(previous, 0),
                    dict.fromkeys(previous, done), dict.fromkeys(previous, False), {a: {} for a in previous})

    parallel_api_test(LifecycleFixture(), num_cycles=20)

    class InvalidRevival(LifecycleFixture):
        def step(self, actions):
            result = list(super().step(actions))
            if self.t == 2:
                self.agents = ["p1"]
                result[2]["p0"] = True
            elif self.t == 3:
                self.agents = self.possible_agents[:]
                result[0] = self.observations(self.agents)
                for index, value in [(1, 0), (2, False), (3, False), (4, {})]:
                    result[index]["p0"] = value
            return tuple(result)

    try:
        parallel_api_test(InvalidRevival(), num_cycles=20)
    except AssertionError as error:
        assert "cannot be revived" in str(error)
        rejected = str(error)
    else:
        raise AssertionError("Invalid terminated-agent revival was accepted")

    path = BASE / "reference_code/tutorial3_action_masking.py"
    spec = importlib.util.spec_from_file_location("upstream_mask_tutorial", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    env = module.CustomActionMaskedEnvironment()
    random.seed(123)
    resets = [env.reset(seed=17)[0] for _ in range(12)]
    starts = {tuple(o["prisoner"]["observation"]) for o in resets}
    return {"lifecycle_fixture_parallel_api": "passed", "invalid_revival_rejected": rejected,
            "tutorial_unique_starts_with_same_seed": len(starts),
            "tutorial_observation_matches_declared_space": env.observation_space("prisoner").contains(resets[0]["prisoner"]),
            "scope": "Interface fixture and upstream tutorial; no BedWars rules implemented"}


def lab2d_probe():
    import dmlab2d
    from dmlab2d import runfiles_helper
    import numpy as np

    def run(seed):
        lab = dmlab2d.Lab2d(runfiles_helper.find(), {"levelName": "clean_up", "numPlayers": "2"})
        names = lab.observation_names()
        actions = lab.action_discrete_names()
        lab.start(episode=0, seed=seed)
        rng = random.Random(42)
        frames = []
        for _ in range(51):
            obs = {name: lab.observation(name) for name in names}
            frames.append(digest(obs))
            if len(frames) == 51:
                break
            command = np.array([rng.randint(lab.action_discrete_spec(name)["min"],
                                           lab.action_discrete_spec(name)["max"]) for name in actions], dtype=np.int32)
            lab.act_discrete(command)
            status, reward = lab.advance()
            assert status == dmlab2d.RUNNING
            frames[-1] = digest([frames[-1], int(status), reward])
        assert any(a.startswith("1.") for a in actions) and any(a.startswith("2.") for a in actions)
        return frames, names, actions

    first, observations, actions = run(17)
    second, _, _ = run(17)
    different, _, _ = run(18)
    assert first == second
    assert first != different
    return {"level": "clean_up", "players": 2, "steps": 50, "same_seed_observation_trace_equal": True,
            "different_seed_observation_trace_differs": True, "trace_sha256": digest(first),
            "observation_names": observations, "action_names": actions,
            "scope": "Observed outputs, rewards/status; not a hash of all hidden engine state"}


def magent_probe():
    from magent2.environments import battle_v4
    from pettingzoo.test import parallel_api_test

    def make():
        return battle_v4.parallel_env(map_size=12, max_cycles=40, minimap_mode=False, extra_features=False)

    checked = make()
    try:
        parallel_api_test(checked, num_cycles=40)
    finally:
        checked.close()

    def run(seed):
        env = make()
        try:
            obs, info = env.reset(seed=seed)
            count = len(env.agents)
            shape = list(obs[env.agents[0]].shape)
            frames = [digest([obs, info, env.state()])]
            rng = random.Random(42)
            while env.agents:
                actions = {a: rng.randrange(env.action_space(a).n) for a in env.agents}
                result = env.step(actions)
                frames.append(digest([result, env.state()]))
                assert len(frames) <= 41
            return frames, count, shape
        finally:
            env.close()

    first, count, shape = run(17)
    second, _, _ = run(17)
    different, _, _ = run(18)
    assert first == second
    return {"parallel_api": "passed", "environment": "battle_v4", "initial_agents": count,
            "observation_shape": shape, "steps": len(first)-1, "same_seed_trace_equal": True,
            "different_seed_trace_differs": first != different, "trace_sha256": digest(first),
            "scope": "Public observations, state(), rewards and lifecycle; not all native internal state"}


def lux_probe():
    sys.path.insert(0, str(BASE / "reference_code"))
    from luxai_runner.process import BotProcess

    botfile = BASE / "echo_agent.py"
    botfile.write_text("import json,os,sys,time\nfor line in sys.stdin:\n m=json.loads(line)\n time.sleep(m.get('delay',0))\n print(json.dumps({'pid':os.getpid(),'action':m['tick']+1}),flush=True)\n")

    async def run():
        bots = [BotProcess(sys.executable, str(botfile), verbose=0, live_log=False) for _ in range(2)]
        try:
            await asyncio.gather(*(b.start() for b in bots))
            replies = await asyncio.wait_for(asyncio.gather(*(b.write('{"tick":3}\n') for b in bots)), timeout=5)
            values = [json.loads(r[0]) for r in replies]
            assert all(v["action"] == 4 for v in values)
            assert len({v["pid"] for v in values}) == 2
            try:
                await asyncio.wait_for(bots[0].write('{"tick":4,"delay":1}\n'), timeout=0.1)
            except TimeoutError:
                timeout = True
            else:
                raise AssertionError("Slow agent did not trigger harness timeout")
            return {"independent_processes": 2, "json_round_trip": "passed", "caller_timeout": timeout,
                    "scope": "Unmodified BotProcess module; timeout added by this probe, full Lux game/runner not run"}
        finally:
            await asyncio.gather(*(b.cleanup() for b in bots))

    return asyncio.run(run())


def bots_probe():
    directory = BASE / "bots-3ce66349ee2e239dd0ac79d1d7ec455e682c5c64/server"
    # Reserve three distinct ports until all port numbers have been selected.
    reservations = [socket.socket() for _ in range(3)]
    try:
        for s in reservations:
            s.bind(("127.0.0.1", 0))
        ports = [s.getsockname()[1] for s in reservations]
    finally:
        for s in reservations:
            s.close()
    log = BASE / "bots-smoke.log"
    clients = []
    with log.open("w") as output:
        process = subprocess.Popen([str(directory / "bots"), "-d", "-P", str(ports[0]), "-W", str(ports[1]),
                                    "-O", str(ports[2]), "-b", "2", "-M", "4", "-F", "json", "training"],
                                   stdout=output, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 5
            while True:
                try:
                    clients.append(socket.create_connection(("127.0.0.1", ports[0]), timeout=1))
                    break
                except ConnectionRefusedError:
                    if process.poll() is not None or time.monotonic() > deadline:
                        raise RuntimeError(log.read_text())
                    time.sleep(0.05)
            clients.append(socket.create_connection(("127.0.0.1", ports[0]), timeout=2))
            # The upstream server starts only after a one-second idle join window.
            for s in clients:
                s.settimeout(5)
            streams = [s.makefile("rb") for s in clients]
            views = []
            for stream in streams:
                view = [stream.readline().decode().rstrip("\n") for _ in range(5)]
                assert len(view) == 5 and all(len(row) == 5 for row in view), view
                views.append(view)
            for s in clients:
                s.sendall(b">")
            updated = [[stream.readline().decode().rstrip("\n") for _ in range(5)] for stream in streams]
            assert all(len(row) == 5 for view in updated for row in view), updated
            for stream in streams:
                stream.close()
            return {"build": "passed", "tcp_clients": 2, "local_view_shape": [5, 5], "command_round_trip": "passed",
                    "scope": "Local TCP smoke; no WebSocket, tournament or whole-game determinism test"}
        finally:
            for s in clients:
                s.close()
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)


if __name__ == "__main__":
    probes = {"pettingzoo": pettingzoo_probe, "lab2d": lab2d_probe, "magent2": magent_probe,
              "lux_process": lux_probe, "bots": bots_probe}
    selected = sys.argv[1:] or list(probes)
    results = {"date_local": "2026-10-25", "platform": platform.platform(), "python": sys.version,
               "packages": {n: importlib.metadata.version(n) for n in ("pettingzoo", "gymnasium", "dmlab2d", "magent2", "numpy")},
               "results": {}}
    for name in selected:
        try:
            details = probes[name]()
            results["results"][name] = {"status": "passed", **details}
            print(name + ": passed", flush=True)
        except Exception as error:
            results["results"][name] = {"status": "failed", "error": str(error), "traceback": traceback.format_exc()}
            print(name + ": failed: " + str(error), flush=True)
    (BASE / "probe-results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n")
    raise SystemExit(any(v["status"] == "failed" for v in results["results"].values()))
