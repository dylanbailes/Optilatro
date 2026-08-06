-- BalatroRL_parallel.lua
-- Multi-instance version for parallel training.
-- Each instance uses a separate state/action file based on INSTANCE_ID.
--
-- USAGE:
-- 1. Copy this file to each Balatro install's Mods/BalatroRL/ folder
-- 2. Set a unique INSTANCE_ID for each (1, 2, 3, etc.)
-- 3. Launch each Balatro instance
-- 4. Python env connects to balatro_rl_1/, balatro_rl_2/, etc.

-- ═══════════════════════════════════════════════════════════════════════════
-- INSTANCE CONFIGURATION
-- ═══════════════════════════════════════════════════════════════════════════
local INSTANCE_ID = 1  -- Change this per instance (1, 2, 3, etc.)

-- ═══════════════════════════════════════════════════════════════════════════
-- CUSTOM GAME SPEED (requires Handy mod)
-- ═══════════════════════════════════════════════════════════════════════════
local CUSTOM_GAME_SPEED = 100  -- Set custom speed (nil = use Handy default)

-- ═══════════════════════════════════════════════════════════════════════════
-- MINIMAL GRAPHICS MODE
-- ═══════════════════════════════════════════════════════════════════════════
local MINIMAL_GRAPHICS = true  -- Toggle for faster training


BalatroRL = {}

-- Instance-specific paths
local STATE_DIR  = "balatro_rl_" .. INSTANCE_ID
local STATE_FILE = STATE_DIR .. "/state.json"
local ACTION_FILE = STATE_DIR .. "/action.json"
local LOG_FILE   = STATE_DIR .. "/log.txt"

-- ── JSON encoder ─────────────────────────────────────────────────────────────

local function json_str(s)
    return '"' .. tostring(s):gsub('\\','\\\\'):gsub('"','\\"'):gsub('\n','\\n') .. '"'
end

local function json_encode(val, depth)
    depth = depth or 0
    if depth > 10 then return '"[MAX_DEPTH]"' end
    local t = type(val)
    if val == nil then return "null"
    elseif t == "boolean" then return tostring(val)
    elseif t == "number" then
        if val ~= val then return "0" end
        return tostring(math.floor(val) == val and math.floor(val) or val)
    elseif t == "string" then return json_str(val)
    elseif t == "table" then
        local is_array = true
        local max_i = 0
        for k, _ in pairs(val) do
            if type(k) ~= "number" or k < 1 or math.floor(k) ~= k then
                is_array = false
                break
            end
            if k > max_i then max_i = k end
        end
        if is_array and max_i > 0 then
            local parts = {}
            for i = 1, max_i do
                parts[i] = json_encode(val[i], depth + 1)
            end
            return "[" .. table.concat(parts, ",") .. "]"
        else
            local parts = {}
            for k, v in pairs(val) do
                table.insert(parts, json_str(k) .. ":" .. json_encode(v, depth + 1))
            end
            return "{" .. table.concat(parts, ",") .. "}"
        end
    end
    return '"[UNKNOWN]"'
end

-- ── Config ───────────────────────────────────────────────────────────────────

local default_cfg = {
    lua_nav    = true,
    buy_jokers = true,
    debug_log  = false,
}

function BalatroRL.cfg()
    if SMODS and SMODS.current_mod and SMODS.current_mod.config then
        local c = SMODS.current_mod.config
        return {
            lua_nav    = c.lua_nav    ~= false,
            buy_jokers = c.buy_jokers ~= false,
            debug_log  = c.debug_log  == true,
        }
    end
    return default_cfg
end

-- ── Logging ──────────────────────────────────────────────────────────────────

function BalatroRL.log(msg)
    if BalatroRL.cfg().debug_log then
        love.filesystem.append(LOG_FILE, os.time() .. " " .. tostring(msg) .. "\n")
    end
end

-- ── Number formatting ────────────────────────────────────────────────────────

function BalatroRL.format_number(n)
    if n >= 1e9 then return string.format("%.1fB", n/1e9)
    elseif n >= 1e6 then return string.format("%.1fM", n/1e6)
    elseif n >= 1e3 then return string.format("%.1fK", n/1e3)
    else return string.format("%.0f", n) end
end

-- ── Hand enumeration & scoring (V2) ──────────────────────────────────────────

local HAND_ORDER = {
    "Flush Five", "Flush House", "Five of a Kind",
    "Straight Flush", "Four of a Kind", "Full House",
    "Flush", "Straight", "Three of a Kind",
    "Two Pair", "Pair", "High Card"
}

local BASE_CHIPS = {
    ["Flush Five"]=160, ["Flush House"]=140, ["Five of a Kind"]=120,
    ["Straight Flush"]=100, ["Four of a Kind"]=60, ["Full House"]=40,
    ["Flush"]=35, ["Straight"]=30, ["Three of a Kind"]=30,
    ["Two Pair"]=20, ["Pair"]=10, ["High Card"]=5
}
local BASE_MULT = {
    ["Flush Five"]=16, ["Flush House"]=14, ["Five of a Kind"]=12,
    ["Straight Flush"]=8, ["Four of a Kind"]=7, ["Full House"]=4,
    ["Flush"]=4, ["Straight"]=4, ["Three of a Kind"]=3,
    ["Two Pair"]=2, ["Pair"]=2, ["High Card"]=1
}

local function get_hand_levels()
    local levels = {}
    if G and G.GAME and G.GAME.hands then
        for name, data in pairs(G.GAME.hands) do
            levels[name] = {
                level = data.level or 1,
                chips = data.chips or BASE_CHIPS[name] or 10,
                mult  = data.mult  or BASE_MULT[name]  or 1,
            }
        end
    end
    return levels
end

local function card_rank_value(card)
    local id = card.base and card.base.id or card.id or 2
    if id == 14 then return 14 end
    return id
end

local function card_chip_value(card)
    local id = card.base and card.base.id or card.id or 2
    if id == 14 then return 11 end
    if id >= 10 then return 10 end
    return id
end

local function count_ranks(cards)
    local counts = {}
    for _, c in ipairs(cards) do
        local r = card_rank_value(c)
        counts[r] = (counts[r] or 0) + 1
    end
    return counts
end

local function count_suits(cards)
    local counts = {}
    for _, c in ipairs(cards) do
        local s = c.base and c.base.suit or "Spades"
        counts[s] = (counts[s] or 0) + 1
    end
    return counts
end

local function is_straight(cards)
    if #cards < 5 then return false end
    local ranks = {}
    for _, c in ipairs(cards) do
        ranks[card_rank_value(c)] = true
    end
    local sorted = {}
    for r in pairs(ranks) do table.insert(sorted, r) end
    table.sort(sorted)
    if #sorted < 5 then return false end
    -- Check consecutive
    for i = 1, #sorted - 4 do
        local consec = true
        for j = 0, 3 do
            if sorted[i+j+1] - sorted[i+j] ~= 1 then consec = false break end
        end
        if consec then return true end
    end
    -- Ace-low straight (A-2-3-4-5)
    if ranks[14] and ranks[2] and ranks[3] and ranks[4] and ranks[5] then
        return true
    end
    return false
end

local function classify_hand(cards)
    if #cards == 0 then return "High Card", {} end
    
    local rank_counts = count_ranks(cards)
    local suit_counts = count_suits(cards)
    
    local max_rank_count = 0
    local rank_freq = {}
    for r, c in pairs(rank_counts) do
        max_rank_count = math.max(max_rank_count, c)
        rank_freq[c] = (rank_freq[c] or 0) + 1
    end
    
    local max_suit_count = 0
    for s, c in pairs(suit_counts) do
        max_suit_count = math.max(max_suit_count, c)
    end
    
    local is_flush = max_suit_count >= 5 or (#cards <= 5 and max_suit_count == #cards and #cards >= 5)
    local is_str = is_straight(cards)
    
    -- Check for flush with 5 cards
    if #cards == 5 then
        is_flush = max_suit_count == 5
    end
    
    if max_rank_count == 5 then
        if is_flush then return "Flush Five", cards end
        return "Five of a Kind", cards
    end
    
    if max_rank_count == 4 and rank_freq[1] and #cards == 5 then
        -- Could be Flush House? No, that's 3+2 flush
    end
    
    if rank_freq[3] and rank_freq[2] then
        if is_flush and #cards == 5 then return "Flush House", cards end
        return "Full House", cards
    end
    
    if is_str and is_flush then return "Straight Flush", cards end
    if max_rank_count == 4 then return "Four of a Kind", cards end
    if is_flush then return "Flush", cards end
    if is_str then return "Straight", cards end
    if max_rank_count == 3 then return "Three of a Kind", cards end
    if rank_freq[2] and rank_freq[2] >= 2 then return "Two Pair", cards end
    if max_rank_count == 2 then return "Pair", cards end
    
    return "High Card", cards
end

local function estimate_score(cards, levels)
    if #cards == 0 then return 0, "High Card" end
    
    local hand_name, scoring_cards = classify_hand(cards)
    local lvl = levels[hand_name] or { level = 1, chips = BASE_CHIPS[hand_name] or 5, mult = BASE_MULT[hand_name] or 1 }
    
    local base_chips = lvl.chips or BASE_CHIPS[hand_name] or 5
    local base_mult  = lvl.mult  or BASE_MULT[hand_name]  or 1
    
    -- Add card chip values
    local card_chips = 0
    for _, c in ipairs(cards) do
        card_chips = card_chips + card_chip_value(c)
    end
    
    -- Check for boss blind debuffs
    local dominated_suit = nil
    if G and G.GAME and G.GAME.blind and G.GAME.blind.name then
        local bn = G.GAME.blind.name
        if bn == "The Goad" then dominated_suit = "Spades"
        elseif bn == "The Head" then dominated_suit = "Hearts"
        elseif bn == "The Club" then dominated_suit = "Clubs"
        elseif bn == "The Plant" then dominated_suit = "Diamonds"
        end
    end
    
    if dominated_suit then
        local valid_chips = 0
        local has_valid = false
        for _, c in ipairs(cards) do
            local suit = c.base and c.base.suit or "Spades"
            if suit ~= dominated_suit then
                valid_chips = valid_chips + card_chip_value(c)
                has_valid = true
            end
        end
        if not has_valid then
            return 0, hand_name  -- All cards debuffed
        end
        card_chips = valid_chips
    end
    
    local total = (base_chips + card_chips) * base_mult
    return math.floor(total), hand_name
end

-- Generate all combinations C(n,k)
local function combinations(arr, k)
    local result = {}
    local n = #arr
    if k > n or k <= 0 then return result end
    if k == n then return {arr} end
    
    local combo = {}
    local function generate(start, depth)
        if depth > k then
            local copy = {}
            for i = 1, k do copy[i] = arr[combo[i]] end
            table.insert(result, copy)
            return
        end
        for i = start, n - (k - depth) do
            combo[depth] = i
            generate(i + 1, depth + 1)
        end
    end
    generate(1, 1)
    return result
end

-- Enumerate all possible plays and rank by estimated score
local function enumerate_plays(hand_cards)
    local levels = get_hand_levels()
    local plays = {}
    
    -- Generate all subsets of size 1-5
    for k = 1, math.min(5, #hand_cards) do
        local combos = combinations(hand_cards, k)
        for _, combo in ipairs(combos) do
            local score, hand_name = estimate_score(combo, levels)
            local indices = {}
            for _, card in ipairs(combo) do
                for i, hc in ipairs(hand_cards) do
                    if hc == card then
                        table.insert(indices, i)
                        break
                    end
                end
            end
            table.insert(plays, {
                cards = combo,
                indices = indices,
                score = score,
                hand_name = hand_name,
            })
        end
    end
    
    -- Sort by score descending
    table.sort(plays, function(a, b) return a.score > b.score end)
    
    return plays
end

-- ── State collection ─────────────────────────────────────────────────────────

local function collect_state(event_name)
    if not G then return nil end
    local game = G.GAME or {}
    local round = game.current_round or {}
    local blind = game.blind or {}
    local rr = game.round_resets or {}
    
    -- Hand cards
    local hand = {}
    if G.hand and G.hand.cards then
        for i, c in ipairs(G.hand.cards) do
            local base = c.base or {}
            table.insert(hand, {
                id = base.id or 0,
                suit = base.suit or "?",
                rank = base.value or "?",
                enhancement = c.ability and c.ability.effect or "none",
                edition = c.edition and c.edition.type or "none",
                seal = c.seal or "none",
                idx = i,
            })
        end
    end
    
    -- Enumerate top plays
    local top_plays = {}
    if G.hand and G.hand.cards and #G.hand.cards > 0 then
        local all_plays = enumerate_plays(G.hand.cards)
        for i = 1, math.min(10, #all_plays) do
            local p = all_plays[i]
            table.insert(top_plays, {
                indices = p.indices,
                score = p.score,
                hand_name = p.hand_name,
            })
        end
    end
    
    -- Jokers
    local jokers = {}
    if G.jokers and G.jokers.cards then
        for i, j in ipairs(G.jokers.cards) do
            local ab = j.ability or {}
            table.insert(jokers, {
                name = j.label or ab.name or "Unknown",
                sell_value = j.sell_cost or 0,
                rarity = ab.rarity or 1,
                effect = ab.effect or "none",
                idx = i,
            })
        end
    end
    
    -- Consumables
    local consumables = {}
    if G.consumeables and G.consumeables.cards then
        for i, c in ipairs(G.consumeables.cards) do
            table.insert(consumables, {
                name = c.label or (c.ability and c.ability.name) or "Unknown",
                type = c.ability and c.ability.set or "Unknown",
                idx = i,
            })
        end
    end
    
    -- Hand type levels
    local hand_levels = {}
    if game.hands then
        for name, data in pairs(game.hands) do
            hand_levels[name] = {
                level = data.level or 1,
                chips = data.chips or 0,
                mult = data.mult or 0,
                played = data.played or 0,
            }
        end
    end
    
    -- Best play score for reward calculation
    local best_play_score = 0
    if #top_plays > 0 then
        best_play_score = top_plays[1].score
    end
    
    local state = {
        event = event_name,
        timestamp = os.clock(),
        seed = game.pseudorandom and game.pseudorandom.seed or "unknown",
        
        -- Round info
        ante = rr.ante or 1,
        round = game.round or 0,
        blind_name = blind.name or "Unknown",
        score_target = blind.chips or 300,
        current_score = game.chips or 0,
        
        -- Resources
        hands_left = round.hands_left or 0,
        discards_left = round.discards_left or 0,
        money = game.dollars or 0,
        
        -- Cards
        hand = hand,
        top_plays = top_plays,
        best_play_score = best_play_score,
        
        -- Jokers & consumables
        jokers = jokers,
        consumables = consumables,
        
        -- Meta
        joker_slots = game.joker_slots or 5,
        consumable_slots = game.consumeable_slots or 2,
        deck_remaining = G.deck and G.deck.cards and #G.deck.cards or 0,
        
        -- Hand levels
        hand_levels = hand_levels,
        
        -- Last hand result
        last_hand_type = game.last_hand_played or "none",
        
        -- Instance ID for parallel training
        instance_id = INSTANCE_ID,
    }
    
    return state
end

-- ── State writer ─────────────────────────────────────────────────────────────

function BalatroRL.write(event_name)
    pcall(function()
        love.filesystem.createDirectory(STATE_DIR)
    end)
    local state = collect_state(event_name)
    if not state then return end
    local ok, encoded = pcall(json_encode, state)
    if ok then
        love.filesystem.write(STATE_FILE, encoded)
    end
end

-- ── Action reader & executor ─────────────────────────────────────────────────

local function json_decode_action(text)
    -- Minimal parser for {"type":"play"|"discard","cards":[...]}
    local action_type = text:match('"type"%s*:%s*"([^"]+)"')
    local cards_str = text:match('"cards"%s*:%s*%[([^%]]*)%]')
    if not action_type then return nil, nil end
    local cards = {}
    if cards_str then
        for num in cards_str:gmatch("(%d+)") do
            table.insert(cards, tonumber(num))
        end
    end
    return action_type, cards
end

local function execute_action(action_type, card_indices)
    if not G.hand or not G.hand.cards then
        BalatroRL.log("execute_action: no hand")
        return
    end
    
    -- Deselect all first
    for _, c in ipairs(G.hand.cards) do
        c.highlighted = false
    end
    G.hand:unhighlight_all()
    
    -- Select specified cards
    local selected = {}
    for _, idx in ipairs(card_indices) do
        local card = G.hand.cards[idx]
        if card then
            card.highlighted = true
            G.hand:add_to_highlighted(card)
            table.insert(selected, idx)
        end
    end
    
    BalatroRL.log("execute_action: " .. action_type .. " cards=" .. table.concat(selected, ","))
    
    -- Execute
    if action_type == "play" then
        pcall(function() G.FUNCS.play_cards_from_highlighted({}) end)
    elseif action_type == "discard" then
        pcall(function() G.FUNCS.discard_cards_from_highlighted({}) end)
    end
end

-- ── Lua navigation (headless) ────────────────────────────────────────────────

local function lua_nav_select_blind()
    if not BalatroRL.cfg().lua_nav then return end
    pcall(function()
        local S = G.STATES
        if G.STATE == S.BLIND_SELECT then
            -- Find and click the select button for current blind
            if G.blind_select_opts then
                for _, opt in ipairs(G.blind_select_opts) do
                    if opt.cards and #opt.cards > 0 then
                        local btn = opt.cards[1]
                        if btn and btn.children and btn.children.select_button then
                            local sel = btn.children.select_button
                            if sel and sel.config and sel.config.button then
                                G.FUNCS[sel.config.button](sel)
                                return
                            end
                        end
                    end
                end
            end
            -- Fallback: simulate selecting first available
            if G.GAME.round_resets and G.GAME.round_resets.blind_choices then
                local bc = G.GAME.round_resets.blind_choices
                local choice = bc.Small or bc.Big or bc.Boss
                if choice then
                    G.FUNCS.select_blind({ config = { id = choice } })
                end
            end
        end
    end)
end

local function lua_nav_cash_out()
    if not BalatroRL.cfg().lua_nav then return end
    pcall(function()
        if G.STATE == G.STATES.ROUND_EVAL or G.STATE == G.STATES.HAND_PLAYED then
            if G.buttons and G.buttons.cards then
                for _, btn in ipairs(G.buttons.cards) do
                    if btn.config and btn.config.button == "cash_out" then
                        G.FUNCS.cash_out(btn)
                        return
                    end
                end
            end
            -- Direct approach
            pcall(G.FUNCS.cash_out, {})
        end
    end)
end

local function lua_nav_handle_shop()
    if not BalatroRL.cfg().lua_nav then return end
    pcall(function()
        if G.STATE ~= G.STATES.SHOP then return end
        
        -- Auto-buy jokers if enabled and we have money
        if BalatroRL.cfg().buy_jokers and G.shop_jokers and G.shop_jokers.cards then
            local bought = false
            for _, card in ipairs(G.shop_jokers.cards) do
                if card.cost and G.GAME.dollars >= card.cost then
                    if G.jokers and #G.jokers.cards < (G.GAME.joker_slots or 5) then
                        pcall(function()
                            G.FUNCS.buy_from_shop({ config = { ref_table = card } })
                        end)
                        bought = true
                        break
                    end
                end
            end
            if bought then return end
        end
        
        -- Leave shop
        pcall(G.FUNCS.toggle_shop, { config = {} })
    end)
end

local function lua_nav_end_round()
    if not BalatroRL.cfg().lua_nav then return end
    pcall(function()
        if G.STATE == G.STATES.ROUND_EVAL then
            lua_nav_cash_out()
        end
    end)
end

local function lua_nav_handle_game_over()
    if not BalatroRL.cfg().lua_nav then return end
    pcall(function()
        if G.STATE == G.STATES.GAME_OVER then
            BalatroRL.log("lua_nav: game_over detected, starting new run")
            pcall(G.FUNCS.start_run, nil, { stake = 1 })
        end
    end)
end

-- ── State machine (navigation hook) ──────────────────────────────────────────

local last_nav_state = nil
local nav_cooldown = 0

local function navigation_tick()
    if not BalatroRL.cfg().lua_nav then return end
    if not G or not G.STATE then return end
    
    nav_cooldown = nav_cooldown - 1
    if nav_cooldown > 0 then return end
    
    local S = G.STATES
    local current = G.STATE
    
    if current == S.BLIND_SELECT then
        lua_nav_select_blind()
        nav_cooldown = 3
    elseif current == S.SHOP then
        lua_nav_handle_shop()
        nav_cooldown = 2
    elseif current == S.ROUND_EVAL then
        lua_nav_end_round()
        nav_cooldown = 2
    elseif current == S.GAME_OVER then
        lua_nav_handle_game_over()
        nav_cooldown = 5
    end
    
    last_nav_state = current
end

-- ── Main update hook ─────────────────────────────────────────────────────────

local POLL_INTERVAL = 0.05  -- 50ms for faster game speeds (64x+)
local poll_timer    = 0
local last_G_STATE  = nil

local orig_game_update = Game.update
Game.update = function(self, dt)
    -- Wrap in pcall to handle round_eval nil crashes during transitions
    local ok, err = pcall(orig_game_update, self, dt)
    if not ok then
        if BalatroRL.cfg().debug_log then
            BalatroRL.log("Game.update error (recovering): " .. tostring(err))
        end
        return
    end
    poll_timer = poll_timer + dt
    if poll_timer < POLL_INTERVAL then return end
    poll_timer = 0
    if not G then return end

    -- Navigation
    navigation_tick()

    -- Write state on every screen transition so Python knows what to do
    if G.STATE ~= last_G_STATE then
        local prev = last_G_STATE
        last_G_STATE = G.STATE
        local S = G.STATES
        local event_name = "state_change"
        if     G.STATE == S.SELECTING_HAND then event_name = "selecting_hand"
        elseif G.STATE == S.HAND_PLAYED    then event_name = "hand_played"
        elseif G.STATE == S.DRAW_TO_HAND   then event_name = "draw_to_hand"
        elseif G.STATE == S.GAME_OVER      then event_name = "game_over"
        elseif G.STATE == S.SHOP           then event_name = "shop"
        elseif G.STATE == S.BLIND_SELECT   then event_name = "blind_select"
        elseif G.STATE == S.ROUND_EVAL     then event_name = "round_eval"
        end
        BalatroRL.write(event_name)
        BalatroRL.log("state: " .. tostring(prev) .. " -> " .. tostring(G.STATE) .. " (" .. event_name .. ")")
    end
    
    -- Also write on SELECTING_HAND even if state didn't change (hand updates)
    if G.STATE == G.STATES.SELECTING_HAND then
        BalatroRL.write("selecting_hand")
    elseif G.STATE == G.STATES.SHOP then
        BalatroRL.write("shop")
    elseif G.STATE == G.STATES.BLIND_SELECT then
        BalatroRL.write("blind_select")
    elseif G.STATE == G.STATES.ROUND_EVAL then
        BalatroRL.write("round_eval")
    elseif G.STATE == G.STATES.SELECTING_HAND then
        BalatroRL.write("selecting_hand")
    end

    -- Action polling
    pcall(function()
        if not love.filesystem.getInfo(ACTION_FILE) then return end
        local text = love.filesystem.read(ACTION_FILE)
        if not text or text == "" then return end
        love.filesystem.remove(ACTION_FILE)
        local action_type, card_indices = json_decode_action(text)
        if not action_type then return end
        love.filesystem.append(LOG_FILE, os.time().." action="..action_type.."\n")
        if action_type == "leave_shop" then
            pcall(G.FUNCS.toggle_shop, {config = {}})
        elseif action_type == "new_run" then
            local nr_ante = G.GAME and G.GAME.round_resets and G.GAME.round_resets.ante or "?"
            love.filesystem.append(LOG_FILE, os.time()
                .. " lua_nav: new_run forced by Python ante=" .. tostring(nr_ante) .. "\n")
            pcall(G.FUNCS.start_run, nil, {stake = 1})
        else
            execute_action(action_type, card_indices)
        end
    end)
end

BalatroRL.write("mod_loaded")

-- Set custom game speed if configured (requires Handy mod)
if CUSTOM_GAME_SPEED and CUSTOM_GAME_SPEED > 0 then
    local function set_custom_speed()
        if Handy and Handy.speed_multiplier then
            Handy.speed_multiplier.value = CUSTOM_GAME_SPEED
            Handy.speed_multiplier.localize_value()
            love.filesystem.append(LOG_FILE, os.time() .. " Custom speed set: " .. CUSTOM_GAME_SPEED .. "x\n")
        end
    end
    pcall(set_custom_speed)
    local orig_start_run = G.FUNCS.start_run
    G.FUNCS.start_run = function(...)
        pcall(set_custom_speed)
        return orig_start_run(...)
    end
end

-- ═══════════════════════════════════════════════════════════════════════════
-- MINIMAL GRAPHICS MODE
-- ═══════════════════════════════════════════════════════════════════════════

local frame_counter = 0
local activity_timer = 0

local orig_love_draw = love.draw
love.draw = function()
    if not MINIMAL_GRAPHICS then
        if orig_love_draw then orig_love_draw() end
        return
    end
    
    -- Minimal HUD mode
    love.graphics.clear(0.05, 0.05, 0.08, 1)
    love.graphics.setColor(1, 1, 1, 1)
    
    local y = 20
    local x = 20
    local line_height = 24
    
    -- Title with instance ID
    love.graphics.setColor(0.4, 0.8, 1, 1)
    love.graphics.print("BALATRO RL - INSTANCE " .. INSTANCE_ID, x, y)
    y = y + line_height * 1.5
    
    if not G or not G.GAME then
        love.graphics.setColor(1, 1, 0, 1)
        love.graphics.print("Waiting for game...", x, y)
        return
    end
    
    local game = G.GAME
    local round_resets = game.round_resets or {}
    
    -- Ante & Blind
    love.graphics.setColor(1, 0.9, 0.3, 1)
    local ante = round_resets.ante or 1
    local blind_name = game.blind and game.blind.name or "Unknown"
    love.graphics.print(string.format("ANTE %d  |  %s", ante, blind_name), x, y)
    y = y + line_height * 1.5
    
    -- Score
    love.graphics.setColor(0.3, 1, 0.5, 1)
    local score = game.chips or 0
    local target = game.blind and game.blind.chips or 1
    local progress = math.min(score / target, 1) * 100
    
    local function fmt(n)
        if n >= 1e9 then return string.format("%.1fB", n/1e9)
        elseif n >= 1e6 then return string.format("%.1fM", n/1e6)
        elseif n >= 1e3 then return string.format("%.1fK", n/1e3)
        else return string.format("%.0f", n) end
    end
    
    love.graphics.print(string.format("SCORE: %s / %s  (%.0f%%)", 
        fmt(score), fmt(target), progress), x, y)
    y = y + line_height
    
    -- Progress bar
    local bar_width = 300
    local bar_height = 16
    love.graphics.setColor(0.2, 0.2, 0.2, 1)
    love.graphics.rectangle("fill", x, y, bar_width, bar_height)
    love.graphics.setColor(0.3, 1, 0.5, 1)
    love.graphics.rectangle("fill", x, y, bar_width * math.min(score / target, 1), bar_height)
    y = y + line_height * 1.5
    
    -- Hands & Discards
    love.graphics.setColor(0.7, 0.7, 1, 1)
    local hands = game.current_round and game.current_round.hands_left or 0
    local discards = game.current_round and game.current_round.discards_left or 0
    love.graphics.print(string.format("HANDS: %d  |  DISCARDS: %d", hands, discards), x, y)
    y = y + line_height * 1.5
    
    -- State
    love.graphics.setColor(0.6, 0.6, 0.6, 1)
    local state_name = "UNKNOWN"
    if G.STATE and G.STATES then
        for name, val in pairs(G.STATES) do
            if G.STATE == val then state_name = name break end
        end
    end
    love.graphics.print(string.format("STATE: %s", state_name), x, y)
    y = y + line_height
    
    -- Money & Jokers
    love.graphics.setColor(1, 0.8, 0.2, 1)
    local money = game.dollars or 0
    local joker_count = G.jokers and G.jokers.cards and #G.jokers.cards or 0
    love.graphics.print(string.format("$%d  |  JOKERS: %d", money, joker_count), x, y)
    y = y + line_height * 2
    
    -- Activity indicator
    frame_counter = frame_counter + 1
    activity_timer = activity_timer + (love.timer.getDelta() or 0.016)
    
    local cycle_pos = (activity_timer % 2) / 2
    
    love.graphics.setColor(0.2, 0.2, 0.2, 1)
    love.graphics.rectangle("fill", x, y, 200, 8)
    
    local segment_width = 40
    local segment_x = x + (200 - segment_width) * cycle_pos
    love.graphics.setColor(0, 1, 0.5, 1)
    love.graphics.rectangle("fill", segment_x, y, segment_width, 8)
    
    y = y + line_height
    
    love.graphics.setColor(0.4, 0.4, 0.4, 1)
    local uptime_min = math.floor(activity_timer / 60)
    local uptime_sec = math.floor(activity_timer % 60)
    love.graphics.print(string.format("FRAME: %d  |  UPTIME: %d:%02d", 
        frame_counter, uptime_min, uptime_sec), x, y)
end
