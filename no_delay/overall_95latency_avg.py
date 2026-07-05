#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Face MEDIA pe fiecare CSV (media celor 3 pod-uri la fiecare moment),
aliniaza toate pe un interval comun 0 -> 30 min (pas 0.5 min = 30s),
pune 0-uri la inceput ca liniile sa porneasca din 0, si scoate UN SINGUR CSV:

    minute, RR, WRR, LC, SED, NQ

Pe ala il duci mai departe (plot, Excel, etc). Citeste robust (spatii/underscore),
converteste unitatile (µs/ms/s -> ms). Nimic hardcodat.
"""
import os, re, glob
import pandas as pd, numpy as np

DATA_DIR  = "p95_graphs"
OUT_DIR   = DATA_DIR
GRID_MAX  = 30.0     # interval pana la 30 min
GRID_STEP = 0.5      # pas 0.5 min (30s)
LEAD_ZEROS = 2       # cate puncte de 0 punem la inceput (ca sa porneasca din 0)
METRIC_HINT = ""     # daca ai mai multe seturi in folder, pune "P95"/"P99"/"Average" ca sa-l alegi

ORDER = ["rr","wrr","lc","sed","nq"]
LABEL = {"rr":"RR","wrr":"WRR","lc":"LC","sed":"SED","nq":"NQ"}

_U={"s":1000.0,"ms":1.0,"us":0.001,"µs":0.001,"ns":1e-6}
def to_ms(v):
    s=str(v).strip()
    if s=="" or s.lower() in("nan","null","-"): return np.nan
    m=re.match(r"^([0-9]*\.?[0-9]+)\s*([a-zµ]+)$",s)
    if not m:
        try:return float(s)
        except:return np.nan
    return float(m.group(1))*_U.get(m.group(2).lower(),1.0)

def _norm(s): return re.sub(r"[ _]+","_",s.lower())
def find_csv(key):
    hint=_norm(METRIC_HINT) if METRIC_HINT else ""
    for p in glob.glob(os.path.join(DATA_DIR,"*.csv")):
        n=_norm(os.path.basename(p))
        if n.startswith(_norm(key)+"_") and (hint=="" or hint in n):
            return p
    raise FileNotFoundError(f"Nu am gasit CSV pentru '{key}' in {DATA_DIR}")

def mean_series(key):
    """media celor 3 pod-uri la fiecare moment + minutele scurse de la start."""
    df=pd.read_csv(find_csv(key)); df["Time"]=pd.to_datetime(df["Time"])
    pods=[c for c in df.columns if c!="Time"]
    vals=df[pods].apply(lambda c:c.map(to_ms))
    el=(df["Time"]-df["Time"].iloc[0]).dt.total_seconds()/60.0
    return el.to_numpy(), vals.mean(axis=1).to_numpy()

# grid comun 0..30
grid=np.round(np.arange(0, GRID_MAX+1e-9, GRID_STEP),3)
out=pd.DataFrame({"minute":grid})

for key in ORDER:
    el,y=mean_series(key)
    # interpolez media pe grid; inainte de primul punct -> 0, dupa ultimul -> ultima valoare
    yi=np.interp(grid, el, y, left=0.0, right=y[-1])
    # 0-uri la inceput ca sa porneasca din 0
    for i in range(min(LEAD_ZEROS,len(yi))):
        yi[i]=0.0
    out[LABEL[key]]=np.round(yi,2)

path=os.path.join(OUT_DIR,"latency_avg_aligned.csv")
out.to_csv(path,index=False)
print("Scris:",path,"|",len(out),"randuri")
print(out.head(8).to_string(index=False))
print("...")
print(out.tail(3).to_string(index=False))