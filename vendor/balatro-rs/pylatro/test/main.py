import pylatro
import random


# Test action space (vector) api
def test_action_space():
    game = pylatro.GameEngine()

    while True:
        if game.is_over:
            break

        # Generate static length action space vector
        action_space = game.gen_action_space()

        # Vector is masked, invalid actions are 0, valid are 1.
        # We only want to execute valid actions.
        while True:
            index = random.choice(range(len(action_space)))
            if action_space[index] == 1:
                game.handle_action_index(index)
                break

    assert game.is_over
    if game.is_win:
        print("game win!")
    else:
        print("game loss!")
    print(game.state)


if __name__ == "__main__":
    test_action_space()
