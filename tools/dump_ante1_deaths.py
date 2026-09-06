"""Dump ante<=2 death traces from a bench sidecar JSON."""
import json
import sys

path = sys.argv[1] if len(sys.argv) > 1 else \
    "vendor/balatro-rl/results/goal_iter6_armA.json"
d = json.load(open(path))
label = [k for k in d.keys()][0]
res = d[label]["results"]
print("seeds:", len(res))
for r in res:
    if not r["won"] and r["ante"] <= 2:
        print("--- seed", r["seed"], "death ante", r["ante"],
              "blind", r.get("death_blind"), r.get("death_kind"),
              "$", r["dollars"])
        print("   jokers:", r["jokers"])
        st = r.get("stats") or {}
        print("   rerolls", st.get("rerolls"), "packs", st.get("packs_bought"),
              "spent", st.get("money_spent"),
              "tarots_used", len(st.get("consumable_uses") or []))
        co = st.get("co_owned") or []
        ante_plays = [p for p in co if p[0] <= r["ante"]]
        for p in ante_plays[-8:]:
            print("   play a%d %s %s" % (p[0], p[1], p[3]))
        cu = st.get("consumable_uses") or []
        for c in cu:
            if c[0] <= r["ante"]:
                print("   used a%d %s targets=%d" % (c[0], c[1],
                                                     len(c[3] or [])))
