"""
test_v2.py
Quick test of V2 state parsing and action loop (no training).

Run this AFTER:
1. pip install sb3-contrib
2. Copy mod_v2/BalatroRL_v2.lua to %APPDATA%/Balatro/Mods/BalatroRL/BalatroRL.lua
3. Start Balatro and begin a run
"""

import time
import numpy as np
from balatro_rl.state_v2 import read_state, state_to_obs, OBS_SIZE
from balatro_rl.action_v2 import generate_action_mask, action_to_cards_and_type, write_action

def main():
    print("=== V2 Test ===")
    print(f"Expected observation size: {OBS_SIZE}")
    print()
    
    print("Reading state.json...")
    gs = read_state(timeout=10.0)
    if gs is None:
        print("ERROR: Could not read state.json. Is Balatro running with V2 mod?")
        return
    
    print(f"[OK] State read successfully")
    print(f"  Event: {gs.event}")
    print(f"  Ante: {gs.ante}, Blind: {gs.blind_name}")
    print(f"  Hands: {gs.hands_left}, Discards: {gs.discards_left}")
    print(f"  Hand size: {len(gs.hand)} cards")
    print(f"  Jokers: {len(gs.jokers)}")
    print()
    
    # Check V2 fields
    print(f"V2 Fields:")
    print(f"  play_options: {len(gs.play_options)}")
    if gs.play_options:
        for i, opt in enumerate(gs.play_options[:3]):
            print(f"    [{i}] {opt.hand_type} (score={opt.score:.0f}, cards={opt.indices})")
    print(f"  discard_options: {len(gs.discard_options)}")
    if gs.discard_options:
        for i, opt in enumerate(gs.discard_options[:3]):
            print(f"    [{10+i}] discard cards {opt.indices}")
    print(f"  best_play_score: {gs.best_play_score:.0f}")
    print(f"  deck_ranks: {gs.deck_ranks}")
    print(f"  deck_suits: {gs.deck_suits}")
    print()
    
    # Test observation vector
    obs = state_to_obs(gs)
    print(f"Observation vector: shape={obs.shape}, min={obs.min():.3f}, max={obs.max():.3f}")
    print()
    
    # Test action mask
    mask = generate_action_mask(gs)
    valid_plays = sum(mask[:10])
    valid_discards = sum(mask[10:])
    print(f"Action mask: {valid_plays} valid plays, {valid_discards} valid discards")
    print()
    
    # Test action conversion (dry run)
    if mask.any():
        action = np.argmax(mask)  # First valid action
        card_indices, action_type = action_to_cards_and_type(action, gs)
        print(f"Sample action {action}: {action_type} cards {card_indices}")
    
    print()
    print("=== Test complete ===")
    print()
    print("Next steps:")
    print("  1. pip install sb3-contrib")
    print("  2. Copy mod_v2/BalatroRL_v2.lua to %APPDATA%/Balatro/Mods/BalatroRL/")
    print("  3. Restart Balatro")
    print("  4. python train_v2.py")

if __name__ == "__main__":
    main()
