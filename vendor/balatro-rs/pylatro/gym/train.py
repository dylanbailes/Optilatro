from matplotlib import pyplot as plt
from collections import defaultdict
import gymnasium as gym
import numpy as np
from env import register
from tqdm import tqdm


class BalatroAgent:
    def __init__(
        self,
        env: gym.Env,
        learning_rate: float,
        initial_epsilon: float,
        epsilon_decay: float,
        final_epsilon: float,
        discount_factor: float = 0.95,
    ):
        """Initialize a Reinforcement Learning agent with an empty dictionary
        of state-action values (q_values), a learning rate and an epsilon.

        Args:
            env: The training environment
            learning_rate: The learning rate
            initial_epsilon: The initial epsilon value
            epsilon_decay: The decay for epsilon
            final_epsilon: The final epsilon value
            discount_factor: The discount factor for computing the Q-value
        """
        self.env = env
        self.q_values = defaultdict(lambda: np.zeros(env.action_space.n))

        self.lr = learning_rate
        self.discount_factor = discount_factor

        self.epsilon = initial_epsilon
        self.epsilon_decay = epsilon_decay
        self.final_epsilon = final_epsilon

        self.training_error = []

    def get_action(self, obs: dict) -> int:
        """
        Returns the best action with probability (1 - epsilon)
        otherwise a random action with probability epsilon to ensure exploration.
        """
        mask = self.env.unwrapped.action_mask()
        # with probability epsilon return a random action to explore the environment
        if np.random.random() < self.epsilon:
            return self.get_rand_action(obs)
        else:
            # get best action, use it only if its valid
            action = self.get_best_action(obs)
            if mask[action] == 1:
                return action
            else:
                return self.get_rand_action(obs)

    def get_rand_action(self, obs: dict) -> int:
        mask = self.env.unwrapped.action_mask()
        space = self.env.action_space
        action = space.sample(mask)
        return action

    def get_best_action(self, obs: dict) -> int:
        obs_tuple = (
            obs["score"],
            obs["target"],
            obs["stage"],
            obs["round"],
            obs["plays"],
            obs["discards"],
            obs["money"],
            obs["deck_len"],
            obs["selected_len"],
            obs["available_len"],
            obs["discarded_len"],
            obs["jokers_len"],
        )
        action = np.argmax(self.q_values[obs_tuple])
        return action

    def update(
        self,
        obs: dict[str, int],
        action: int,
        reward: float,
        terminated: bool,
        next_obs: dict[str, int],
    ):
        """Updates the Q-value of an action."""
        obs_tuple = (
            obs["score"],
            obs["target"],
            obs["stage"],
            obs["round"],
            obs["plays"],
            obs["discards"],
            obs["money"],
            obs["deck_len"],
            obs["selected_len"],
            obs["available_len"],
            obs["discarded_len"],
            obs["jokers_len"],
        )
        next_obs_tuple = (
            next_obs["score"],
            next_obs["target"],
            next_obs["stage"],
            next_obs["round"],
            next_obs["plays"],
            next_obs["discards"],
            next_obs["money"],
            next_obs["deck_len"],
            next_obs["selected_len"],
            next_obs["available_len"],
            next_obs["discarded_len"],
            next_obs["jokers_len"],
        )

        future_q_value = (not terminated) * np.max(self.q_values[next_obs_tuple])
        temporal_difference = (
            reward
            + self.discount_factor * future_q_value
            - self.q_values[obs_tuple][action]
        )

        self.q_values[obs_tuple][action] = (
            self.q_values[obs_tuple][action] + self.lr * temporal_difference
        )
        self.training_error.append(temporal_difference)

    def decay_epsilon(self):
        self.epsilon = max(self.final_epsilon, self.epsilon - self.epsilon_decay)


def train():
    # hyperparameters
    learning_rate = 0.01
    n_episodes = 10_000_000
    start_epsilon = 1.0
    epsilon_decay = start_epsilon / (n_episodes / 2)  # reduce the exploration over time
    final_epsilon = 0.1

    register()
    env = gym.make("gymnasium_env/Balatro-v0")
    env = gym.wrappers.RecordEpisodeStatistics(env, buffer_length=n_episodes)

    agent = BalatroAgent(
        env=env,
        learning_rate=learning_rate,
        initial_epsilon=start_epsilon,
        epsilon_decay=epsilon_decay,
        final_epsilon=final_epsilon,
    )

    for episode in tqdm(range(n_episodes)):
        obs, info = env.reset()
        done = False

        # play one episode
        while not done:
            action = agent.get_action(obs)
            next_obs, reward, terminated, truncated, info = env.step(action)

            # update the agent
            agent.update(obs, action, reward, terminated, next_obs)

            # update if the environment is done and the current obs
            done = terminated or truncated
            obs = next_obs
        agent.decay_epsilon()

    plot(env, agent)


def plot(env, agent):
    # visualize the episode rewards, episode length and training error in one figure
    fig, axs = plt.subplots(1, 5, figsize=(20, 8))
    base_env = env.unwrapped

    # np.convolve will compute the rolling mean for 100 episodes
    roll_eps = 10
    # axs[0].plot(env.return_queue)
    axs[0].plot(np.convolve(env.return_queue, np.ones(roll_eps)) / roll_eps)
    axs[0].set_title("Episode Rewards")
    axs[0].set_xlabel("Episode")
    axs[0].set_ylabel("Reward")

    axs[1].plot(env.length_queue)
    axs[1].plot(np.convolve(env.length_queue, np.ones(roll_eps)) / roll_eps)
    axs[1].set_title("Episode Lengths")
    axs[1].set_xlabel("Episode")
    axs[1].set_ylabel("Length")

    axs[2].plot(agent.training_error)
    axs[2].plot(np.convolve(agent.training_error, np.ones(roll_eps)) / roll_eps)
    axs[2].set_title("Training Error")
    axs[2].set_xlabel("Episode")
    axs[2].set_ylabel("Temporal Difference")

    axs[3].plot(base_env.score_queue)
    # axs[3].plot(np.convolve(np.asarray(base_env.score_queue), np.ones(roll_eps)))
    axs[3].set_title("Scores")
    axs[3].set_xlabel("Episode")
    axs[3].set_ylabel("Score")

    axs[4].plot(base_env.actions_queue)
    # axs[4].plot(np.convolve(np.asarray(base_env.actions_queue), np.ones(roll_eps)))
    axs[4].set_title("Actions Length")
    axs[4].set_xlabel("Episode")
    axs[4].set_ylabel("Actions")

    plt.tight_layout()
    plt.show()


if __name__ == "__main__":
    train()
