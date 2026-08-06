import pylatro
import random


def run_game() -> (bool, int):
    config = pylatro.Config()
    config.ante_end = 1
    game = pylatro.GameEngine(config)

    # Run the game
    action_space_loop(game)
    # action_loop(game)

    if game.is_win:
        print("game win!")
        print(game.state)
        # print(game.state.action_history)

    return game.is_win, game.state.score


# Use dynamic action api (dynamic sized list)
def action_loop(game: pylatro.GameState):
    while True:
        if game.is_over:
            break
        actions = game.gen_actions()
        if len(actions) > 0:
            action = random.choice(actions)
            game.handle_action(action)


# Use action space api (static/bounded list)
def action_space_loop(game: pylatro.GameState):
    while True:
        if game.is_over:
            return
        space = game.gen_action_space()
        while True:
            if 1 not in set(space):
                # for debugging, this shouldn't happened
                print("empty action space")
                print(game.state)
                return
            index = random.choice(range(len(space)))
            if space[index] == 1:
                game.handle_action_index(index)
                break


def main():
    high_score = 0
    for i in range(100_000):
        # print(f"running game {i}")
        win, score = run_game()
        if score > high_score:
            high_score = score
            print(f"new high score: {high_score} (game #{i})")


if __name__ == "__main__":
    main()
