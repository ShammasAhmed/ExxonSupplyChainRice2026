"""Rail revenue per car vs. distance for caustic soda tank cars (rate_sources.csv R1, R3).

Data: STB 2024 Public Use Waybill Sample, https://www.stb.gov/wp-content/uploads/PublicUseWaybillSample2024.zip
Field positions: 2024 STB Waybill Reference Guide, PUWS layout.

    python sources/puws_caustic.py PublicUseWaybillSample2024.txt caustic
"""
import sys
import numpy as np
path = sys.argv[1]
mode = sys.argv[2] if len(sys.argv)>2 else "caustic"
rows=[]
with open(path) as f:
    for L in f:
        stcc=L[35:40]; ct=L[23:25]; hz=L[34]
        if mode=="caustic":
            ok = stcc=="28122" and hz=="H" and ct in ("50","51")
        elif mode=="chem28tank":
            ok = stcc.startswith("28") and ct in ("50","51")
        elif mode=="chem28tankH":
            ok = stcc.startswith("28") and ct in ("50","51") and hz=="H"
        if not ok: continue
        cl=int(L[10:14]); bw=int(L[40:47]); rev=int(L[54:63]); misc=int(L[72:81]); mi=int(L[88:92])
        xf=int(L[94:99])/100.0; nint=int(L[102]); o=L[103:106]; d=L[125:128]
        if cl<=0 or mi<=0 or rev<=0: continue
        rows.append((cl,bw,rev,misc,mi,xf,nint,o,d,ct))
cl=np.array([r[0] for r in rows],float); bw=np.array([r[1] for r in rows],float)
rev=np.array([r[2] for r in rows],float); mi=np.array([r[4] for r in rows],float)
xf=np.array([r[5] for r in rows]); nint=np.array([r[6] for r in rows])
w=cl*xf  # expanded carloads weight
rpc=rev/cl; tpc=bw/cl
print(f"mode={mode} sample records={len(rows)} sample cars={cl.sum():.0f} expanded cars={w.sum():.0f}")
print(f"wtd mean tons/car={np.average(tpc,weights=w):.1f} short tons; mean miles={np.average(mi,weights=w):.0f}")
print(f"wtd mean rev/car=${np.average(rpc,weights=w):,.0f}; rev/ton-mile (agg)= {rev.dot(xf)/ (bw*mi).dot(xf)*100:.2f} cents; rev/car-mile (agg) = ${rev.dot(xf)/(cl*mi).dot(xf):.2f}")
def wq(x,wt,q):
    i=np.argsort(x); x=x[i]; wt=wt[i]; c=np.cumsum(wt)/wt.sum(); return x[np.searchsorted(c,q)]
bands=[(0,100),(100,250),(250,400),(400,600),(600,800),(800,1000),(1000,1200),(1200,1500),(1500,1800),(1800,2200),(2200,3500)]
print("band | n_rec | exp_cars | mean_mi | P25 rev/car | median rev/car | P75 | mean rev/car | median rev/ton | median $/car-mi")
for a,b in bands:
    m=(mi>a)&(mi<=b)
    if m.sum()<3: print(a,b,"n<3",m.sum()); continue
    print(f"{a}-{b} | {m.sum()} | {w[m].sum():.0f} | {np.average(mi[m],weights=w[m]):.0f} | {wq(rpc[m],w[m],.25):,.0f} | {wq(rpc[m],w[m],.5):,.0f} | {wq(rpc[m],w[m],.75):,.0f} | {np.average(rpc[m],weights=w[m]):,.0f} | {wq(rpc[m]/tpc[m],w[m],.5):.1f} | {wq(rpc[m]/mi[m],w[m],.5):.2f}")
# weighted OLS rev/car = a + b*mi
X=np.vstack([np.ones_like(mi),mi]).T
W=np.sqrt(w)
beta,*_=np.linalg.lstsq(X*W[:,None],rpc*W,rcond=None)
res=rpc-X@beta; r2=1-np.average(res**2,weights=w)/np.average((rpc-np.average(rpc,weights=w))**2,weights=w)
print(f"WLS rev/car = {beta[0]:,.0f} + {beta[1]:.3f}*miles  (R2={r2:.2f}, n={len(rpc)})")
# also on band medians
# robust: least absolute deviation via IRLS
b=beta.copy()
for _ in range(200):
    r=np.abs(rpc-X@b); ww=w/np.maximum(r,1.0)
    Wt=np.sqrt(ww); b,*_=np.linalg.lstsq(X*Wt[:,None],rpc*Wt,rcond=None)
print(f"LAD (median) rev/car = {b[0]:,.0f} + {b[1]:.3f}*miles")
for k in (0,1):
    m=(nint==0) if k==0 else (nint>0)
    if m.sum()<5: continue
    bb,*_=np.linalg.lstsq(X[m]*W[m][:,None],rpc[m]*W[m],rcond=None)
    print(f"{'single-line' if k==0 else 'interline'}: n={m.sum()} exp cars={w[m].sum():.0f} WLS rev/car={bb[0]:,.0f}+{bb[1]:.3f}*mi; median rev/car={wq(rpc[m],w[m],.5):,.0f}, mean mi={np.average(mi[m],weights=w[m]):.0f}")
