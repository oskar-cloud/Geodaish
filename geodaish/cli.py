"""Train, compare, benchmark, and watch agents from one small CLI."""

import argparse
import csv
from datetime import datetime
import json
import math
from pathlib import Path
import time

import numpy as np

from geodaish.env import DIFFICULTIES, heuristic_action
from geodaish.vision import make_env


def positive_int(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return number


def positive_float(value):
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("must be a positive finite number")
    return number


def policy_action(policy, obs, rng):
    if policy == "random":
        return int(rng.integers(0, 2))
    if policy == "heuristic":
        return heuristic_action(obs)
    if policy == "idle":
        return 0
    return int(policy.predict(obs, deterministic=True)[0])


def environment_options(args):
    profile = {}
    if getattr(args, "physics_profile", None):
        content = json.loads(Path(args.physics_profile).read_text(encoding="utf-8"))
        if (not isinstance(content, dict) or not isinstance(content.get("training"), dict)
                or not {"physics", "input_delay"} <= content["training"].keys()):
            raise ValueError("Calibration JSON must contain training.physics and training.input_delay")
        profile = content["training"]
    return {"observations": getattr(args, "observations", "state"),
            "level": getattr(args, "level", "generated"),
            "input_delay": args.input_delay if getattr(args, "input_delay", None) is not None else profile.get("input_delay", 0),
            "physics": profile.get("physics", {})}


def evaluate(policy, *, difficulty="normal", episodes=30, seed=20000, environment=None):
    env = make_env(difficulty=difficulty, **(environment or {}))
    rng = np.random.default_rng(seed)
    results = []
    pipeline_times = []
    try:
        for episode in range(episodes):
            obs, info = env.reset(seed=seed + episode)
            total = 0.0
            while True:
                started = time.perf_counter()
                action = policy_action(policy, obs, rng)
                decision_ms = (time.perf_counter() - started) * 1000
                if hasattr(env, "capture_ms"):
                    pipeline_times.append(env.capture_ms + decision_ms)
                obs, reward, terminated, truncated, info = env.step(action)
                total += reward
                if terminated or truncated:
                    break
            results.append({"seed": seed + episode, "reward": total, **info})
    finally:
        env.close()
    return {
        "episodes": episodes,
        "difficulty": difficulty,
        "first_seed": seed,
        "distinct_levels": 1 if (environment or {}).get("level") == "test" else episodes,
        "environment": environment or {"observations": "state", "level": "generated", "input_delay": 0, "physics": {}},
        "capture_detection_policy_mean_ms": float(np.mean(pipeline_times)) if pipeline_times else None,
        "success_rate": float(np.mean([r["is_success"] for r in results])),
        "mean_progress": float(np.mean([r["progress"] for r in results])),
        "mean_reward": float(np.mean([r["reward"] for r in results])),
        "results": results,
    }


def load_model(path):
    import torch
    from stable_baselines3 import PPO
    torch.set_num_threads(1)
    if not Path(path).is_file() and not Path(str(path) + ".zip").is_file():
        raise ValueError(f"Model not found: {path}. Run 'geodaish train' first.")
    return PPO.load(path, device="cpu")


def train(args):
    from geodaish.dashboard import TrainingReporter
    import torch
    from stable_baselines3 import PPO
    from stable_baselines3.common.callbacks import BaseCallback
    from stable_baselines3.common.env_util import make_vec_env
    from stable_baselines3.common.logger import configure

    torch.set_num_threads(1)
    args.environment = environment_options(args)
    validation_episodes = 1 if args.environment["level"] == "test" else 10
    output = Path(args.output or f"runs/{datetime.now():%Y%m%d-%H%M%S}")
    if output.exists() and any(output.iterdir()):
        raise ValueError(f"{output} is not empty. Choose a new --output directory.")
    output.mkdir(parents=True, exist_ok=True)
    config = {key: value for key, value in vars(args).items() if key != "func"}
    config["output"] = str(output)
    (output / "config.json").write_text(json.dumps(config, indent=2) + "\n")

    class ValidationCallback(BaseCallback):
        def __init__(self):
            super().__init__()
            self.best = -float("inf")
            self.last_eval = 0

        def _on_step(self):
            reporter.observe(self.locals.get("infos", []), self.num_timesteps)
            if self.num_timesteps - self.last_eval < args.eval_every:
                return True
            self.last_eval = self.num_timesteps
            metrics = evaluate(self.model, difficulty=args.difficulty, episodes=validation_episodes, seed=10000,
                               environment=args.environment)
            row = {"timesteps": self.num_timesteps, **{k: metrics[k] for k in
                   ("success_rate", "mean_progress", "mean_reward")}}
            path = output / "validation.csv"
            exists = path.exists()
            with path.open("a", newline="") as file:
                writer = csv.DictWriter(file, fieldnames=list(row))
                if not exists:
                    writer.writeheader()
                writer.writerow(row)
            print(f"Step {self.num_timesteps:,} | validation progress {metrics['mean_progress']:.0%}"
                  f" | wins {metrics['success_rate']:.0%}", flush=True)
            self.model.save(output / "latest")
            if metrics["mean_reward"] > self.best:
                self.best = metrics["mean_reward"]
                self.model.save(output / "best")
            reporter.validation(self.model, metrics)
            return True

    env = make_vec_env(make_env, n_envs=args.envs, seed=args.seed,
                       env_kwargs={"difficulty": args.difficulty, **args.environment},
                       monitor_dir=str(output / "episodes"))
    model = None
    reporter = None
    finished = False
    started = time.perf_counter()
    interrupted = False
    try:
        if args.resume:
            model = PPO.load(args.resume, env=env, device="cpu")
            model.set_random_seed(args.seed)
        else:
            model = PPO("MlpPolicy", env, device="cpu", seed=args.seed,
                        n_steps=256, batch_size=256, n_epochs=4,
                        learning_rate=3e-4, gamma=0.99, ent_coef=0.01,
                        policy_kwargs={"net_arch": [64, 64]}, verbose=0)
        model.set_logger(configure(str(output), ["csv"]))
        print(f"Training PPO on CPU, {args.envs} environments, output: {output}", flush=True)
        print("Ctrl+C saves the current model. Timesteps round up to full rollouts.", flush=True)
        callback = ValidationCallback()
        initial_steps = model.num_timesteps
        callback.last_eval = initial_steps
        reporter = TrainingReporter(args, output, initial_steps)
        print(f"Dashboard report: {args.dashboard_file}", flush=True)
        try:
            model.learn(total_timesteps=args.steps, callback=callback,
                        reset_num_timesteps=not bool(args.resume))
        except KeyboardInterrupt:
            interrupted = True
            print("Interrupted; saving current model.", flush=True)
        model.save(output / "final")
        final_validation = evaluate(model, difficulty=args.difficulty, episodes=validation_episodes, seed=10000,
                                    environment=args.environment)
        if final_validation["mean_reward"] > callback.best:
            model.save(output / "best")
        reporter.validation(model, final_validation)
        reporter.finish(model.num_timesteps, "interrupted" if interrupted else "completed")
        finished = True
        elapsed = time.perf_counter() - started
        summary = {"timesteps_this_run": model.num_timesteps - initial_steps,
                   "seconds": elapsed, "interrupted": interrupted,
                   "validation": final_validation}
        (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        print(f"Saved {output / 'best.zip'} and final.zip in {elapsed:.1f}s", flush=True)
        flags = (f"--difficulty {args.difficulty} --observations {args.environment['observations']}"
                 f" --level {args.environment['level']} --input-delay {args.environment['input_delay']}")
        if args.physics_profile:
            flags += f" --physics-profile '{args.physics_profile}'"
        print(f"Next: geodaish evaluate --model '{output / 'best.zip'}' {flags}")
        print(f"Watch: geodaish watch --model '{output / 'best.zip'}' {flags}")
    finally:
        if reporter is not None and not finished:
            reporter.finish(model.num_timesteps, "failed")
        env.close()


def evaluate_command(args):
    policies = {"random": "random", "heuristic (hand-written)": "heuristic"}
    if args.model:
        policies["PPO (learned)"] = load_model(args.model)
    report = {}
    for name, policy in policies.items():
        metrics = evaluate(policy, difficulty=args.difficulty, episodes=args.episodes, seed=args.seed,
                           environment=environment_options(args))
        report[name] = metrics
        print(f"{name:25s} wins {metrics['success_rate']:6.1%} | "
              f"progress {metrics['mean_progress']:6.1%} | reward {metrics['mean_reward']:7.2f}")
    if args.output:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2) + "\n")
        print(f"Report: {path}")


def play(args):
    import pygame

    policy = load_model(args.model) if getattr(args, "model", None) else None
    if args.command == "watch" and policy is None:
        policy = args.policy
    env = make_env(render_mode="human", difficulty=args.difficulty, **environment_options(args))
    rng = np.random.default_rng(args.seed)
    seed = args.seed
    obs, _ = env.reset(seed=seed)
    finished_at = None
    running = True
    try:
        while running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        running = False
                    elif event.key == pygame.K_r:
                        obs, _ = env.reset(seed=seed)
                        finished_at = None
            if not running or env.unwrapped.closed:
                break
            if env.unwrapped._done:
                env.render()
                if policy is not None and time.monotonic() - finished_at > 1.0:
                    seed += 1
                    obs, _ = env.reset(seed=seed)
                    finished_at = None
                continue
            action = policy_action(policy, obs, rng) if policy is not None else int(
                pygame.key.get_pressed()[pygame.K_SPACE])
            obs, _, terminated, truncated, _ = env.step(action)
            if terminated or truncated:
                finished_at = time.monotonic()
    finally:
        env.close()


def benchmark(args):
    env = make_env(difficulty=args.difficulty, **environment_options(args))
    obs, _ = env.reset(seed=args.seed)
    started = time.perf_counter()
    for _ in range(args.steps):
        obs, _, terminated, truncated, _ = env.step(heuristic_action(obs))
        if terminated or truncated:
            obs, _ = env.reset()
    elapsed = time.perf_counter() - started
    env.close()
    print(f"{args.steps / elapsed:,.0f} environment steps/second ({args.steps / elapsed / 60:.0f}x 60 FPS).")
    print("Simulation only; PPO training also spends time updating the network.")


def calibrate_command(args):
    from geodaish.calibration import measure_jump
    report = measure_jump(input_delay=args.input_delay or 0, difficulty=args.difficulty)
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    m = report["measurements"]
    print(f"Pixel measurement in the simulator: height {m['peak_height']:.3f}, airtime {m['airtime_seconds']:.3f}s")
    print(f"Input queue: {m['input_delay_frames']} frames; command to first visible motion {m['command_to_first_motion_ms']:.1f}ms")
    print(f"Measured profile: {path}. Use --physics-profile {path} for training/evaluation/watch.")


def main():
    parser = argparse.ArgumentParser(description="Geodaish — Geometry Dash-inspired RL lab")
    sub = parser.add_subparsers(dest="command", required=True)
    from geodaish.windows.cli import register
    register(sub)
    for command in ("train", "evaluate", "play", "watch", "benchmark", "export-dashboard", "calibrate"):
        p = sub.add_parser(command)
        p.add_argument("--difficulty", choices=DIFFICULTIES, default="normal")
        p.add_argument("--seed", type=int, default=20000 if command in ("evaluate", "export-dashboard") else 42)
        if command != "export-dashboard":
            p.add_argument("--input-delay", type=int, help="Jump press/release queue in 60 Hz frames (0-30)")
        if command not in ("export-dashboard", "calibrate"):
            p.add_argument("--observations", choices=["state", "pixels"], default="state")
            p.add_argument("--level", choices=["generated", "test"], default="generated")
            p.add_argument("--physics-profile", help="JSON produced by calibrate; applies physics and input delay")
        if command == "train":
            p.add_argument("--steps", type=positive_int, default=2000000)
            p.add_argument("--envs", type=positive_int, default=4)
            p.add_argument("--eval-every", type=positive_int, default=20000)
            p.add_argument("--output")
            p.add_argument("--resume", help="Continue training a trusted local PPO checkpoint")
            p.add_argument("--dashboard-file", default="runs/live.json", help="Local dashboard snapshot")
            p.add_argument("--dashboard-url", help="Vercel URL; alternatively set GEODAISH_DASHBOARD_URL")
            p.add_argument("--report-every", type=positive_float, default=5.0, help="Telemetry interval in seconds")
            p.set_defaults(func=train)
        elif command == "evaluate":
            p.add_argument("--model")
            p.add_argument("--episodes", type=positive_int, default=30)
            p.add_argument("--output")
            p.set_defaults(func=evaluate_command)
        elif command in ("play", "watch"):
            if command == "watch":
                choice = p.add_mutually_exclusive_group(required=True)
                choice.add_argument("--model")
                choice.add_argument("--policy", choices=["random", "heuristic"])
            p.set_defaults(func=play)
        elif command == "benchmark":
            p.add_argument("--steps", type=positive_int, default=100000)
            p.set_defaults(func=benchmark)
        elif command == "calibrate":
            p.add_argument("--output", default="runs/calibration.json")
            p.set_defaults(func=calibrate_command)
        else:
            from geodaish.dashboard import export_dashboard
            p.add_argument("--run", required=True, help="Completed run directory with original CSV logs")
            p.add_argument("--model", required=True)
            p.add_argument("--evaluation", help="Optional separate evaluation JSON")
            p.add_argument("--output", default="web/data/demo.json")
            p.set_defaults(func=export_dashboard)
    args = parser.parse_args()
    if getattr(args, "seed", 0) < 0:
        parser.error("--seed must be nonnegative")
    try:
        args.func(args)
    except (ValueError, FileNotFoundError, RuntimeError) as exc:
        parser.exit(2, f"Error: {exc}\n")
