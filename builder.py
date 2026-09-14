# -*- coding: utf-8 -*-
"""
builder.py — збирає макети у Figma через figma_mcp (без участі LLM).

build_order(brief, photo_paths) → dict(section_id, frame_ids, figma_url, exported=[jpg paths])

Підтримка:
  • рілз (обкладинка) — усі 8 шаблонів
  • карусель — шаблони 5, 7, 8 повністю; 1–4, 6 — лише обкладинка (решту верстає дизайнер)
Усі шаблони беруться з файлу PROPHOTO STUDIO, сторінка POST AUTOMATIZATION; результат — на сторінці AUTO POSTS.
"""
import os, json, glob, requests
from figma_mcp import Figma, FILE_KEY

# ----------------------------------------------------------------------------- template node ids (сторінка POST AUTOMATIZATION)
COVER = {"1": "413:226", "2": "414:481", "3": "414:496", "4": "414:501", "5": "414:508", "6": "414:522", "7": "414:538", "8": "384:236", "9": "461:2"}
BASE_A, BASE_B, BASE_LAST = "359:9", "359:8", "359:11"        # шаблон 7/8: внутрішні A, B, фінал
STUDIO_INNER = "415:782"                                       # шаблон 5: внутрішній
WEEK_INNER = "414:616"                                         # шаблон 3: слайд «ТИЖДЕНЬ N»

# позиції текстів обкладинок: (x, y, width|0=auto, size, lineHeight, style, align, letterSpacingPct)
COVER_TEXT = {
    "1": {"title": (417, 1835, 2459, 200, 200, "Light", "CENTER", 84), "subline": (739, 2433, 1762, 100, 100, "Regular", "CENTER", 0)},
    "2": {"subline": (310, 2626, 2600, 100, 100, "Regular", "LEFT", 0), "title": (295, 2930, 2650, 300, 250, "Bold", "LEFT", 0)},
    "3": {"title": (313, 2402, 2614, 200, 200, "Regular", "CENTER", 84)},
    "4": {"subline": (631, 2559, 1978, 100, 100, "Regular", "CENTER", 0), "title": (307, 2735, 2626, 300, 300, "Regular", "CENTER", 0)},
    "5": {"subline": (197, 3133, 2800, 100, 100, "Regular", "LEFT", 0), "title": (197, 3373, 2800, 300, 250, "Regular", "LEFT", 0)},
    "6": {"subline": (114, 3133, 2900, 100, 100, "Regular", "LEFT", 0), "title": (114, 3317, 2900, 300, 250, "Regular", "LEFT", 0)},
    "7": {"title": (1146, 250, 2008, 200, 200, "Bold", "LEFT", 0), "subline": (320, 3276, 2600, 100, 100, "Light", "CENTER", 0), "cta": (158, 3637, 900, 64, 64, "Light", "LEFT", 0)},
    "8": {"title": (1146, 250, 2008, 200, 200, "Bold", "LEFT", 0), "subline": (320, 3276, 2600, 100, 100, "Light", "CENTER", 0), "cta": (158, 3637, 900, 64, 64, "Light", "LEFT", 0)},
    "9": {"subline": (197, 3133, 2800, 100, 100, "Regular", "LEFT", 0), "title": (197, 3316, 2800, 300, 250, "Regular", "LEFT", 0)},
}

JS_COMMON = r"""
const FAM="KyivType Sans";
const ST={Light:"Light-",Bold:"Bold-",Heavy:"Heavy-",Regular:"Regular"}, WG={"Light-":200,"Bold-":700,"Heavy-":840};
for(const s of Object.values(ST)) { try{ await figma.loadFontAsync({family:FAM,style:s}); }catch(e){} }
function fn(st){ const s=ST[st]; return WG[s]?{family:FAM,style:s,variationSettings:{wght:WG[s],MIDL:0,CONT:0}}:{family:FAM,style:s}; }
const WHITE={r:1,g:1,b:1};
function parseRich(t,base){ const segs=[]; let ul=null; const re=/\*\*(.+?)\*\*|\*(.+?)\*|([^*]+)/g; let m,pos=0;
  while((m=re.exec(t))){ if(m[1]) segs.push({t:m[1],s:"Bold"}); else if(m[2]){ segs.push({t:m[2],s:base}); ul={start:pos,end:pos+m[2].length}; } else segs.push({t:m[3],s:base}); pos+=(m[1]||m[2]||m[3]).length; }
  return {segs,ul}; }
function mkText(parent,x,y,w,size,lh,text,base,align,ls,noUpper){
  const n=figma.createText(); parent.appendChild(n);
  n.fontName=fn(base); n.fontSize=size; n.lineHeight={unit:"PIXELS",value:lh}; n.textCase=noUpper?"ORIGINAL":"UPPER";
  if(ls) n.letterSpacing={unit:"PERCENT",value:ls};
  n.fills=[{type:"SOLID",color:WHITE}]; n.textAlignHorizontal=align||"LEFT";
  const {segs,ul}=parseRich(text,base); const full=noUpper?segs.map(s=>s.t).join(""):segs.map(s=>s.t).join("").toUpperCase(); n.characters=full;
  let p=0; for(const s of segs){ if(s.t.length) n.setRangeFontName(p,p+s.t.length,fn(s.s)); p+=s.t.length; }
  if(w){ n.resize(w,100); n.textAutoResize="HEIGHT"; } else { n.textAutoResize="WIDTH_AND_HEIGHT"; }
  n.x=x; n.y=y; n.name=full.slice(0,40); return {n,ul};
}
function measure(parent,text,size,base){ const t=mkText(parent,0,-9999,0,size,size,text,base); const w=t.n.width; t.n.remove(); return w; }
function findTexts(f){ return f.findAll(x=>x.type==="TEXT"); }
function imgRects(f){ return f.findAll(x=>x.type==="RECTANGLE"&&x.fills.length&&x.fills[0].type==="IMAGE"&&x.width>600).sort((a,b)=>a.x-b.x); }
function setSize(n,s){ n.fontSize=s; n.lineHeight={unit:"PIXELS",value:s}; }
function lastLineWidth(parent,text,size,width){ const words=text.split(" "); let cur=""; for(const wd of words){ const test=cur?cur+" "+wd:wd; if(measure(parent,test,size,"Bold")>width&&cur) cur=wd; else cur=test; } return measure(parent,cur,size,"Bold"); }
const page=figma.root.children.find(p=>p.name==="AUTO POSTS")||figma.createPage(); page.name="AUTO POSTS"; await figma.setCurrentPageAsync(page);
const bottom=page.children.length?Math.max(...page.children.map(c=>c.y+c.height)):0;
const sec=figma.createSection(); sec.name=SPEC.section; page.appendChild(sec); sec.x=0; sec.y=bottom+500;
let cx=100; const made=[]; const imgs=[];
async function cloneTpl(id,name){ const src=await figma.getNodeByIdAsync(id); const c=src.clone(); sec.appendChild(c); c.visible=true; c.name=name; c.x=cx; c.y=100; cx+=c.width+200; made.push(c.id); return c; }
"""

JS_COVER = r"""
{ const f=await cloneTpl(COVER_ID,"01_COVER"); for(const t of findTexts(f)) t.remove();
  const ulVec=f.findOne(x=>x.type==="VECTOR"&&x.name==="Vector 39");
  const P=CT;
  if(P.title){ const [x,y,w,s,lh,st,al,ls]=P.title; let ts=s; const T=mkText(f,x,y,w,ts,lh,SPEC.title,st,al,ls);
    const maxLines = SPEC.template==="3"?3:2; while(T.n.height>maxLines*ts*(lh/s)+5&&ts>120){ ts-=8; T.n.fontSize=ts; T.n.lineHeight={unit:"PIXELS",value:Math.round(ts*lh/s)}; }
    if(al==="LEFT"&&y>2000) T.n.y=y+( (2*lh) - T.n.height ); }
  if(P.subline&&SPEC.subline){ const [x,y,w,s,lh,st,al,ls]=P.subline; let ss=s; const S=mkText(f,x,y,w,ss,lh,SPEC.subline,st,al,ls); while(S.n.height>ss+5&&ss>60){ ss-=4; setSize(S.n,ss); }
    if(S.ul&&ulVec){ const chars=S.n.characters; const wb=S.ul.start?measure(f,chars.slice(0,S.ul.start),ss,st):0; const ww=measure(f,chars.slice(S.ul.start,S.ul.end),ss,st); const fullW=measure(f,chars,ss,st); const sx=x+(w-fullW)/2+wb; ulVec.resize(ww+60,42); ulVec.x=sx-30; ulVec.y=S.n.y+ss+18; } else if(ulVec) ulVec.remove(); }
  if(P.cta&&SPEC.cta){ const [x,y,w,s,lh,st,al]=P.cta; mkText(f,x,y,w,s,lh,SPEC.cta,st,al); }
  imgs.push(...imgRects(f).map(r=>r.id)); }
"""

JS_BASE_INNER = r"""
function itemsBlock(f,items,nums,numX,textX,w,yTop,yBot,gap,center){
  const nodes=items.map(t=>mkText(f,textX,0,w,80,90,t,"Light").n);
  const total=nodes.reduce((a,n)=>a+n.height,0)+gap*(items.length-1);
  let y=center? yTop+(yBot-yTop-total)/2 : yTop;
  nodes.forEach((n,i)=>{ n.y=y; mkText(f,numX,y+(n.height-90)/2,0,80,90,nums[i]+".","Heavy"); y+=n.height+gap; });
}
let secIdx=0;
for(const s of SPEC.slides){ secIdx++;
  const key=(secIdx%2===1)?"A":"B"; const f=await cloneTpl(key==="A"?BASE_A:BASE_B,String(secIdx+1).padStart(2,"0")+"_"+key);
  for(const t of findTexts(f)) t.remove();
  const T=mkText(f,474,393,1963,128,128,s.title,"Bold","CENTER");
  const sq=f.findOne(x=>x.type==="VECTOR"&&x.name==="Vector 43");
  const lw=lastLineWidth(f,T.n.characters,128,1963);
  if(sq){ sq.x=474+(1963-lw)/2; sq.y=393+T.n.height+40; }
  const items=s.items, nums=items.map((_,i)=>i+1);
  if(key==="A"){
    const probe=items.map(t=>{const n=mkText(f,0,-9999,1420,80,90,t,"Light").n; const h=n.height; n.remove(); return h;});
    const total=probe.reduce((a,b)=>a+b,0)+80*(items.length-1);
    const arrow=f.findOne(x=>x.name==="Group 127");
    if(total<=1245||items.length<4){ itemsBlock(f,items,nums,590,786,1420,2375,3620,80,true); }
    else { let best=null; for(let k=1;k<items.length;k++){ const a=probe.slice(0,k).reduce((x,y)=>x+y,0)+120*(k-1), b=probe.slice(k).reduce((x,y)=>x+y,0)+120*(items.length-k-1); const sc=Math.max(a,b); if(!best||sc<best.sc) best={sc,k}; }
      itemsBlock(f,items.slice(0,best.k),nums.slice(0,best.k),239,350,1100,2600,3560,120,true); itemsBlock(f,items.slice(best.k),nums.slice(best.k),1540,1648,1480,2600,3560,120,true); if(arrow) arrow.remove(); }
  } else { itemsBlock(f,items,nums,752,936,1800,880,2200,80,false); }
  imgs.push(...imgRects(f).map(r=>r.id));
}
await cloneTpl(BASE_LAST,"99_LAST");
"""

JS_STUDIO_INNER = r"""
const U=s=>s.toUpperCase();
function txt(f,pred){ return f.findOne(n=>n.type==="TEXT"&&pred(n)); }
let i=1;
for(const s of SPEC.slides){ i++; const c=await cloneTpl(STUDIO_INNER,String(i).padStart(2,"0")+"_INNER");
  const big=txt(c,n=>n.characters==="ЗАЛ"), sub=txt(c,n=>n.characters.toLowerCase()==="циклорама");
  const words=s.title.split(/[\s—:]+/); const bigWord=words[0]||s.title; const subText=s.title.slice(bigWord.length).replace(/^[\s—:–-]+/,"")||"";
  big.textAutoResize="WIDTH_AND_HEIGHT"; big.characters=U(bigWord);
  sub.textAutoResize="WIDTH_AND_HEIGHT"; sub.textAlignHorizontal="LEFT"; sub.characters=U(subText||" "); sub.x=big.x+60; sub.y=558; let fs=180; while(sub.width>2500&&fs>110){ fs-=10; sub.fontSize=fs; }
  const pillL=c.findOne(n=>n.name==="Rectangle 60"), pillR=c.findOne(n=>n.name==="Rectangle 61");
  const ptL=txt(c,n=>n.characters.startsWith("80")), ptR=txt(c,n=>n.characters.startsWith("Циклорама"));
  const tags=s.tags||[]; 
  for(const [rect,t,text,right] of [[pillL,ptL,tags[0],false],[pillR,ptR,tags[1],true]]){
    if(!text){ rect.remove(); t.remove(); continue; }
    t.fontSize=84; t.textAutoResize="WIDTH_AND_HEIGHT"; t.characters=U(text); const w=t.width+180; rect.resize(w,163); if(right) rect.x=2814-w; t.x=rect.x+90; t.y=rect.y+(163-t.height)/2; }
  if(pillL.parent&&pillR.parent&&pillR.x<pillL.x+pillL.width+40){ pillR.x=pillL.x+pillL.width+40; ptR.x=pillR.x+90; }
  const L1=txt(c,n=>n.characters.startsWith("Велике")), L2=txt(c,n=>n.characters.startsWith("Всі")), R1=txt(c,n=>n.characters.startsWith("Турбо")), R2=txt(c,n=>n.characters.startsWith("Великий"));
  const items=s.items; const half=Math.ceil(items.length/2); const Lit=items.slice(0,half), Rit=items.slice(half);
  const nav=c.findOne(n=>n.name==="Group 118");
  for(const [nodes,its] of [[[L1,L2],Lit],[[R1,R2],Rit]]){ const [a,b]=nodes;
    if(!its.length){ a.remove(); b.remove(); continue; }
    a.textAutoResize="HEIGHT"; a.resize(1216,100); a.characters=its.slice(0,Math.ceil(its.length/2)).join("\n"); a.textAutoResize="HEIGHT";
    const rest=its.slice(Math.ceil(its.length/2)); if(rest.length){ b.textAutoResize="HEIGHT"; b.resize(1216,100); b.characters=rest.join("\n"); b.textAutoResize="HEIGHT"; b.y=a.y+a.height+50; } else b.remove(); }
  const cols=c.findAll(n=>n.type==="TEXT"&&n.y>2600&&n.fontSize>=64&&n.fontSize<=80);
  for(const size of [80,72,64]){ for(const t of cols){ t.fontSize=size; t.textAutoResize="HEIGHT"; }
    const L=cols.filter(t=>t.x<1400).sort((a,b)=>a.y-b.y), R=cols.filter(t=>t.x>=1400).sort((a,b)=>a.y-b.y);
    for(const col of [L,R]) if(col.length>1) col[1].y=col[0].y+col[0].height+50;
    const bottom=Math.max(...cols.map(t=>t.y+t.height)); if(!nav||bottom<=nav.y-60) break; }
  imgs.push(...imgRects(c).map(r=>r.id));
}
await cloneTpl(BASE_LAST,"99_LAST");
"""

JS_WEEKS_INNER = r"""
let wi=0;
for(const s of SPEC.slides){ wi++; const c=await cloneTpl(WEEK_INNER,String(wi+1).padStart(2,"0")+"_WEEK");
  for(const t of findTexts(c)) t.remove();
  const DARK={r:0.08,g:0.04,b:0.03};
  function dk(n){ n.fills=[{type:"SOLID",color:DARK}]; return n; }
  const badge=(s.tags&&s.tags[0])||("тиждень "+wi);
  const B=mkText(c,116,256,767,100,100,badge,"Bold","CENTER"); dk(B.n); let bs=100; while(B.n.height>105&&bs>60){ bs-=6; setSize(B.n,bs); B.n.y=211+(190-B.n.height)/2; }
  const T=mkText(c,1262,255,1900,100,100,s.title,"Light"); dk(T.n); let ts=100; while(T.n.height>2*ts+5&&ts>64){ ts-=6; setSize(T.n,ts); }
  const items=s.items||[]; const half=Math.ceil(items.length/2);
  const cols=[[165,941,items.slice(0,half)],[1132,1278,items.slice(half)]]; const nodes=[];
  for(const [x,w,its] of cols){ if(!its.length) continue; const n=mkText(c,x,2784,w,64,64,its.map(i=>"•  "+i).join("\n\n"),"Regular","LEFT",0,true); dk(n.n); nodes.push(n.n); }
  for(const size of [64,56,48]){ for(const n of nodes){ n.fontSize=size; n.lineHeight={unit:"PIXELS",value:size}; }
    if(Math.max(0,...nodes.map(n=>n.y+n.height))<=3560) break; }
  imgs.push(...imgRects(c).filter(r=>r.name!=="logo").map(r=>r.id));
}
await cloneTpl(BASE_LAST,"99_LAST");
"""

def _js(brief):
    t = brief["template"]
    spec = {"section": f"{brief['order_id']} · {brief['title']}",
            "template": t, "title": brief["title"], "subline": brief.get("subline") or "", "cta": brief.get("cta") or "",
            "slides": brief.get("slides") or []}
    js = f"const SPEC={json.dumps(spec, ensure_ascii=False)}; const COVER_ID={json.dumps(COVER[t])}; const CT={json.dumps(COVER_TEXT[t])};\n"
    js += f"const BASE_A={json.dumps(BASE_A)}, BASE_B={json.dumps(BASE_B)}, BASE_LAST={json.dumps(BASE_LAST)}, STUDIO_INNER={json.dumps(STUDIO_INNER)}, WEEK_INNER={json.dumps(WEEK_INNER)};\n"
    js += JS_COMMON + JS_COVER
    if brief["type"] == "carousel" and spec["slides"]:
        if t in ("7", "8"): js += JS_BASE_INNER
        elif t == "5": js += JS_STUDIO_INNER
        elif t == "3": js += JS_WEEKS_INNER
    js += "\nsec.resizeWithoutConstraints(cx+100,4300); return JSON.stringify({section:sec.id,made,imgs});"
    return js

def build_order(brief, photo_paths, out_dir):
    fg = Figma()
    res = json.loads(fg.use_figma(_js(brief), "build order " + brief["order_id"]))
    # photos: cycle through client photos for every image slot
    if photo_paths and res["imgs"]:
        urls = fg.upload_assets(res["imgs"])
        for i, u in enumerate(urls):
            fg.put_photo(u, photo_paths[i % len(photo_paths)])
    # export
    os.makedirs(out_dir, exist_ok=True); exported = []
    for i, fid in enumerate(res["made"], 1):
        url = fg.screenshot_url(fid, 4050)
        p = os.path.join(out_dir, f"slide_{i:02d}.png"); open(p, "wb").write(requests.get(url, timeout=120).content)
        try:
            from PIL import Image
            jp = p[:-4] + ".jpg"; Image.open(p).convert("RGB").save(jp, quality=95); os.remove(p); p = jp
        except Exception: pass
        exported.append(p)
    url = f"https://www.figma.com/design/{FILE_KEY}/PROPHOTO-STUDIO?node-id={res['section'].replace(':', '-')}"
    full = brief["type"] == "reels" or brief["template"] in ("3", "5", "7", "8")
    return {"section": res["section"], "frames": res["made"], "figma_url": url, "exported": exported, "complete": full}

if __name__ == "__main__":
    import sys
    brief = json.load(open(sys.argv[1], encoding="utf-8")); d = os.path.dirname(sys.argv[1])
    photos = sorted(glob.glob(os.path.join(d, "photos", "*")))
    print(json.dumps(build_order(brief, photos, os.path.join(d, "out")), ensure_ascii=False, indent=1))
