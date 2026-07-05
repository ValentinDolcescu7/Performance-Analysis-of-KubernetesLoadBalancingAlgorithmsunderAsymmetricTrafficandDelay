#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Grafic compact, o singura figura, citind latency_avg_aligned.csv.
Scara Y = symlog: LINIARA de la 0 pana la LINTHRESH (zoom pe zona mica, vezi
diferentele de jos), apoi LOGARITMICA deasupra (spike-urile se string sus).
Porneste din 0.
"""
import os
import pandas as pd, numpy as np
import matplotlib.pyplot as plt
from matplotlib.ticker import MultipleLocator, FixedLocator, ScalarFormatter

DATA_DIR = "p99_graphs"
CSV_PATH = os.path.join(DATA_DIR, "latency_avg99_aligned.csv")
OUT_PATH = os.path.join(DATA_DIR, "latency99_symlog.png")

TITLE     = "Întârziere P99"
YLABEL    = "Întârziere P99 (ms)"
LINTHRESH = 15      # pana aici e liniar (zoom pe zona mica); peste -> logaritmic
LINSCALE  = 1.3     # cat spatiu primeste zona liniara (mai mare = mai mult zoom jos)
MARKER_EVERY = 4

STYLE = {
    "RR":  dict(color="#0072B2", marker="o", label="RR"),
    "WRR": dict(color="#E69F00", marker="s", label="WRR"),
    "LC":  dict(color="#009E73", marker="^", label="LC"),
    "SED": dict(color="#CC79A7", marker="D", label="SED"),
    "NQ":  dict(color="#D55E00", marker="v", label="NQ"),
}

df = pd.read_csv(CSV_PATH); x = df["minute"].to_numpy()
cols = [c for c in df.columns if c != "minute"]
ymax = np.nanmax(df[cols].to_numpy())

fig, ax = plt.subplots(figsize=(9.5,5.4), dpi=150)
for c in cols:
    y = df[c].to_numpy(dtype=float)
    st = STYLE.get(c, dict(color=None, marker="o", label=c))
    ax.plot(x, y, color=st["color"], lw=2.0, marker=st["marker"], markevery=MARKER_EVERY,
            markersize=5.5, markerfacecolor="white", markeredgecolor=st["color"],
            markeredgewidth=1.3, label=st["label"], zorder=3)

ax.set_yscale("symlog", linthresh=LINTHRESH, linscale=LINSCALE)
ax.set_ylim(0, ymax*1.2)
# ticks alese ca sa se vada si zona mica, si cea mare
ticks=[0,5,10,15,30,50,100,200,400]
ticks=[t for t in ticks if t<=ymax*1.2]
ax.yaxis.set_major_locator(FixedLocator(ticks))
ax.yaxis.set_major_formatter(ScalarFormatter())

ax.set_title(TITLE, fontsize=15, fontweight="bold", pad=12)
ax.set_xlabel("Timp scurs (minute)", fontsize=12, fontweight="bold")
ax.set_ylabel(YLABEL, fontsize=12, fontweight="bold")
ax.set_xlim(0, x.max())
ax.xaxis.set_major_locator(MultipleLocator(5)); ax.xaxis.set_minor_locator(MultipleLocator(1))
ax.axhline(LINTHRESH, color="0.7", lw=0.8, ls=":")   # marcheaza trecerea liniar->log
ax.grid(True, which="major", ls="--", lw=0.6, alpha=0.5)
ax.legend(loc="upper right", framealpha=0.95, fontsize=9, ncol=2)
fig.tight_layout()
fig.savefig(OUT_PATH, bbox_inches="tight")
print("Scris:", OUT_PATH)