/* ───────────────────────────────────────────────────────────────
   V7 Run 4 · Balatro RL trajectory visualizer
   Single-file renderer + playback engine
   ─────────────────────────────────────────────────────────────── */

const SUIT_GLYPH = { Spades: "♠", Hearts: "♥", Diamonds: "♦", Clubs: "♣" };
const SUIT_COLOR = { Spades: "black", Hearts: "red", Diamonds: "red", Clubs: "black" };
const RANK_LABEL = { 11: "J", 12: "Q", 13: "K", 14: "A" };

// Balatro hand-type base chips × mult (level 1) and per-level deltas.
// Used to render the scoring panel mid-play.
const HAND_BASE = {
  "High Card":       { chips:   5, mult:  1, d_chips: 10, d_mult: 1 },
  "Pair":            { chips:  10, mult:  2, d_chips: 15, d_mult: 1 },
  "Two Pair":        { chips:  20, mult:  2, d_chips: 20, d_mult: 1 },
  "Three of a Kind": { chips:  30, mult:  3, d_chips: 20, d_mult: 2 },
  "Straight":        { chips:  30, mult:  4, d_chips: 30, d_mult: 3 },
  "Flush":           { chips:  35, mult:  4, d_chips: 15, d_mult: 2 },
  "Full House":      { chips:  40, mult:  4, d_chips: 25, d_mult: 2 },
  "Four of a Kind":  { chips:  60, mult:  7, d_chips: 30, d_mult: 3 },
  "Straight Flush":  { chips: 100, mult:  8, d_chips: 40, d_mult: 4 },
  "Five of a Kind":  { chips: 120, mult: 12, d_chips: 35, d_mult: 3 },
  "Flush House":     { chips: 140, mult: 14, d_chips: 40, d_mult: 4 },
  "Flush Five":      { chips: 160, mult: 16, d_chips: 50, d_mult: 3 },
};

// Joker contributions to scoring.
// Scaling jokers track their accumulated chips/mult in state directly; for
// fixed-effect or game-state-dependent jokers we apply a small lookup.
const JOKER_EFFECTS = {
  // Scaling — pull whatever they've accumulated
  j_green_joker:    (j) => ({ mult: j.state?.mult || 0 }),
  j_ride_the_bus:   (j) => ({ mult: j.state?.mult || 0 }),
  j_constellation:  (j) => ({ mult: j.state?.mult || 0 }),
  j_fortune_teller: (j) => ({ mult: j.state?.mult || 0 }),
  j_red_card:       (j) => ({ mult: j.state?.mult || 0 }),
  j_madness:        (j) => ({ x_mult: j.state?.x_mult || 1 }),
  j_hologram:       (j) => ({ x_mult: j.state?.x_mult || 1 }),
  j_square_joker:   (j) => ({ chips: j.state?.chips || 0 }),
  j_runner:         (j) => ({ chips: j.state?.chips || 0 }),
  j_ice_cream:      (j) => ({ chips: j.state?.chips || 0 }),
  j_stone_joker:    (j) => ({ chips: j.state?.chips || 0 }),

  // Static adds
  j_stuntman:  () => ({ chips: 250 }),
  j_scholar:   () => ({ chips: 20, mult: 4 }),   // +20 chips, +4 mult on Aces
  j_abstract:  (j, g) => ({ mult: 3 * ((g.jokers || []).length) }),
  j_supernova: (j, g) => ({ mult: (j.state?.hands_played || 0) }),

  // Game-state-dependent
  j_blue_joker: (j, g) => ({ chips: 2 * (g.deck_size || 0) }),
  j_bull:       (j, g) => ({ mult: 2 * Math.max(0, g.money || 0) }),

  // Conditional (shown when their trigger is active)
  j_mystic_summit: (j, g) => (g.discards_left === 0 ? { mult: 15 } : {}),
  j_banner:        (j, g) => ({ chips: 30 * (g.discards_left || 0) }),
  j_acrobat:       (j, g) => (g.hands_left === 1 ? { x_mult: 3 } : {}),
  j_misprint:      () => ({ mult: 12 }),         // average of 0-23
};

function computeJokerBonus(jokers, gameState) {
  let chips = 0;
  let mult = 0;
  let x_mult = 1;
  if (!jokers) return { chips, mult, x_mult };
  const ctx = { ...gameState, jokers };
  for (const j of jokers) {
    const fn = JOKER_EFFECTS[j.key];
    if (!fn) continue;
    const out = fn(j, ctx) || {};
    chips += out.chips || 0;
    mult  += out.mult  || 0;
    if (out.x_mult) x_mult *= out.x_mult;
  }
  return { chips, mult, x_mult };
}

function evalHand(cards) {
  // Accepts an array of {rank:int, suit:string} and returns the Balatro hand name.
  if (!cards || !cards.length) return "High Card";
  const ranks = cards.map(c => c.rank).sort((a, b) => a - b);
  const suits = cards.map(c => c.suit);
  const rankCounts = {};
  ranks.forEach(r => { rankCounts[r] = (rankCounts[r] || 0) + 1; });
  const counts = Object.values(rankCounts).sort((a, b) => b - a);
  const uniqueSuits = new Set(suits);
  const isFlush = uniqueSuits.size === 1 && cards.length >= 5;

  // Straight detection — handle Ace-low (A-2-3-4-5) and normal
  let isStraight = false;
  if (cards.length >= 5) {
    const uniq = [...new Set(ranks)].sort((a, b) => a - b);
    if (uniq.length >= 5) {
      // Check for 5 consecutive
      for (let i = 0; i <= uniq.length - 5; i++) {
        if (uniq[i + 4] - uniq[i] === 4) { isStraight = true; break; }
      }
      // Wheel: A,2,3,4,5 → ranks [2,3,4,5,14]
      if (!isStraight &&
          uniq.includes(14) && uniq.includes(2) && uniq.includes(3) &&
          uniq.includes(4) && uniq.includes(5)) {
        isStraight = true;
      }
    }
  }

  if (counts[0] === 5) return isFlush ? "Flush Five" : "Five of a Kind";
  if (counts[0] === 4) return "Four of a Kind";
  if (counts[0] === 3 && counts[1] === 2) return isFlush ? "Flush House" : "Full House";
  if (isStraight && isFlush) return "Straight Flush";
  if (isFlush) return "Flush";
  if (isStraight) return "Straight";
  if (counts[0] === 3) return "Three of a Kind";
  if (counts[0] === 2 && counts[1] === 2) return "Two Pair";
  if (counts[0] === 2) return "Pair";
  return "High Card";
}

const $ = (id) => document.getElementById(id);
const el = (tag, cls, html) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (html !== undefined) e.innerHTML = html;
  return e;
};

const fmt = (n, decimals = 0) => {
  if (n == null || !isFinite(n)) return "—";
  if (Math.abs(n) >= 1e6) return (n / 1e6).toFixed(1) + "M";
  if (Math.abs(n) >= 1e3) return (n / 1e3).toFixed(1) + "K";
  return Number(n).toLocaleString(undefined, {
    minimumFractionDigits: decimals, maximumFractionDigits: decimals,
  });
};

// Per-phase default dwell times (ms) for adaptive pacing
const PHASE_DELAY = {
  hand: 1400,         // decisions on hand need time to read
  shop: 700,          // shop rapid-fire through buys/rerolls
  blind_select: 1100, // beat on blind choice
  game_over: 3000,
};

class ReplayApp {
  constructor() {
    this.episode = null;
    this.step = 0;
    this.playing = false;
    this.speedMultiplier = 1.0; // 1.0 = use PHASE_DELAY as-is
    this.timer = null;
    this.wireControls();
  }

  async load(path = "trajectory.json") {
    const res = await fetch(path);
    if (!res.ok) throw new Error(`Failed to load ${path}: ${res.status}`);
    this.episode = await res.json();
    this.step = 0;
    this.renderMeta();
    this.render();
  }

  wireControls() {
    $("btn-play").addEventListener("click", () => this.togglePlay());
    $("btn-prev").addEventListener("click", () => this.goto(this.step - 1));
    $("btn-next").addEventListener("click", () => this.goto(this.step + 1));
    $("btn-restart").addEventListener("click", () => this.goto(0));
    $("speed-select").addEventListener("change", (e) => {
      this.speedMultiplier = parseInt(e.target.value, 10) / 1200;
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === " ") { e.preventDefault(); this.togglePlay(); }
      else if (e.key === "ArrowRight") this.goto(this.step + 1);
      else if (e.key === "ArrowLeft")  this.goto(this.step - 1);
      else if (e.key === "r" || e.key === "R") this.goto(0);
    });
  }

  togglePlay() {
    if (this.playing) {
      this.playing = false;
      $("btn-play").textContent = "▶";
      if (this.timer) { clearTimeout(this.timer); this.timer = null; }
    } else {
      if (this.step >= this.episode.trajectory.length - 1) this.step = 0;
      this.playing = true;
      $("btn-play").textContent = "❚❚";
      this.schedule();
    }
  }

  schedule() {
    if (!this.playing) return;
    const s = this.episode.trajectory[this.step];
    const base = PHASE_DELAY[s.phase] ?? 1000;
    const delay = Math.max(100, base * this.speedMultiplier);
    this.timer = setTimeout(() => {
      if (this.step < this.episode.trajectory.length - 1) {
        this.goto(this.step + 1);
        this.schedule();
      } else {
        this.playing = false;
        $("btn-play").textContent = "▶";
      }
    }, delay);
  }

  goto(i) {
    const max = this.episode.trajectory.length - 1;
    this.step = Math.max(0, Math.min(max, i));
    this.render();
  }

  // ── Rendering ──────────────────────────────────────────────────

  renderMeta() {
    $("seed").textContent = this.episode.seed;
    $("ckpt").textContent = "iter_0920";
  }

  render() {
    if (!this.episode) return;
    const s = this.episode.trajectory[this.step];
    const total = this.episode.trajectory.length;

    $("step").textContent = `${this.step + 1} / ${total}`;
    $("progress-fill").style.width = `${((this.step + 1) / total) * 100}%`;

    // Top-bar + blind info
    $("ante").textContent = s.ante ?? 1;
    const blind = s.blind || {};
    $("blind-name").textContent = blind.name ?? "—";
    $("blind-title").textContent = blind.name ?? "—";
    $("blind-target").textContent = fmt(blind.target ?? 0);

    const blindBadge = $("blind-badge");
    blindBadge.className = "blind-badge";
    const kind = (blind.kind || "Small").toLowerCase();
    if (kind === "big")  blindBadge.classList.add("big");
    if (kind === "boss") blindBadge.classList.add("boss");
    blindBadge.textContent = (blind.kind ?? "—").toUpperCase();

    // Counters
    $("money").textContent = s.money ?? 0;
    $("hands-left").textContent = s.hands_left ?? 0;
    $("discards-left").textContent = s.discards_left ?? 0;

    // Score + progress bar
    const score = s.chips_scored ?? 0;
    const target = blind.target ?? 1;
    $("score").textContent = fmt(score);
    $("score-bar").style.width = `${Math.min(100, (score / Math.max(1, target)) * 100)}%`;

    // Deck counter (Red Deck)
    const deckSize = s.deck_size ?? 52;
    $("deck-size").textContent = deckSize;

    // Jokers
    this.renderJokers(s.jokers || []);

    // Consumables
    this.renderConsumables(s.consumables || []);

    // Phase-dependent stage
    const area = $("stage-area");
    area.className = `stage-area ${s.phase}`;

    if (s.phase === "hand")         this.renderHand(s);
    else if (s.phase === "shop")    this.renderShop(s);
    else if (s.phase === "blind_select") this.renderBlindSelect(s);
    else if (s.phase === "game_over")    this.renderGameOver(s);

    // Decision panel
    this.renderDecision(s);
  }

  renderJokers(jokers) {
    $("joker-count").textContent = `${jokers.length}/5`;
    const container = $("jokers");
    container.innerHTML = "";
    for (const j of jokers) {
      const tile = el("div", "joker");
      const left  = el("div");
      left.appendChild(el("div", "joker-name", j.name));
      left.appendChild(el("div", "joker-key", j.key));
      tile.appendChild(left);

      const stats = el("div", "joker-state");
      const st = j.state || {};
      if (st.mult != null && st.mult !== 0)
        stats.appendChild(el("span", "joker-stat mult", `+${st.mult}×`));
      if (st.chips != null && st.chips !== 0)
        stats.appendChild(el("span", "joker-stat chips", `+${st.chips}`));
      if (st.money != null && st.money !== 0)
        stats.appendChild(el("span", "joker-stat", `$${st.money}`));
      if (st.sell_value != null)
        stats.appendChild(el("span", "joker-stat", `$${st.sell_value}`));
      tile.appendChild(stats);
      container.appendChild(tile);
    }
  }

  renderConsumables(keys) {
    const container = $("consumables");
    container.innerHTML = "";
    const slots = 2;
    for (let i = 0; i < slots; i++) {
      if (i < keys.length) {
        const pretty = keys[i].replace(/^c_/, "").replace(/_/g, " ");
        container.appendChild(el("div", "consumable", pretty));
      } else {
        container.appendChild(el("div", "empty-slot"));
      }
    }
  }

  renderHand(s) {
    const area = $("hand-area");
    area.innerHTML = "";

    const selected = new Set(
      s.action?.type === "hand" ? (s.action.subset || []) : []
    );
    const intent = s.action?.intent;

    // Evaluate hand type for the selected subset (show for play; dim for discard/no selection)
    const selectedCards = (s.hand_cards || []).filter((_, i) => selected.has(i));
    const handType = selectedCards.length ? evalHand(selectedCards) : null;
    const levels = s.planet_levels || {};
    const panel = this.makeScorePanel(handType, levels, intent, s);
    area.appendChild(panel);

    const row = el("div", "cards");
    (s.hand_cards || []).forEach((c, idx) => {
      const card = this.makeCard(c);
      if (selected.has(idx)) {
        card.classList.add("selected");
        if (intent === "discard") card.dataset.queued = "discard";
        if (intent === "play")    card.dataset.queued = "play";
      }
      row.appendChild(card);
    });
    area.appendChild(row);
  }

  makeScorePanel(handType, levels, intent, s) {
    const panel = el("div", "score-panel");
    // Only dim when there's genuinely nothing to score (no cards selected).
    // On discard steps we still show the preview so viewers can see what the
    // agent chose to throw away.
    if (!handType) panel.classList.add("idle");

    const displayType = handType || "—";
    const base = HAND_BASE[displayType] || { chips: 0, mult: 0, d_chips: 0, d_mult: 0 };
    const level = Math.max(1, levels[displayType] || 1);
    const baseChips = base.chips + base.d_chips * (level - 1);
    const baseMult  = base.mult  + base.d_mult  * (level - 1);

    // Apply joker contributions
    const bonus = computeJokerBonus(s.jokers || [], s);
    const totalChips = baseChips + bonus.chips;
    const totalMult  = (baseMult  + bonus.mult) * (bonus.x_mult || 1);
    const total = totalChips * totalMult;

    const head = el("div", "score-panel-hand");
    head.appendChild(el("span", "score-hand-name", displayType));
    head.appendChild(el("span", "score-hand-level", `LVL ${level}`));

    const cm = el("div", "score-chip-mult");
    cm.appendChild(this.makeStackedValue("score-chips", baseChips, bonus.chips));
    cm.appendChild(el("span", "score-times", "×"));
    cm.appendChild(this.makeStackedValue("score-mult", baseMult,
                     bonus.mult, bonus.x_mult > 1 ? bonus.x_mult : null));
    cm.appendChild(el("span", "score-equals", "="));
    cm.appendChild(el("span", "score-total", fmt(total)));

    panel.appendChild(head);
    panel.appendChild(cm);

    // Breakdown row — only show if there's actually a joker contribution
    if (bonus.chips || bonus.mult || (bonus.x_mult && bonus.x_mult > 1)) {
      const parts = [`base ${baseChips} × ${baseMult}`];
      if (bonus.chips) parts.push(`+${bonus.chips} chips`);
      if (bonus.mult)  parts.push(`+${bonus.mult} mult`);
      if (bonus.x_mult && bonus.x_mult > 1) parts.push(`×${bonus.x_mult.toFixed(2)}`);
      panel.appendChild(el("div", "score-breakdown", parts.join(" · ")));
    }

    return panel;
  }

  makeStackedValue(cls, baseVal, addVal, xMult) {
    const box = el("span", cls);
    box.appendChild(el("span", "score-base", baseVal));
    if (addVal) box.appendChild(el("span", "score-joker-add", `+${addVal}`));
    if (xMult)  box.appendChild(el("span", "score-joker-xmult", `×${xMult.toFixed(2)}`));
    return box;
  }

  makeCard(c) {
    const color = SUIT_COLOR[c.suit] || "black";
    const card = el("div", `card ${color}`);
    const rank = RANK_LABEL[c.rank] || String(c.rank);
    const glyph = SUIT_GLYPH[c.suit] || "?";
    if (c.enhancement && c.enhancement !== "None") card.classList.add(`enh-${c.enhancement.toLowerCase()}`);
    if (c.edition && c.edition !== "None")         card.classList.add(`edition-${c.edition.toLowerCase()}`);
    if (c.debuffed) card.classList.add("debuffed");

    const tl = el("div", "card-corner");
    tl.appendChild(el("span", "", rank));
    tl.appendChild(el("span", "", glyph));
    const mid = el("div", "card-suit-big", glyph);
    const br = el("div", "card-corner card-corner-br");
    br.appendChild(el("span", "", rank));
    br.appendChild(el("span", "", glyph));
    card.appendChild(tl);
    card.appendChild(mid);
    card.appendChild(br);
    return card;
  }

  renderShop(s) {
    const area = $("shop-area");
    area.innerHTML = "";
    const label = el("div", "hand-label", "SHOP");
    const grid  = el("div", "shop-grid");
    const items = s.shop || [];

    // Determine the chosen shop slot for this step
    const act = s.action?.action;
    let chosenIdx = null;
    if (s.action?.type === "phase" && act != null && act >= 2 && act <= 8) {
      chosenIdx = act - 2;
    }

    items.forEach((it, i) => {
      const tile = el("div", "shop-item");
      if (it.sold) tile.classList.add("bought");
      if (i === chosenIdx) tile.classList.add("chosen");
      tile.appendChild(el("div", "shop-kind", it.kind || ""));
      tile.appendChild(el("div", "shop-name", it.name || it.key || "—"));
      tile.appendChild(el("div", "shop-price", `$${it.price ?? 0}`));
      grid.appendChild(tile);
    });
    if (!items.length) {
      grid.appendChild(el("div", "shop-item", `<div class="shop-name" style="opacity:0.4">shop data unavailable</div>`));
    }
    area.appendChild(label);
    area.appendChild(grid);
  }

  renderBlindSelect(s) {
    const blind = s.blind || {};
    const name = blind.name || `Ante ${s.ante} ${blind.kind || ""}`;
    $("blind-choice-name").textContent = name;
    $("blind-choice-target").textContent = fmt(blind.target ?? 0);

    const kindBadge = $("blind-choice-kind-badge");
    kindBadge.className = "blind-choice-kind";
    const kind = (blind.kind || "Small").toLowerCase();
    if (kind === "big")  kindBadge.classList.add("big");
    if (kind === "boss") kindBadge.classList.add("boss");
    kindBadge.textContent = (blind.kind ?? "—").toUpperCase();

    // Agent's decision: skip_blind vs select_blind
    const decision = $("blind-choice-decision");
    const verdict = $("decision-verdict");
    const sub = $("decision-sub");
    decision.classList.remove("skip", "engage");

    const chose = s.action?.name;
    if (chose === "skip_blind") {
      decision.classList.add("skip");
      verdict.textContent = "SKIP";
      sub.textContent = blind.kind === "Boss"
        ? "not allowed — falling back"
        : "claim tag · conserve cash";
    } else {
      decision.classList.add("engage");
      verdict.textContent = "ENGAGE";
      sub.textContent = blind.kind === "Boss"
        ? "face the boss"
        : "play for chips + payout";
    }
  }

  renderGameOver(s) {
    const out = this.episode.outcome || {};
    const title = out.won
      ? `ANTE ${out.ante} CLEARED`
      : `ELIMINATED AT ANTE ${out.ante}`;
    $("game-over-title").textContent = title;
  }

  renderDecision(s) {
    const pill = $("phase-pill");
    pill.className = `phase-pill ${s.phase}`;
    pill.textContent = (s.phase || "—").replace("_", " ").toUpperCase();

    const chosenName = this.actionDisplayName(s);
    $("chosen-action").textContent = chosenName;

    const probs = s.top_probs || [];
    const probsEl = $("probs");
    probsEl.innerHTML = "";
    for (const [name, p] of probs.slice(0, 5)) {
      const chosen = (name === chosenName) ||
                     (s.action?.type === "hand" && name === s.action.intent);
      const row = el("div", "prob-row");
      const nm = el("div", `prob-name${chosen ? " chosen" : ""}`, this.prettyActionName(name));
      const vl = el("div", `prob-value${chosen ? " chosen" : ""}`, `${(p * 100).toFixed(1)}%`);
      const track = el("div", "prob-bar-track");
      const fill  = el("div", `prob-bar-fill${chosen ? " chosen" : ""}`);
      // Animate width after insertion
      requestAnimationFrame(() => { fill.style.width = `${(p * 100).toFixed(1)}%`; });
      track.appendChild(fill);
      row.appendChild(nm);
      row.appendChild(vl);
      row.appendChild(track);
      probsEl.appendChild(row);
    }

    const v = s.value_estimate ?? 0;
    const vEl = $("value-estimate");
    vEl.textContent = (v >= 0 ? "+" : "") + v.toFixed(2);
    vEl.className = `value-number mono ${v > 0 ? "positive" : v < 0 ? "negative" : ""}`;

    const r = s.reward ?? 0;
    const rEl = $("step-reward");
    rEl.textContent = (r >= 0 ? "+" : "") + r.toFixed(2);
    rEl.className = `value-number mono ${r > 0 ? "positive" : r < 0 ? "negative" : ""}`;
  }

  actionDisplayName(s) {
    if (!s.action) return "—";
    if (s.action.type === "hand") {
      const intent = s.action.intent;
      const subset = (s.action.subset || []).join(",");
      return `${intent} [${subset}]`;
    }
    return s.action.name || `action ${s.action.action}`;
  }

  prettyActionName(name) {
    return name.replace(/_/g, " ");
  }
}

// Boot
window.addEventListener("DOMContentLoaded", () => {
  const app = new ReplayApp();
  window.__app = app;
  app.load("trajectory.json").catch((e) => {
    console.error(e);
    document.body.innerHTML = `<div style="padding:40px;color:#e8ecf1;font-family:system-ui">
      <h2 style="color:#ef4444">Failed to load trajectory.json</h2>
      <p>${e.message}</p>
      <p style="color:#8a95a8">Serve this folder over HTTP, e.g. <code>python -m http.server 8000</code> then open <code>http://localhost:8000/</code>.</p>
    </div>`;
  });
});
