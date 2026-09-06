"""Paired per-seed diff between two bench sidecars."""
import json
import sys

a_path, b_path = sys.argv[1], sys.argv[2]
A = {r["seed"]: r for r in json.load(open(a_path))["heuristic_v10"]["results"]}
B = {r["seed"]: r for r in json.load(open(b_path))["heuristic_v10"]["results"]}
aw = sum(1 for s in A if A[s]["won"])
bw = sum(1 for s in B if B[s]["won"])
ad = sum(1 for s in A if not A[s]["won"] and A[s]["ante"] <= 1)
bd = sum(1 for s in B if not B[s]["won"] and B[s]["ante"] <= 1)
print("A: %dW/%dD  B: %dW/%dD" % (aw, ad, bw, bd))
gains = [s for s in A if not A[s]["won"] and B[s]["won"]]
losses = [s for s in A if A[s]["won"] and not B[s]["won"]]
print("B gains (A lost -> B won):", sorted(gains))
print("B regressions (A won -> B lost):", sorted(losses))
