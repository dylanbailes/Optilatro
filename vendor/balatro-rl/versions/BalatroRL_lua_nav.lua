-- BalatroRL.lua
-- Writes state.json on state changes. Executes card play/discard from action.json.
-- Navigation modes: Lua (headless) or Python/pyautogui (mouse). Toggle in mod config.


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
    }
end

local function joker_info(joker)
    if not joker or not joker.config then return nil end
    local cfg = joker.config.center or {}
    return {
        name   = cfg.name or "unknown",
        key    = cfg.key  or "unknown",
        rarity = cfg.rarity or 0,
        cost   = joker.cost or 0,
        mult   = (joker.ability and joker.ability.mult)    or 0,
        chips  = (joker.ability and joker.ability.t_chips) or 0,
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
        blind_name     = blind.name  or "unknown",
        blind_chips    = blind.chips or 0,
        blind_boss     = blind.boss  or false,
        hands_left     = round.hands_left    or 0,
        discards_left  = round.discards_left or 0,
        money          = game.dollars        or 0,
        joker_slots    = game.joker_limit    or 5,
        current_score  = (round.current_hand and round.current_hand.chips) or 0,
        score_target   = blind.chips or 0,
        hand           = {},
        jokers         = {},
        deck_remaining = G.deck    and #G.deck.cards    or 0,
        discard_count  = G.discard and #G.discard.cards or 0,
        shop           = {},
        hand_levels    = hand_levels(),
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

hook("play_cards_from_highlighted",    "play")
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

local POLL_INTERVAL = 0.1
local poll_timer    = 0
local last_G_STATE  = nil

local orig_game_update = Game.update
Game.update = function(self, dt)
    orig_game_update(self, dt)
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
    end

    -- Lua blind select: bypass G.FUNCS.select_blind (needs UIBox we can't easily get)
    -- Instead call new_round() directly after setting state — what select_blind does internally
    -- Lua blind select: queue events via E_MANAGER (correct way, not synchronous from update)
    -- Only runs if lua_nav is enabled in mod config
    if BalatroRL.cfg().lua_nav and G.STATE == G.STATES.BLIND_SELECT then
        local bod = G.GAME and G.GAME.blind_on_deck
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
                        ease_round(1)
                        pcall(inc_career_stat, "c_rounds", 1)
                        rr.blind_tag   = nil
                        rr.blind       = blind_obj
                        rr.blind_states[bod] = "Current"
                        if G.blind_select     then G.blind_select:remove();     G.blind_select     = nil end
                        if G.blind_prompt_box then G.blind_prompt_box:remove(); G.blind_prompt_box = nil end
                        return true
                    end
                }))
                G.E_MANAGER:add_event(Event({
                    trigger = "immediate",
                    func = function() new_round(); return true end
                }))
            end)
            love.filesystem.append(LOG_FILE, os.time() ..
                (ok and " lua_nav: select_blind queued bod=" .. tostring(bod) .. "\n"
                    or  " lua_nav: queue err: " .. tostring(err) .. "\n"))
            BalatroRL.write("blind_select_done")
        end
    else
        BalatroRL._blind_fired   = false
        BalatroRL._blind_fire_at = nil
    end
    -- Lua cash out: fires 2s after entering ROUND_EVAL
    if BalatroRL.cfg().lua_nav and G.STATE == G.STATES.ROUND_EVAL then
        if not BalatroRL._cashout_fired then
            BalatroRL._cashout_fired   = true
            BalatroRL._cashout_fire_at = love.timer.getTime() + 1.0
        end
        if BalatroRL._cashout_fire_at and love.timer.getTime() >= BalatroRL._cashout_fire_at then
            BalatroRL._cashout_fire_at = nil
            local ok, err = pcall(G.FUNCS.cash_out, {config = {button = "cash_out"}})
            love.filesystem.append(LOG_FILE, os.time() ..
                (ok and " lua_nav: cash_out OK\n" or " lua_nav: cash_out err: " .. tostring(err) .. "\n"))
        end
    else
        BalatroRL._cashout_fired   = false
        BalatroRL._cashout_fire_at = nil
    end

    -- Lua shop: buy affordable jokers, then leave
    if BalatroRL.cfg().lua_nav and G.STATE == G.STATES.SHOP then
        if not BalatroRL._shop_fired then
            BalatroRL._shop_fired   = true
            BalatroRL._shop_buy_at  = love.timer.getTime() + 0.8   -- wait for shop to build
            BalatroRL._shop_leave_at = nil
            BalatroRL._shop_bought  = false
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
            end
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
        BalatroRL._shop_fired    = false
        BalatroRL._shop_buy_at   = nil
        BalatroRL._shop_leave_at = nil
    end

    -- Lua new run: fires 1s after entering GAME_OVER
    if BalatroRL.cfg().lua_nav and G.STATE == G.STATES.GAME_OVER then
        if not BalatroRL._gameover_fired then
            BalatroRL._gameover_fired   = true
            BalatroRL._gameover_fire_at = love.timer.getTime() + 0.5
        end
        if BalatroRL._gameover_fire_at and love.timer.getTime() >= BalatroRL._gameover_fire_at then
            BalatroRL._gameover_fire_at = nil
            local ok, err = pcall(G.FUNCS.start_run, nil, {stake = 1})
            love.filesystem.append(LOG_FILE, os.time() ..
                (ok and " lua_nav: start_run OK\n" or " lua_nav: start_run err: " .. tostring(err) .. "\n"))
        end
    else
        BalatroRL._gameover_fired   = false
        BalatroRL._gameover_fire_at = nil
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
            -- Python signals it's done buying — leave the shop
            pcall(G.FUNCS.toggle_shop, {config = {}})
        else
            execute_action(action_type, card_indices)
        end
    end)
end

BalatroRL.write("mod_loaded")
