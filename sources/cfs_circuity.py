"""Circuity (routed / great-circle miles) by mode from the 2017 Commodity Flow Survey (rate_sources.csv G1).

Data: https://www2.census.gov/programs-surveys/cfs/datasets/2017/cfs-2017-puf-csv.zip

    python sources/cfs_circuity.py CFS_2017_PUF_CSV.csv
"""
import sys, pandas as pd, numpy as np
df=pd.read_csv(sys.argv[1],dtype={'MODE':str,'SCTG':str,'HAZMAT':str,'EXPORT_YN':str},usecols=['SCTG','MODE','SHIPMT_WGHT','SHIPMT_DIST_GC','SHIPMT_DIST_ROUTED','HAZMAT','WGT_FACTOR','EXPORT_YN'])
df=df[(df.SHIPMT_DIST_GC>0)&(df.EXPORT_YN=='N')]
df['tw']=df.WGT_FACTOR*df.SHIPMT_WGHT/2000
df['r']=df.SHIPMT_DIST_ROUTED/df.SHIPMT_DIST_GC
names={'04':'For-hire truck','05':'Company truck','06':'Rail','08':'Inland water','09':'Great Lakes','12':'Pipeline','15':'Truck+rail','16':'Truck+water','17':'Rail+water'}
def wq(x,w,q):
    i=np.argsort(x.values); x=x.values[i]; w=w.values[i]; c=np.cumsum(w)/w.sum(); return x[np.searchsorted(c,q)]
def rep(d,label):
    print(f"--- {label}")
    print(f"{'mode':16s} {'n':>7s} {'ratio_tonmi':>11s} {'ratio_ship':>10s} {'med_ton':>7s} {'p25':>5s} {'p75':>5s} {'avgGC_tonwt':>11s}")
    for m,n in names.items():
        s=d[d.MODE==m]
        if len(s)<30: 
            print(f"{n:16s} {len(s):7d} (too few)"); continue
        rt=(s.tw*s.SHIPMT_DIST_ROUTED).sum()/(s.tw*s.SHIPMT_DIST_GC).sum()
        rs=(s.WGT_FACTOR*s.SHIPMT_DIST_ROUTED).sum()/(s.WGT_FACTOR*s.SHIPMT_DIST_GC).sum()
        print(f"{n:16s} {len(s):7d} {rt:11.3f} {rs:10.3f} {wq(s.r,s.tw,.5):7.3f} {wq(s.r,s.tw,.25):5.2f} {wq(s.r,s.tw,.75):5.2f} {(s.tw*s.SHIPMT_DIST_GC).sum()/s.tw.sum():11.0f}")
rep(df,'All commodities, domestic (EXPORT_YN=N)')
rep(df[df.SCTG=='20'],'SCTG 20 Basic chemicals')
rep(df[df.HAZMAT=='H'],'HAZMAT=H (non-class-3 hazmat)')
rep(df[(df.SCTG=='20')&(df.HAZMAT=='H')],'SCTG20 & HAZMAT=H')
rep(df[df.SHIPMT_DIST_GC>=100],'All commodities, GC>=100 mi')
