import json, pathlib, sys
ROOT = pathlib.Path(__file__).resolve().parent.parent
VENDOR = ROOT / "vendor" / "balatro-rl"
sys.path.insert(0, str(VENDOR))
from collections import Counter
from balatro_sim.agent_v9 import ECONOMY_JOKERS

p = pathlib.Path(r"D:\Optilatro\vendor\balatro-rl\results\v10_report.json")
data = json.loads(p.read_text())
for policy in ['heuristic_v9','heuristic_v10']:
    agg = data[policy]['aggregate']
    results = data[policy]['results']
    deaths = [r for r in results if not r['won'] and r['ante']<=1]
    print(f"=== {policy} ===")
    print(f"Ante-1 deaths {len(deaths)}/200 ({len(deaths)/2.0:.1f}%)")
    jcnt = Counter()
    no_j=one_j=econ_only=0
    packs=[]
    rarities=[]
    for r in deaths:
        st = r.get('stats',{})
        jb = st.get('jokers_bought',[])
        packs.append(st.get('packs_bought',0))
        if not jb:
            no_j+=1
        elif len(jb)==1:
            one_j+=1
        if jb and all(k in ECONOMY_JOKERS for k in jb):
            econ_only+=1
        for k in jb:
            jcnt[k]+=1
    print(f" 0 jokers {no_j}/{len(deaths)} 1 joker {one_j} econ_only {econ_only}")
    print(f" packs_bought mean in deaths {sum(packs)/len(packs) if packs else 0:.2f}")
    print(f" top jokers in deaths: {jcnt.most_common(10)}")
    blind_cnt = Counter(r.get('death_blind','?') for r in deaths)
    print(f" death_blind: {blind_cnt}")
    bests = [r['stats'].get('best_score',0) for r in deaths]
    if bests:
        print(f" best_score min {min(bests)} max {max(bests)} mean {sum(bests)/len(bests):.0f}")
    # also check jokers at end vs bought
    # check dollars
    dollars = [r.get('dollars',0) for r in deaths]
    if dollars:
        print(f" dollars at death mean {sum(dollars)/len(dollars):.1f} max {max(dollars)}")
    # Check generation counts
    tarots = [len(r['stats'].get('tarots',[])) for r in deaths]
    if tarots:
        print(f" tarots mean {sum(tarots)/len(tarots):.1f}")
    print()
# Compare survivors
for policy in ['heuristic_v10']:
    results = data[policy]['results']
    survivors = [r for r in results if r['ante']>1]
    print(f"=== {policy} survivors ante>1 (first 3) ===")
    for r in survivors[:3]:
        print(f" seed {r['seed']} ante {r['ante']} won {r['won']} jokers_bought {r['stats'].get('jokers_bought')} packs {r['stats'].get('packs_bought')} econ {r['stats'].get('econ_source')}")
