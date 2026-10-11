from stable_baselines3 import PPO
import torch

from geodaish.cli import evaluate
from geodaish.env import DashEnv


def test_ppo_training_save_reload_and_evaluation(tmp_path):
    torch.set_num_threads(1)
    env = DashEnv(difficulty="easy")
    model = PPO("MlpPolicy", env, n_steps=32, batch_size=32, n_epochs=1,
                policy_kwargs={"net_arch": [16]}, device="cpu", seed=0)
    before = [p.detach().clone() for p in model.policy.parameters()]
    model.learn(128)
    assert any(not torch.equal(a, b) for a, b in zip(before, model.policy.parameters()))
    model.save(tmp_path / "agent")
    loaded = PPO.load(tmp_path / "agent", device="cpu")
    first = evaluate(model, difficulty="easy", episodes=2, seed=20000)
    second = evaluate(loaded, difficulty="easy", episodes=2, seed=20000)
    assert first == second
    env.close()
