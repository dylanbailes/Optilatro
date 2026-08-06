-- BalatroRL.lua
-- Writes state.json on state changes. Executes card play/discard from action.json.
-- Navigation modes: Lua (headless) or Python/pyautogui (mouse). Toggle in mod config.

-- ═══════════════════════════════════════════════════════════════════════════
-- CUSTOM GAME SPEED (requires Handy mod)
-- Set to nil to use Handy's default, or a number for custom speed (e.g., 100)
-- ═══════════════════════════════════════════════════════════════════════════
local CUSTOM_GAME_SPEED = 100  -- Set custom speed (nil = use Handy default)

BalatroRL = {}

local STATE_DIR  = "balatro_rl"
local STATE_FILE = STATE_DIR .. "/state.json"
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
        for k,_ in pairs(val) do
            if type(k)~="number" or k~=math.floor(k) or k<1 then is_array=false; break end
            if k>max_i then max_i=k end
        end
        is_array = is_array and (max_i == #val)
        if is_array then
            local parts = {}
            for i=1,#val do parts[i]=json_encode(val[i],depth+1) end
            return "["..table.concat(parts,",").."]"
        else
            local parts = {}
            for k,v in pairs(val) do
                if type(k)=="string" then
                    table.insert(parts, json_str(k)..":"..json_encode(v,depth+1))
                end
            end
            return "{"..table.concat(parts,",").."}"
        end
    end
    return "null"
end

-- ── State capture helpers ─────────────────────────────────────────────────────

local function card_info(card)
    if not card or not card.base then return nil end
    local base = card.base
    return {
        rank        = base.value  or "none",
        suit        = base.suit   or "none",
        rank_id     = base.id     or 0,
        suit_id     = base.suit_id or 0,
        enhancement = (card.config and card.config.center and card.config.center.key) or "none",
        seal        = (card.seal  or "none"),
        edition     = (card.edition and card.edition.type) or "none",
        highlighted = card.highlighted or false,
        debuff      = card.debuff or false,  -- Boss blind debuffs (The Goad, The Plant, etc.)
    }
end

local function joker_info(joker)
    if not joker or not joker.config then return nil end
    local cfg = joker.config.center or {}
    local ab = joker.ability or {}
    -- extra_val captures runtime state for dynamic jokers (Ice Cream, Green Joker, etc.)
    local extra_val = 0
    if type(ab.extra) == "number" then
        extra_val = ab.extra
    elseif type(ab.extra) == "table" then
        extra_val = ab.extra.chips or ab.extra.mult or ab.extra.money or 0
    end
    return {
        name      = cfg.name or "unknown",
        key       = cfg.key  or "unknown",
        rarity    = cfg.rarity or 0,
        cost      = joker.cost or 0,
        mult      = ab.mult or 0,
        chips     = ab.t_chips or ab.chips or 0,
        extra_val = extra_val,
    }
end

local HAND_NAMES = {
    "High Card","Pair","Two Pair","Three of a Kind","Straight",
    "Flush","Full House","Four of a Kind","Straight Flush",
    "Five of a Kind","Flush House","Flush Five"
}

local function hand_levels()
    local levels = {}
    if not (G and G.GAME and G.GAME.hands) then return levels end
    for _, name in ipairs(HAND_NAMES) do
        local h = G.GAME.hands[name]
        if h then
            table.insert(levels, {name=name, level=h.level or 1, mult=h.mult or 1, chips=h.chips or 0})
        end
    end
    return levels
end

local function shop_info()
    local items = {}
    if not (G and G.shop_jokers and G.shop_jokers.cards) then return items end
    for _, card in ipairs(G.shop_jokers.cards) do
        local cfg = card.config and card.config.center or {}
        table.insert(items, {name=cfg.name or "unknown", key=cfg.key or "unknown", cost=card.cost or 0})
    end
    return items
end

-- ══════════════════════════════════════════════════════════════════════════════
-- V2: Hand Enumeration, Evaluation, and Score Estimation
-- ══════════════════════════════════════════════════════════════════════════════

-- Hand type IDs (for observation vector)
local HAND_TYPE_ID = {
    ["High Card"]=0, ["Pair"]=1, ["Two Pair"]=2, ["Three of a Kind"]=3,
    ["Straight"]=4, ["Flush"]=5, ["Full House"]=6, ["Four of a Kind"]=7,
    ["Straight Flush"]=8, ["Five of a Kind"]=9, ["Flush House"]=10, ["Flush Five"]=11
}

-- Generate all k-combinations from indices 1..n
local function combinations(n, k)
    local result = {}
    local combo = {}
    local function recurse(start, depth)
        if depth > k then
            local copy = {}
            for i=1,k do copy[i] = combo[i] end
            table.insert(result, copy)
            return
        end
        for i = start, n - (k - depth) do
            combo[depth] = i
            recurse(i + 1, depth + 1)
        end
    end
    recurse(1, 1)
    return result
end

-- Count occurrences of each rank (1-14) and suit (1-4) in a set of cards
local function count_ranks_suits(cards)
    local ranks, suits = {}, {}
    for i=1,14 do ranks[i] = 0 end
    for i=1,4  do suits[i] = 0 end
    for _, c in ipairs(cards) do
        local r = c.rank_id or 0
        local s = c.suit_id or 0
        if r >= 1 and r <= 14 then ranks[r] = ranks[r] + 1 end
        if s >= 1 and s <= 4  then suits[s] = suits[s] + 1 end
    end
    return ranks, suits
end

-- Check if cards form a straight (5 consecutive ranks, Ace can be low or high)
local function is_straight(ranks)
    local sorted = {}
    for r=1,14 do
        if ranks[r] > 0 then table.insert(sorted, r) end
    end
    if #sorted < 5 then return false end
    table.sort(sorted)
    -- Check normal straight
    local consecutive = 1
    for i=2,#sorted do
        if sorted[i] == sorted[i-1] + 1 then
            consecutive = consecutive + 1
            if consecutive >= 5 then return true end
        else
            consecutive = 1
        end
    end
    -- Check wheel (A-2-3-4-5): Ace=14, 2=2, 3=3, 4=4, 5=5
    if ranks[14] > 0 and ranks[2] > 0 and ranks[3] > 0 and ranks[4] > 0 and ranks[5] > 0 then
        return true
    end
    return false
end

-- Evaluate hand type for a set of 1-5 cards
local function evaluate_hand_type(cards)
    local n = #cards
    if n == 0 then return "High Card", 0 end
    
    local ranks, suits = count_ranks_suits(cards)
    
    -- Count rank frequencies
    local freq = {}
    for r=1,14 do
        local c = ranks[r]
        if c > 0 then
            freq[c] = (freq[c] or 0) + 1
        end
    end
    
    -- Check flush (all same suit)
    local is_flush = false
    for s=1,4 do
        if suits[s] == n and n >= 5 then is_flush = true; break end
    end
    
    -- Check straight
    local is_str = (n >= 5) and is_straight(ranks)
    
    -- Five of a Kind
    if freq[5] then
        if is_flush then return "Flush Five", 11 end
        return "Five of a Kind", 9
    end
    
    -- Four of a Kind
    if freq[4] then
        return "Four of a Kind", 7
    end
    
    -- Full House or Flush House
    if freq[3] and freq[2] then
        if is_flush then return "Flush House", 10 end
        return "Full House", 6
    end
    
    -- Straight Flush
    if is_str and is_flush then
        return "Straight Flush", 8
    end
    
    -- Flush
    if is_flush then
        return "Flush", 5
    end
    
    -- Straight
    if is_str then
        return "Straight", 4
    end
    
    -- Three of a Kind
    if freq[3] then
        return "Three of a Kind", 3
    end
    
    -- Two Pair
    if freq[2] and freq[2] >= 2 then
        return "Two Pair", 2
    end
    
    -- Pair
    if freq[2] then
        return "Pair", 1
    end
    
    return "High Card", 0
end

-- Get base chips and mult for a hand type from current game state
local function get_hand_base(hand_name)
    if not (G and G.GAME and G.GAME.hands) then
        -- Fallback defaults
        local defaults = {
            ["High Card"]={5,1}, ["Pair"]={10,2}, ["Two Pair"]={20,2},
            ["Three of a Kind"]={30,3}, ["Straight"]={30,4}, ["Flush"]={35,4},
            ["Full House"]={40,4}, ["Four of a Kind"]={60,7}, ["Straight Flush"]={100,8},
            ["Five of a Kind"]={120,12}, ["Flush House"]={140,14}, ["Flush Five"]={160,16}
        }
        local d = defaults[hand_name] or {5,1}
        return d[1], d[2]
    end
    local h = G.GAME.hands[hand_name]
    if h then
        return h.chips or 5, h.mult or 1
    end
    return 5, 1
end

-- Estimate joker bonuses for a given hand
-- Returns (bonus_chips, bonus_mult, mult_multiplier)
local function estimate_joker_bonus(cards, hand_name, jokers)
    local bonus_chips = 0
    local bonus_mult = 0
    local mult_mult = 1.0  -- multiplicative mult (e.g., ×1.5)
    
    if not jokers then return bonus_chips, bonus_mult, mult_mult end
    
    -- Count suits in hand for suit-gated jokers
    local _, suits = count_ranks_suits(cards)
    local has_heart   = suits[1] and suits[1] > 0
    local has_diamond = suits[2] and suits[2] > 0
    local has_spade   = suits[3] and suits[3] > 0
    local has_club    = suits[4] and suits[4] > 0
    
    local n_cards = #cards
    local n_jokers = #jokers
    
    for _, j in ipairs(jokers) do
        local key = j.key or ""
        local mult = j.mult or 0
        local chips = j.chips or 0
        local extra = j.extra_val or 0
        
        -- Universal mult/chip adders
        if key == "j_joker" then bonus_mult = bonus_mult + 4
        elseif key == "j_greedy_joker" and has_diamond then bonus_mult = bonus_mult + 4
        elseif key == "j_lusty_joker"  and has_heart   then bonus_mult = bonus_mult + 4
        elseif key == "j_wrathful_joker" and has_spade then bonus_mult = bonus_mult + 4
        elseif key == "j_gluttenous_joker" and has_club then bonus_mult = bonus_mult + 4
        
        -- Hand-type gated jokers
        elseif key == "j_jolly" and (hand_name == "Pair" or hand_name == "Two Pair" or hand_name == "Full House") then
            bonus_mult = bonus_mult + 8
        elseif key == "j_zany" and (hand_name == "Two Pair" or hand_name == "Full House") then
            bonus_mult = bonus_mult + 12
        elseif key == "j_mad" and (hand_name == "Three of a Kind" or hand_name == "Full House" or hand_name == "Four of a Kind") then
            bonus_mult = bonus_mult + 10
        elseif key == "j_crazy" and (hand_name == "Straight" or hand_name == "Straight Flush") then
            bonus_mult = bonus_mult + 12
        elseif key == "j_droll" and (hand_name == "Flush" or hand_name == "Straight Flush" or hand_name == "Flush House" or hand_name == "Flush Five") then
            bonus_mult = bonus_mult + 10
        
        -- Chip adders by hand type
        elseif key == "j_sly" and (hand_name == "Pair" or hand_name == "Two Pair" or hand_name == "Full House") then
            bonus_chips = bonus_chips + 50
        elseif key == "j_wily" and (hand_name == "Three of a Kind" or hand_name == "Full House" or hand_name == "Four of a Kind") then
            bonus_chips = bonus_chips + 100
        elseif key == "j_clever" and (hand_name == "Two Pair" or hand_name == "Full House") then
            bonus_chips = bonus_chips + 80
        elseif key == "j_devious" and (hand_name == "Straight" or hand_name == "Straight Flush") then
            bonus_chips = bonus_chips + 100
        elseif key == "j_crafty" and (hand_name == "Flush" or hand_name == "Straight Flush" or hand_name == "Flush House" or hand_name == "Flush Five") then
            bonus_chips = bonus_chips + 80
        
        -- Size-gated
        elseif key == "j_half" and n_cards <= 3 then
            bonus_mult = bonus_mult + 20
        
        -- Scaling jokers
        elseif key == "j_abstract" then
            bonus_mult = bonus_mult + (3 * n_jokers)
        elseif key == "j_blue_joker" then
            local deck_size = G.deck and #G.deck.cards or 40
            bonus_chips = bonus_chips + (2 * deck_size)
        
        -- Dynamic jokers (use extra_val which has runtime state)
        elseif key == "j_ice_cream" then
            bonus_chips = bonus_chips + extra  -- extra.chips decreases each round
        elseif key == "j_green_joker" then
            bonus_mult = bonus_mult + mult    -- ability.mult is updated by game
        elseif key == "j_ride_the_bus" then
            bonus_mult = bonus_mult + extra   -- extra.mult from consecutive face card streak
        
        -- Mult multipliers
        elseif key == "j_steel_joker" then
            -- +0.2x mult per Steel card in full deck (estimate)
            mult_mult = mult_mult * 1.2
        
        -- Generic fallback: use the joker's base mult/chips if we don't recognize it
        else
            bonus_mult = bonus_mult + mult
            bonus_chips = bonus_chips + chips
        end
    end
    
    return bonus_chips, bonus_mult, mult_mult
end

-- Estimate total score for a hand: (base_chips + bonus_chips + card_chips) * (base_mult + bonus_mult) * mult_mult
local function estimate_score(cards, hand_name, jokers)
    local base_chips, base_mult = get_hand_base(hand_name)
    local bonus_chips, bonus_mult, mult_mult = estimate_joker_bonus(cards, hand_name, jokers)
    
    -- Card chip values (sum of rank values for scoring cards)
    -- Skip debuffed cards (boss blinds like The Goad, The Plant, etc.)
    local card_chips = 0
    local scoring_cards = 0
    for _, c in ipairs(cards) do
        if not c.debuff then
            scoring_cards = scoring_cards + 1
            local r = c.rank_id or 0
            if r >= 2 and r <= 10 then
                card_chips = card_chips + r
            elseif r >= 11 and r <= 13 then  -- J/Q/K
                card_chips = card_chips + 10
            elseif r == 14 then  -- Ace
                card_chips = card_chips + 11
            end
        end
    end
    
    -- If all cards debuffed, hand scores nothing
    if scoring_cards == 0 then
        return 0
    end
    
    local total_chips = base_chips + bonus_chips + card_chips
    local total_mult = base_mult + bonus_mult
    
    return math.floor(total_chips * total_mult * mult_mult)
end

-- Generate and rank all play options (1-5 cards)
-- Returns top 10 plays sorted by estimated score descending
local function rank_plays(hand_cards, jokers)
    local n = #hand_cards
    if n == 0 then return {} end
    
    local plays = {}
    
    -- Generate all combinations of 1-5 cards
    for k = 1, math.min(5, n) do
        local combos = combinations(n, k)
        for _, indices in ipairs(combos) do
            local cards = {}
            for _, idx in ipairs(indices) do
                table.insert(cards, hand_cards[idx])
            end
            local hand_name, hand_type_id = evaluate_hand_type(cards)
            local score = estimate_score(cards, hand_name, jokers)
            table.insert(plays, {
                indices = indices,
                hand_type = hand_name,
                hand_type_id = hand_type_id,
                n_cards = k,
                score = score,
            })
        end
    end
    
    -- Sort by score descending
    table.sort(plays, function(a,b) return a.score > b.score end)
    
    -- Return top 10
    local result = {}
    for i = 1, math.min(10, #plays) do
        result[i] = plays[i]
    end
    return result
end

-- Generate discard options: 8 single-card + 2 multi-card
-- Option A: each of the 8 cards as individual discards, plus 2 lowest-rank pairs
local function enumerate_discards(hand_cards)
    local n = #hand_cards
    if n == 0 then return {} end
    
    local options = {}
    
    -- 8 single-card discards (one per card slot)
    for i = 1, math.min(8, n) do
        table.insert(options, {
            indices = {i},
            n_cards = 1,
        })
    end
    
    -- 2 multi-card options: discard 2 lowest-ranked cards
    if n >= 2 then
        -- Sort cards by rank (ascending) to find lowest
        local sorted = {}
        for i = 1, n do
            table.insert(sorted, {idx = i, rank = hand_cards[i].rank_id or 0})
        end
        table.sort(sorted, function(a,b) return a.rank < b.rank end)
        
        -- Discard 2 lowest
        table.insert(options, {
            indices = {sorted[1].idx, sorted[2].idx},
            n_cards = 2,
        })
        
        -- Discard 3 lowest (if available)
        if n >= 3 then
            table.insert(options, {
                indices = {sorted[1].idx, sorted[2].idx, sorted[3].idx},
                n_cards = 3,
            })
        end
    end
    
    return options
end

-- Get deck composition: count of each rank (1-13) and suit (1-4) remaining in deck
local function get_deck_composition()
    local ranks = {}
    local suits = {}
    for i=1,13 do ranks[i] = 0 end
    for i=1,4  do suits[i] = 0 end
    
    if G and G.deck and G.deck.cards then
        for _, card in ipairs(G.deck.cards) do
            if card.base then
                local r = card.base.id or 0
                local s = card.base.suit_id or 0
                -- Map rank_id to 1-13 (Ace=1, 2=2, ..., K=13)
                if r == 14 then r = 1 end  -- Ace
                if r >= 1 and r <= 13 then ranks[r] = ranks[r] + 1 end
                if s >= 1 and s <= 4  then suits[s] = suits[s] + 1 end
            end
        end
    end
    
    return ranks, suits
end

-- V2: compute all play/discard options and add to state
function BalatroRL.compute_v2_options(state)
    -- Only compute during hand selection
    if not (G and G.hand and G.hand.cards and #G.hand.cards > 0) then
        state.play_options = {}
        state.discard_options = {}
        state.best_play_score = 0
        state.deck_ranks = {}
        state.deck_suits = {}
        return
    end
    
    -- Build card info list for hand
    local hand_cards = {}
    for _, card in ipairs(G.hand.cards) do
        local c = card_info(card)
        if c then table.insert(hand_cards, c) end
    end
    
    -- Get joker info
    local jokers = {}
    if G.jokers and G.jokers.cards then
        for _, joker in ipairs(G.jokers.cards) do
            local j = joker_info(joker)
            if j then table.insert(jokers, j) end
        end
    end
    
    -- Compute play options
    local play_opts = rank_plays(hand_cards, jokers)
    state.play_options = play_opts
    
    -- Best play score (for discard reward signal)
    state.best_play_score = (play_opts[1] and play_opts[1].score) or 0
    
    -- Compute discard options
    state.discard_options = enumerate_discards(hand_cards)
    
    -- Deck composition
    local deck_ranks, deck_suits = get_deck_composition()
    state.deck_ranks = deck_ranks
    state.deck_suits = deck_suits
end

-- ── State capture ─────────────────────────────────────────────────────────────

function BalatroRL.cfg()
    -- SMODS.Mods is safe to access at runtime (after all mods loaded)
    local c = SMODS.Mods and SMODS.Mods["BalatroRL"] and SMODS.Mods["BalatroRL"].config or {}
    return {
        lua_nav    = c.lua_nav    ~= false,   -- default true
        buy_jokers = c.buy_jokers ~= false,   -- default true
        debug_log  = c.debug_log  == true,    -- default false
    }
end

function BalatroRL.capture(event)
    if not G or not G.GAME then return nil end
    local game  = G.GAME
    local round = game.current_round or {}
    local blind = game.blind or {}
    local state = {
        event          = event or "unknown",
        phase          = G.STAGE  or "unknown",
        game_state     = G.STATE  or 0,
        timestamp      = os.time(),
        tick           = love.timer.getTime(),
        seed           = game.seed or "unknown",
        ante           = (game.round_resets and game.round_resets.ante) or 0,
        round          = game.round or 0,
        -- Derive blind name from round position if not boss (G.GAME.blind persists boss name)
        blind_name     = (function()
            if blind.boss then return blind.name or "Boss Blind" end
            local r = (game.round or 0) % 3
            if r == 0 then return "Small Blind"
            elseif r == 1 then return "Big Blind"
            else return blind.name or "Boss Blind" end
        end)(),
        blind_chips    = blind.chips or 0,
        blind_boss     = blind.boss  or false,
        hands_left     = round.hands_left    or 0,
        discards_left  = round.discards_left or 0,
        money          = game.dollars        or 0,
        joker_slots    = game.joker_limit    or 5,
        current_score  = game.chips or 0,   -- accumulated blind chips (G.GAME.chips), resets each blind
        score_target   = blind.chips or 0,
        hand           = {},
        jokers         = {},
        deck_remaining = G.deck    and #G.deck.cards    or 0,
        discard_count  = G.discard and #G.discard.cards or 0,
        shop           = {},
        hand_levels    = hand_levels(),
        last_hand_type = (BalatroRL._last_played_hand or round.most_played_poker_hand) or "unknown",
    }
    if G.hand and G.hand.cards then
        for _, card in ipairs(G.hand.cards) do
            local c = card_info(card); if c then table.insert(state.hand, c) end
        end
    end
    if G.jokers and G.jokers.cards then
        for _, joker in ipairs(G.jokers.cards) do
            local j = joker_info(joker); if j then table.insert(state.jokers, j) end
        end
    end
    state.shop = shop_info()
    return state
end

-- ── File I/O ──────────────────────────────────────────────────────────────────

function BalatroRL.write(event)
    local ok, err = pcall(function()
        love.filesystem.createDirectory(STATE_DIR)
        local state = BalatroRL.capture(event)
        if state then
            state.config = BalatroRL.cfg()   -- expose config flags to Python
            BalatroRL.compute_v2_options(state)  -- V2: add play/discard options + deck composition
            love.filesystem.write(STATE_FILE, json_encode(state))
        end
    end)
    if not ok then
        pcall(function()
            love.filesystem.createDirectory(STATE_DIR)
            love.filesystem.append(LOG_FILE, tostring(err).."\n")
        end)
    end
end

function BalatroRL.log(msg)
    if BalatroRL.cfg().debug_log then
        pcall(function()
            love.filesystem.createDirectory(STATE_DIR)
            love.filesystem.append(LOG_FILE, os.time() .. " " .. tostring(msg) .. "\n")
        end)
    end
end

-- ── Hook game events ──────────────────────────────────────────────────────────

local function hook(fn_name, label)
    local orig = G.FUNCS[fn_name]
    if not orig then return end
    G.FUNCS[fn_name] = function(e) orig(e); BalatroRL.write(label) end
end

local _orig_play = G.FUNCS.play_cards_from_highlighted
if _orig_play then
    G.FUNCS.play_cards_from_highlighted = function(e)
        _orig_play(e)
        -- Capture last played hand type from current_round after scoring
        local rr = G.GAME and G.GAME.current_round
        if rr and rr.current_hand and rr.current_hand.hand_name then
            BalatroRL._last_played_hand = rr.current_hand.hand_name
        end
        BalatroRL.write("play")
    end
end
hook("discard_cards_from_highlighted", "discard")
hook("select_blind",  "blind_selected")
hook("skip_blind",    "blind_skipped")
hook("buy_from_shop", "shop_buy")

local orig_draw = G.FUNCS.draw_from_deck_to_hand
if orig_draw then
    G.FUNCS.draw_from_deck_to_hand = function(e)
        orig_draw(e); BalatroRL.write("hand_drawn")
    end
end

-- ── Card action execution ─────────────────────────────────────────────────────

local ACTION_FILE = STATE_DIR .. "/action.json"

local function json_decode_action(text)
    local action_type = text:match('"action"%s*:%s*"(%a+)"')
    local indices = {}
    local idx_block = text:match('"card_indices"%s*:%s*%[([^%]]*)%]')
    if idx_block then
        for n in idx_block:gmatch("(%d+)") do
            table.insert(indices, tonumber(n) + 1)
        end
    end
    return action_type, indices
end

local function execute_action(action_type, card_indices)
    if not (G and G.hand and G.hand.cards) then return end
    if #G.hand.cards == 0 or not card_indices or #card_indices == 0 then return end
    if G.STATE ~= G.STATES.SELECTING_HAND then return end
    local round = G.GAME and G.GAME.current_round
    if action_type == "play"    and round and round.hands_left    <= 0 then return end
    if action_type == "discard" and round and round.discards_left <= 0 then return end
    for _, card in ipairs(G.hand.cards) do G.hand:remove_from_highlighted(card, true) end
    for _, idx in ipairs(card_indices) do
        local card = G.hand.cards[idx]
        if card and G.hand:can_highlight(card) then G.hand:add_to_highlighted(card, true) end
    end
    if action_type == "play" then
        G.E_MANAGER:add_event(Event({func=function()
            G.FUNCS.play_cards_from_highlighted({config={object=G.play}}); return true
        end}))
    elseif action_type == "discard" then
        G.E_MANAGER:add_event(Event({func=function()
            G.FUNCS.discard_cards_from_highlighted({config={object=G.play}}); return true
        end}))
    end
end

-- ── Game.update hook ──────────────────────────────────────────────────────────

local POLL_INTERVAL = 0.05  -- 50ms for faster game speeds (64x+)
local poll_timer    = 0
local last_G_STATE  = nil

local orig_game_update = Game.update
Game.update = function(self, dt)
    -- Wrap in pcall to handle round_eval nil crashes during transitions
    local ok, err = pcall(orig_game_update, self, dt)
    if not ok then
        -- Log but don't crash; game will recover on next frame
        if BalatroRL.cfg().debug_log then
            BalatroRL.log("Game.update error (recovering): " .. tostring(err))
        end
        return
    end
    poll_timer = poll_timer + dt
    if poll_timer < POLL_INTERVAL then return end
    poll_timer = 0
    if not G then return end

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
        elseif G.STATE == S.NEW_ROUND      then event_name = "new_round"
        end
        BalatroRL.write(event_name)
        love.filesystem.append(LOG_FILE,
            os.time().." state "..tostring(prev).."->"..tostring(G.STATE).."\n")

        -- Diagnose state=-1 crash: log full context when G.STATE goes negative
        if type(G.STATE) == "number" and G.STATE < 0 then
            local rr   = G.GAME and G.GAME.round_resets or {}
            local bl   = G.GAME and G.GAME.blind or {}
            local cr   = G.GAME and G.GAME.current_round or {}
            love.filesystem.append(LOG_FILE,
                os.time() .. " [CRASH] state=-1 context:"
                .. " prev_state=" .. tostring(prev)
                .. " ante=" .. tostring(rr.ante)
                .. " bod=" .. tostring(rr.blind_on_deck)
                .. " blind=" .. tostring(bl.name)
                .. " boss=" .. tostring(bl.boss)
                .. " hands_left=" .. tostring(cr.hands_left)
                .. " discards_left=" .. tostring(cr.discards_left)
                .. " chips=" .. tostring(G.GAME and G.GAME.chips)
                .. " dollars=" .. tostring(G.GAME and G.GAME.dollars)
                .. " hook_fired=" .. tostring(BalatroRL._hook_skip_fired)
                .. " stuck_fired=" .. tostring(BalatroRL._stuck_fired)
                .. " ante_guard=" .. tostring(BalatroRL._ante_guard_fired)
                .. "\n")
        end
    end

    -- Auto-nav from main menu: fires start_run 2s after MENU loads
    -- Handles fresh Balatro launches and restarts from train.py
    if G.STATE == G.STATES.MENU then
        if not BalatroRL._menu_fire_at then
            BalatroRL._menu_fire_at = love.timer.getTime() + 2.0
            love.filesystem.append(LOG_FILE, os.time() .. " lua_nav: MENU detected — will start_run in 2s\n")
        end
        if BalatroRL._menu_fire_at and love.timer.getTime() >= BalatroRL._menu_fire_at then
            BalatroRL._menu_fire_at = nil
            local ok = pcall(G.FUNCS.start_run, nil, {stake = 1})
            love.filesystem.append(LOG_FILE, os.time() .. " lua_nav: MENU start_run " .. (ok and "OK" or "FAILED") .. "\n")
        end
    else
        BalatroRL._menu_fire_at = nil
    end

    -- Lua blind select: bypass G.FUNCS.select_blind (needs UIBox we can't easily get)
    -- Instead call new_round() directly after setting state — what select_blind does internally
    -- Lua blind select: queue events via E_MANAGER (correct way, not synchronous from update)
    -- Only runs if lua_nav is enabled in mod config
    if BalatroRL.cfg().lua_nav and G.STATE == G.STATES.BLIND_SELECT then
        -- Log every time we enter BLIND_SELECT so we can trace ante accumulation
        local rr_ante  = G.GAME and G.GAME.round_resets and G.GAME.round_resets.ante  or "?"
        local rr_round = G.GAME and G.GAME.round_resets and G.GAME.round_resets.round or "?"
        local win_ante = G.GAME and G.GAME.win_ante or "?"
        local bod_log  = G.GAME and G.GAME.blind_on_deck or "?"
        if not BalatroRL._blind_select_logged then
            BalatroRL._blind_select_logged = true
            love.filesystem.append(LOG_FILE, os.time()
                .. " BLIND_SELECT entered: rr_ante=" .. tostring(rr_ante)
                .. " rr_round=" .. tostring(rr_round)
                .. " win_ante=" .. tostring(win_ante)
                .. " bod=" .. tostring(bod_log) .. "\n")
        end
        -- Guard: don't auto-navigate past win_ante (use G.GAME.win_ante, not hardcoded 8)
        local win_ante_n = (type(win_ante) == "number") and win_ante or 8
        if type(rr_ante) == "number" and rr_ante > win_ante_n then
            if not BalatroRL._ante_guard_fired then
                BalatroRL._ante_guard_fired = true
                love.filesystem.append(LOG_FILE, os.time()
                    .. " GUARD: ante " .. tostring(rr_ante) .. " > win_ante " .. tostring(win_ante_n)
                    .. " — forcing new run\n")
                G.E_MANAGER:add_event(Event({
                    trigger = "after",
                    delay   = 0.5,
                    func    = function() pcall(G.FUNCS.start_run, nil, {stake = 1}); return true end
                }))
            end
            BalatroRL.write("blind_select")
        else
        local bod = G.GAME and G.GAME.blind_on_deck
        -- Log when The Hook is the upcoming/current boss for diagnostics
        local rr_choices = G.GAME and G.GAME.round_resets and G.GAME.round_resets.blind_choices
        local boss_key   = rr_choices and rr_choices["Boss"]
        if bod == "Boss" and boss_key == "bl_hook" and not BalatroRL._hook_skip_fired then
            BalatroRL._hook_skip_fired = true
            love.filesystem.append(LOG_FILE, os.time() .. " [HOOK] BLIND_SELECT: The Hook is boss — letting play proceed, relying on WON watchdog delay\n")
        end
        if bod and not BalatroRL._blind_fired then
            BalatroRL._blind_fired   = true
            BalatroRL._blind_fire_at = love.timer.getTime() + 0.5
        end
        if BalatroRL._blind_fire_at and love.timer.getTime() >= BalatroRL._blind_fire_at then
            BalatroRL._blind_fire_at = nil
            local rr        = G.GAME.round_resets
            -- blind_choices maps "Small"/"Big"/"Boss" → a string key like "bl_small"
            -- Use that key to look up the actual blind object in G.P_BLINDS
            local blind_obj = nil
            local choice_val = rr.blind_choices and rr.blind_choices[bod]
            if type(choice_val) == "string" then
                blind_obj = G.P_BLINDS and G.P_BLINDS[choice_val]
                love.filesystem.append(LOG_FILE, os.time() .. " lua_nav: choice_val=" .. choice_val
                    .. " P_BLINDS hit=" .. tostring(blind_obj ~= nil) .. "\n")
            elseif type(choice_val) == "table" then
                blind_obj = choice_val
            end
            blind_obj = blind_obj or rr.blind  -- last resort fallback
            local ok, err = pcall(function()
                G.E_MANAGER:add_event(Event({
                    trigger = "immediate",
                    func = function()
                        -- ease_round(1) intentionally omitted: it's a UI counter that
                        -- accumulates across runs without resetting, causing display corruption.
                        -- new_round() handles the actual round state correctly.
                        pcall(inc_career_stat, "c_rounds", 1)
                        rr.blind_tag   = nil
                        rr.blind       = blind_obj
                        rr.blind_states[bod] = "Current"
                        if G.blind_select     then G.blind_select:remove();     G.blind_select     = nil end
                        if G.blind_prompt_box then G.blind_prompt_box:remove(); G.blind_prompt_box = nil end
                        delay(0.2)  -- matches original select_blind — lets boss blind activate before new_round()
                        return true
                    end
                }))
                G.E_MANAGER:add_event(Event({
                    trigger = "immediate",
                    func = function() new_round(); return true end
                }))
            end)
            love.filesystem.append(LOG_FILE, os.time() ..
                (ok and " lua_nav: select_blind queued bod=" .. tostring(bod)
                        .. " ante=" .. tostring(rr.ante) .. "\n"
                    or  " lua_nav: queue err: " .. tostring(err) .. "\n"))
            BalatroRL.write("blind_select_done")
        end
        end  -- close ante guard else block
    else
        BalatroRL._blind_fired         = false
        BalatroRL._blind_fire_at       = nil
        BalatroRL._blind_select_logged = false
        BalatroRL._ante_guard_fired    = false
        BalatroRL._hook_skip_fired     = false
    end
    -- Lua cash out: fires 2s after entering ROUND_EVAL
    if BalatroRL.cfg().lua_nav and G.STATE == G.STATES.ROUND_EVAL then
        if not BalatroRL._cashout_fired then
            BalatroRL._cashout_fired   = true
            BalatroRL._cashout_fire_at = love.timer.getTime() + 1.0
        end
        if BalatroRL._cashout_fire_at and love.timer.getTime() >= BalatroRL._cashout_fire_at then
            BalatroRL._cashout_fire_at = nil
            local ca_ante = G.GAME and G.GAME.round_resets and G.GAME.round_resets.ante or "?"
            local ok, err = pcall(G.FUNCS.cash_out, {config = {button = "cash_out"}})
            love.filesystem.append(LOG_FILE, os.time() ..
                (ok and " lua_nav: cash_out OK ante=" .. tostring(ca_ante) .. "\n"
                    or  " lua_nav: cash_out err: " .. tostring(err) .. "\n"))
        end
    else
        BalatroRL._cashout_fired   = false
        BalatroRL._cashout_fire_at = nil
    end

    -- Lua shop: buy affordable jokers, then leave
    if BalatroRL.cfg().lua_nav and G.STATE == G.STATES.SHOP then
        if not BalatroRL._shop_fired then
            BalatroRL._shop_fired      = true
            BalatroRL._shop_buy_at     = love.timer.getTime() + 0.8
            BalatroRL._shop_sell_at    = nil   -- phase 2: sell weak joker
            BalatroRL._shop_upgrade_at = nil   -- phase 3: buy upgrade after sell
            BalatroRL._shop_leave_at   = nil
            BalatroRL._shop_sell_card  = nil
            BalatroRL._shop_buy_card   = nil
        end
        -- Helper: effective value of a joker card (rarity + edition bonus)
        -- Negative jokers are flagged unsellable (returns nil)
        local function joker_value(card)
            if not (card.ability and card.ability.set == "Joker") then return nil end
            local ed = card.edition or {}
            if ed.negative then return nil end   -- never sell Negative jokers
            local rarity = (card.config and card.config.center and card.config.center.rarity) or 1
            local bonus  = 0
            if     ed.polychrome then bonus = 10
            elseif ed.holo       then bonus = 5
            elseif ed.foil       then bonus = 3
            end
            return rarity * 10 + bonus
        end

        -- Phase 1: buy as many affordable jokers as possible without going over limit/budget
        if BalatroRL._shop_buy_at and love.timer.getTime() >= BalatroRL._shop_buy_at then
            BalatroRL._shop_buy_at = nil
            if G.shop_jokers and BalatroRL.cfg().buy_jokers then
                -- Track remaining dollars and slots locally (game state updates are queued, not instant)
                local remaining    = G.GAME.dollars
                local slots_used   = #G.jokers.cards
                local slots_max    = G.jokers.config.card_limit
                for _, card in ipairs(G.shop_jokers.cards or {}) do
                    local cost = card.cost or 0
                    if card.ability and card.ability.set == 'Joker'
                       and cost > 0
                       and remaining >= cost
                       and slots_used < slots_max then
                        local ok, err = pcall(G.FUNCS.buy_from_shop,
                            {config = {ref_table = card, id = "buy"}})
                        if ok then
                            remaining  = remaining  - cost
                            slots_used = slots_used + 1
                        end
                        love.filesystem.append(LOG_FILE, os.time() ..
                            (ok and " lua_nav: bought joker cost=" .. cost
                                 .. " remaining=$" .. remaining
                                 .. " slots=" .. slots_used .. "/" .. slots_max .. "\n"
                               or  " lua_nav: buy err: " .. tostring(err) .. "\n"))
                    end
                end

                -- Check for sell-upgrade opportunity (execute in next phase after delay)
                slots_used = #G.jokers.cards
                if slots_used >= slots_max and G.shop_jokers.cards then
                    local sell_card  = nil
                    local sell_score = math.huge
                    local sell_value = 0
                    for _, held in ipairs(G.jokers.cards or {}) do
                        local sc = joker_value(held)
                        if sc and sc < sell_score then
                            sell_score = sc
                            sell_card  = held
                            sell_value = held.sell_cost or 0
                        end
                    end
                    if sell_card then
                        local best_shop = nil
                        local best_sc   = sell_score
                        for _, scard in ipairs(G.shop_jokers.cards or {}) do
                            local sc   = joker_value(scard)
                            local cost = scard.cost or 0
                            if sc and sc > best_sc and (remaining + sell_value) >= cost then
                                best_sc   = sc
                                best_shop = scard
                            end
                        end
                        if best_shop then
                            -- Store for deferred execution — sell and buy need separate frames
                            BalatroRL._shop_sell_card  = sell_card
                            BalatroRL._shop_buy_card   = best_shop
                            BalatroRL._shop_sell_score = sell_score
                            BalatroRL._shop_buy_score  = best_sc
                            BalatroRL._shop_sell_at    = love.timer.getTime() + 0.3
                        end
                    end
                end

                -- Reroll once if nothing useful and cash allows
                local reroll_cost = (G.GAME.current_round and G.GAME.current_round.reroll_cost) or 5
                if remaining > reroll_cost * 2 and not BalatroRL._shop_sell_at then
                    local has_useful = false
                    for _, scard in ipairs(G.shop_jokers.cards or {}) do
                        if scard.ability and scard.ability.set == "Joker" then has_useful = true; break end
                    end
                    if not has_useful then
                        local rok = pcall(G.FUNCS.reroll_shop, {config = {}})
                        love.filesystem.append(LOG_FILE, os.time()
                            .. " lua_nav: reroll cost=$" .. tostring(reroll_cost)
                            .. (rok and " OK\n" or " FAILED\n"))
                    end
                end
            end
            if not BalatroRL._shop_sell_at then
                BalatroRL._shop_leave_at = love.timer.getTime() + 0.5
            end
        end

        -- Phase 2: sell weak joker (deferred from buy phase)
        if BalatroRL._shop_sell_at and love.timer.getTime() >= BalatroRL._shop_sell_at then
            BalatroRL._shop_sell_at = nil
            local sell_ok = pcall(G.FUNCS.sell_card,
                {config = {ref_table = BalatroRL._shop_sell_card, selling = true}})
            love.filesystem.append(LOG_FILE, os.time()
                .. " lua_nav: sell-upgrade SELL score=" .. tostring(BalatroRL._shop_sell_score)
                .. (sell_ok and " OK\n" or " FAILED\n"))
            -- Schedule buy after sell event has processed
            BalatroRL._shop_upgrade_at = love.timer.getTime() + 0.3
        end

        -- Phase 3: buy upgrade after sell has processed
        if BalatroRL._shop_upgrade_at and love.timer.getTime() >= BalatroRL._shop_upgrade_at then
            BalatroRL._shop_upgrade_at = nil
            local buy_ok = pcall(G.FUNCS.buy_from_shop,
                {config = {ref_table = BalatroRL._shop_buy_card, id = "buy"}})
            love.filesystem.append(LOG_FILE, os.time()
                .. " lua_nav: sell-upgrade BUY score=" .. tostring(BalatroRL._shop_buy_score)
                .. " cost=$" .. tostring((BalatroRL._shop_buy_card and BalatroRL._shop_buy_card.cost) or 0)
                .. (buy_ok and " OK\n" or " FAILED\n"))
            BalatroRL._shop_leave_at = love.timer.getTime() + 0.5
        end
        -- Phase 2: leave shop
        if BalatroRL._shop_leave_at and love.timer.getTime() >= BalatroRL._shop_leave_at then
            BalatroRL._shop_leave_at = nil
            if G.shop then
                local ok, err = pcall(G.FUNCS.toggle_shop, {config = {}})
                love.filesystem.append(LOG_FILE, os.time() ..
                    (ok and " lua_nav: toggle_shop OK\n" or " lua_nav: toggle_shop err: " .. tostring(err) .. "\n"))
            else
                BalatroRL._shop_fired = false   -- G.shop not ready, retry
                love.filesystem.append(LOG_FILE, os.time() .. " lua_nav: G.shop nil, retrying\n")
            end
        end
    else
        BalatroRL._shop_fired      = false
        BalatroRL._shop_buy_at     = nil
        BalatroRL._shop_sell_at    = nil
        BalatroRL._shop_upgrade_at = nil
        BalatroRL._shop_leave_at   = nil
        BalatroRL._shop_sell_card  = nil
        BalatroRL._shop_buy_card   = nil
    end

    -- Lua new run: fires 1s after entering GAME_OVER
    if BalatroRL.cfg().lua_nav and G.STATE == G.STATES.GAME_OVER then
        if not BalatroRL._gameover_fired then
            BalatroRL._gameover_fired   = true
            BalatroRL._gameover_fire_at = love.timer.getTime() + 0.5
        end
        if BalatroRL._gameover_fire_at and love.timer.getTime() >= BalatroRL._gameover_fire_at then
            BalatroRL._gameover_fire_at = nil
            local go_ante = G.GAME and G.GAME.round_resets and G.GAME.round_resets.ante or "?"
            local ok, err = pcall(G.FUNCS.start_run, nil, {stake = 1})
            love.filesystem.append(LOG_FILE, os.time() ..
                (ok and " lua_nav: start_run OK ante_was=" .. tostring(go_ante) .. "\n"
                    or  " lua_nav: start_run err: " .. tostring(err) .. "\n"))
        end
    else
        BalatroRL._gameover_fired   = false
        BalatroRL._gameover_fire_at = nil
    end

    -- Stuck-state watchdog: SELECTING_HAND with 0 hands left, game didn't auto-transition.
    -- discards_left NOT checked: The Hook discards from hand (not player discards), so
    -- discards_left stays > 0 even when unwinnable with 0 hands left.
    if G.STATE == G.STATES.SELECTING_HAND
       and G.GAME and G.GAME.current_round
       and G.GAME.current_round.hands_left <= 0
       and G.GAME.chips and G.GAME.blind then
        if not BalatroRL._stuck_fired then
            BalatroRL._stuck_fired = true
            local chips  = G.GAME.chips
            local target = G.GAME.blind.chips
            local bod    = G.GAME.blind_on_deck
            local rr     = G.GAME.round_resets
            if chips >= target then
                -- WON: force ROUND_EVAL, but first manually advance blind_on_deck so the
                -- next BLIND_SELECT shows the correct blind (not the same Boss again).
                -- For The Hook: add a 1.5s delay to let its pending card-discard E_MANAGER
                -- events clear before forcing ROUND_EVAL (avoids nil card access crash).
                local rr_choices_w = G.GAME and G.GAME.round_resets and G.GAME.round_resets.blind_choices
                local is_hook = (rr_choices_w and rr_choices_w["Boss"] == "bl_hook" and bod == "Boss")
                local won_delay = is_hook and 1.5 or 0.0
                love.filesystem.append(LOG_FILE, os.time()
                    .. " watchdog: WON stuck chips=" .. tostring(chips)
                    .. " target=" .. tostring(target)
                    .. " bod=" .. tostring(bod)
                    .. (is_hook and " [HOOK delay=1.5s]" or "") .. " — advancing blind + ROUND_EVAL\n")
                G.E_MANAGER:add_event(Event({
                    trigger = won_delay > 0 and "after" or "immediate",
                    delay   = won_delay,
                    func = function()
                        -- Mark current blind defeated
                        if rr and rr.blind_states and bod then
                            rr.blind_states[bod] = "Defeated"
                        end
                        -- Advance blind_on_deck to the next blind
                        if bod == "Small" then
                            G.GAME.blind_on_deck = "Big"
                        elseif bod == "Big" then
                            G.GAME.blind_on_deck = "Boss"
                        elseif bod == "Boss" then
                            G.GAME.blind_on_deck = "Small"
                            -- Increment ante and reset blind states for new ante
                            if rr then
                                rr.ante = (rr.ante or 1) + 1
                                if rr.blind_states then
                                    rr.blind_states["Small"] = "Unplayed"
                                    rr.blind_states["Big"]   = "Unplayed"
                                    rr.blind_states["Boss"]  = "Unplayed"
                                end
                                -- Pick a new boss for the next ante from the boss pool
                                -- (prevents same boss repeating every ante when watchdog bypasses NEW_ROUND)
                                if rr.blind_choices and G.GAME.boss_pool and #G.GAME.boss_pool > 0 then
                                    local idx = math.random(#G.GAME.boss_pool)
                                    rr.blind_choices["Boss"] = G.GAME.boss_pool[idx]
                                    love.filesystem.append(LOG_FILE, os.time()
                                        .. " watchdog: new boss for ante " .. tostring(rr.ante)
                                        .. " = " .. tostring(G.GAME.boss_pool[idx]) .. "\n")
                                end
                            end
                        end
                        love.filesystem.append(LOG_FILE, os.time()
                            .. " watchdog: blind advanced to " .. tostring(G.GAME.blind_on_deck)
                            .. " rr_ante=" .. tostring(rr and rr.ante or "?") .. "\n")
                        G.STATE          = G.STATES.ROUND_EVAL
                        G.STATE_COMPLETE = false
                        return true
                    end
                }))
            else
                -- LOST: force new run
                local bl_name  = G.GAME and G.GAME.blind and G.GAME.blind.name or "?"
                local bl_boss  = G.GAME and G.GAME.blind and G.GAME.blind.boss or false
                local bl_key   = rr and rr.blind_choices and rr.blind_choices[bod] or "?"
                local e_count  = (G.E_MANAGER and G.E_MANAGER.queue and #G.E_MANAGER.queue) or "?"
                love.filesystem.append(LOG_FILE, os.time()
                    .. " watchdog: LOST stuck — forcing new_run chips=" .. tostring(chips)
                    .. " target=" .. tostring(target)
                    .. " blind=" .. tostring(bl_name)
                    .. " boss=" .. tostring(bl_boss)
                    .. " bl_key=" .. tostring(bl_key)
                    .. " bod=" .. tostring(bod)
                    .. " E_MGR_queue=" .. tostring(e_count)
                    .. " G.STATE=" .. tostring(G.STATE) .. "\n")
                G.E_MANAGER:add_event(Event({
                    trigger = "after",
                    delay   = 0.5,
                    func    = function()
                        love.filesystem.append(LOG_FILE,
                            os.time() .. " watchdog: start_run firing now G.STATE=" .. tostring(G.STATE) .. "\n")
                        local ok, err = pcall(G.FUNCS.start_run, nil, {stake = 1})
                        love.filesystem.append(LOG_FILE,
                            os.time() .. " watchdog: start_run result=" .. tostring(ok)
                            .. " err=" .. tostring(err)
                            .. " G.STATE_after=" .. tostring(G.STATE) .. "\n")
                        return true
                    end
                }))
            end
        end
    elseif G.STATE ~= G.STATES.SELECTING_HAND then
        BalatroRL._stuck_fired = false
    end

    -- Keep state.json fresh while waiting for input on nav screens
    -- (shop items, blind info etc. may not be ready at the instant of state transition)
    local S = G.STATES
    if G.STATE == S.SHOP then
        BalatroRL.write("shop")
    elseif G.STATE == S.BLIND_SELECT then
        BalatroRL.write("blind_select")
    elseif G.STATE == S.ROUND_EVAL then
        BalatroRL.write("round_eval")
    elseif G.STATE == S.SELECTING_HAND then
        BalatroRL.write("selecting_hand")  -- keep state.json fresh so Python reset() can detect new run
    end

    -- Action polling: play/discard from Python, plus leave_shop signal
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
    -- Defer until Handy is loaded
    local function set_custom_speed()
        if Handy and Handy.speed_multiplier then
            Handy.speed_multiplier.value = CUSTOM_GAME_SPEED
            Handy.speed_multiplier.localize_value()
            love.filesystem.append(LOG_FILE, os.time() .. " Custom speed set: " .. CUSTOM_GAME_SPEED .. "x\n")
        end
    end
    -- Try immediately and also hook into game start
    pcall(set_custom_speed)
    local orig_start_run = G.FUNCS.start_run
    G.FUNCS.start_run = function(...)
        pcall(set_custom_speed)
        return orig_start_run(...)
    end
end

-- ═══════════════════════════════════════════════════════════════════════════
-- MINIMAL GRAPHICS MODE
-- Set to true for faster training with simple HUD overlay
-- ═══════════════════════════════════════════════════════════════════════════
local MINIMAL_GRAPHICS = true  -- Toggle this to enable/disable

local frame_counter = 0
local activity_timer = 0
local last_action_time = 0

local orig_love_draw = love.draw
love.draw = function()
    if not MINIMAL_GRAPHICS then
        -- Normal rendering
        if orig_love_draw then orig_love_draw() end
        return
    end
    
    -- Minimal HUD mode: black screen with essential info
    love.graphics.clear(0.05, 0.05, 0.08, 1)  -- Dark background
    love.graphics.setColor(1, 1, 1, 1)
    
    local y = 20
    local x = 20
    local line_height = 24
    
    -- Title
    love.graphics.setColor(0.4, 0.8, 1, 1)
    love.graphics.print("BALATRO RL - TRAINING MODE", x, y)
    y = y + line_height * 1.5
    
    if not G or not G.GAME then
        love.graphics.setColor(1, 1, 0, 1)
        love.graphics.print("Waiting for game...", x, y)
        return
    end
    
    local game = G.GAME
    local round_resets = game.round_resets or {}
    
    -- Ante & Blind
    love.graphics.setColor(1, 0.9, 0.3, 1)  -- Gold
    local ante = round_resets.ante or 1
    local blind_name = game.blind and game.blind.name or "Unknown"
    love.graphics.print(string.format("ANTE %d  |  %s", ante, blind_name), x, y)
    y = y + line_height * 1.5
    
    -- Score
    love.graphics.setColor(0.3, 1, 0.5, 1)  -- Green
    local score = game.chips or 0
    local target = game.blind and game.blind.chips or 1
    local progress = math.min(score / target, 1) * 100
    
    -- Simple number formatting
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
    love.graphics.setColor(0.7, 0.7, 1, 1)  -- Light blue
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
    
    -- Animated progress bar (cycles every 2 seconds)
    local bar_width = 200
    local bar_height = 8
    local cycle_pos = (activity_timer % 2) / 2  -- 0 to 1 over 2 seconds
    
    love.graphics.setColor(0.2, 0.2, 0.2, 1)
    love.graphics.rectangle("fill", x, y, bar_width, bar_height)
    
    -- Moving segment
    local segment_width = 40
    local segment_x = x + (bar_width - segment_width) * cycle_pos
    love.graphics.setColor(0, 1, 0.5, 1)  -- Bright green
    love.graphics.rectangle("fill", segment_x, y, segment_width, bar_height)
    
    y = y + line_height
    
    -- Frame counter & uptime
    love.graphics.setColor(0.4, 0.4, 0.4, 1)
    local uptime_min = math.floor(activity_timer / 60)
    local uptime_sec = math.floor(activity_timer % 60)
    love.graphics.print(string.format("FRAME: %d  |  UPTIME: %d:%02d", 
        frame_counter, uptime_min, uptime_sec), x, y)
end
