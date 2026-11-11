"""Create a standalone interactive activity map using only standard Python.

python plot_activity_map.py
Open activity_heatmap.html in a browser. No server or internet is required.
"""
import argparse
import base64
import csv
import json
from pathlib import Path
import struct

LABELS = {
    "eating_drinking": "Eating / drinking",
    "studying_working": "Studying / working",
    "reading_relaxing": "Reading / relaxing",
    "socializing": "Socializing",
    "taking_break": "Taking a break",
    "club_event": "Club / event",
    "passing_through": "Passing through",
    "scrolling_phone": "Scrolling phone",
    "other": "Other",
    "planned_meeting": "Planned meeting",
}
COLORS = ["#d73027", "#2166ac", "#1b7837", "#984ea3", "#e08214",
          "#008b8b", "#666666", "#c51b7d", "#806327", "#526000"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cells", type=Path, default=Path("cleaned/map_cells.csv"))
    parser.add_argument("--visits", type=Path, default=Path("cleaned/visits.csv"))
    parser.add_argument("--map", type=Path, default=Path("survey_cad_full_labelled_3.png"))
    parser.add_argument("--output", type=Path, default=Path("activity_heatmap.html"))
    args = parser.parse_args()
    png = args.map.read_bytes()
    if png[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("Map must be a PNG file.")
    width, height = struct.unpack(">II", png[16:24])
    with args.visits.open(encoding="utf-8-sig", newline="") as f:
        visits = {r["visit_id"]: r for r in csv.DictReader(f)}
    points = []
    seen = set()
    with args.cells.open(encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            x, y = int(r["column"]), int(r["row"])
            if not 1 <= x <= 30 or not 1 <= y <= 24:
                raise ValueError("Map cell outside the 30 x 24 grid.")
            key = (r["visit_id"], r["activity"], x, y)
            if key in seen:
                continue
            seen.add(key)
            v = visits[r["visit_id"]]
            points.append([r["activity"], x, y, v["weekday"], v["time_period"], r["visit_id"]])
    labels = dict(LABELS)
    for a in sorted({p[0] for p in points} - labels.keys()):
        labels[a] = a.replace("_", " ").title()
    config = json.dumps(dict(points=points, labels=labels, colors=COLORS, width=width, height=height)).replace("<", "\\u003c")
    document = '''<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Hunt Library activity map</title>
<style>
body{font:16px system-ui;margin:24px;background:#f5f6f8;color:#17202a}h1{margin-bottom:8px}
.controls{display:flex;gap:16px;flex-wrap:wrap;margin:18px 0}select,button{font:inherit;padding:6px}
#legend{display:flex;flex-wrap:wrap;gap:8px 20px;margin:16px 0}#legend label{cursor:pointer}
.swatch{display:inline-block;width:13px;height:13px;margin-right:5px;border-radius:50%}
.map{background:white;border:1px solid #ccd2da;overflow:auto}svg{display:block;width:100%;min-width:850px}
.note{color:#455366;max-width:1000px;line-height:1.5}#status{font-weight:600;margin:12px 0}
@media print{.controls{display:none}body{margin:0}.map{overflow:visible}svg{min-width:0}}
</style>
<h1>Hunt Library activity map</h1>
<p class="note">Each mark represents a selected grid cell. Circle area or cell opacity increases with the number of visits selecting that cell for that activity. Hover for counts. Select one activity for an unobstructed heatmap.</p>
<div class="controls">
<label>Weekday <select id="day"><option value="">All weekdays</option></select></label>
<label>Time period <select id="period"><option value="">All periods</option></select></label>
<label>Display <select id="mode"><option value="points">Colored point clusters</option><option value="heat">Grid heatmap</option></select></label>
<label><input id="labels" type="checkbox" checked>Label peak cells</label>
<button id="all">Show all</button><button id="none">Hide all</button>
<button id="download">Download SVG</button></div>
<div id="legend"></div><div id="status"></div>
<div class="map"><svg id="map" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Activity selections over Hunt Library floor plan"></svg></div>
<p class="note">Colors identify activities; overlapping marks can obscure one another. Counts represent visits, including repeat visitors on different days. Cells are not exact physical points, and counts do not measure dwell time or occupancy. Blank areas mean no recorded selections in this subset. Time periods use voucher categories; weekdays use survey start dates. Peak labels identify the most selected cell for each visible activity, choosing the top-left cell in a tie. The intensity scale is shared across visible activities and recalculated when filters change.</p>
<script>
const DATA=__DATA__;
const svg=document.getElementById('map'), NS='http://www.w3.org/2000/svg';
const W=DATA.width,H=DATA.height,cw=W/30,ch=H/24;
svg.setAttribute('viewBox',`0 0 ${W} ${H}`);
function node(tag,attrs,parent=svg){let n=document.createElementNS(NS,tag);Object.entries(attrs).forEach(([k,v])=>n.setAttribute(k,v));parent.appendChild(n);return n}
node('image',{href:'data:image/png;base64,__PNG__',width:W,height:H});
const layer=node('g',{}), annotations=node('g',{});
const keys=Object.keys(DATA.labels), active=new Set(keys);
const color=a=>DATA.colors[keys.indexOf(a)%DATA.colors.length];
const day=document.getElementById('day'),period=document.getElementById('period'),mode=document.getElementById('mode'),labels=document.getElementById('labels');
for(const d of ['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday']){let o=new Option(d,d);day.add(o)}
for(const p of [...new Set(DATA.points.map(p=>p[4]))].sort())period.add(new Option(p,p));
const checks=[];
for(const a of keys){let l=document.createElement('label'),c=document.createElement('input');c.type='checkbox';c.checked=true;c.onchange=()=>{c.checked?active.add(a):active.delete(a);draw()};checks.push(c);l.append(c);let sw=document.createElement('span');sw.className='swatch';sw.style.background=color(a);l.append(sw,document.createTextNode(DATA.labels[a]));l.title='Double-click to show this activity alone';l.ondblclick=e=>{e.preventDefault();active.clear();active.add(a);checks.forEach((c,i)=>c.checked=keys[i]===a);draw()};document.getElementById('legend').append(l)}
function draw(){
 layer.replaceChildren();annotations.replaceChildren();
 let counts=new Map(),visits=new Set();
 for(const [a,x,y,d,p,v] of DATA.points){if(!active.has(a)||(day.value&&d!==day.value)||(period.value&&p!==period.value))continue;let k=JSON.stringify([a,x,y]);counts.set(k,(counts.get(k)||0)+1);visits.add(v)}
 let entries=[...counts].map(([k,n])=>[...JSON.parse(k),n]);let max=Math.max(1,...entries.map(e=>e[3]));
 // Largest first so smaller overlapping points remain visible.
 entries.sort((a,b)=>b[3]-a[3]);
 let peaks=new Map();
 for(const [a,x,y,n] of entries){
  let attrs=mode.value==='heat'?{x:(x-1)*cw,y:(y-1)*ch,width:cw,height:ch,fill:color(a),'fill-opacity':.12+.68*n/max,stroke:color(a),'stroke-width':.5}:{cx:(x-.5)*cw,cy:(y-.5)*ch,r:Math.sqrt(n/max)*Math.min(cw,ch)*.43,fill:color(a),'fill-opacity':.62,stroke:'white','stroke-width':1.5};
  let mark=node(mode.value==='heat'?'rect':'circle',attrs,layer);node('title',{},mark).textContent=`${DATA.labels[a]} | cell (${x}, ${y}) | ${n} visit${n===1?'':'s'}`;
  let previous=peaks.get(a);if(!previous||n>previous[3]||(n===previous[3]&&(y<previous[2]||(y===previous[2]&&x<previous[1]))))peaks.set(a,[a,x,y,n]);
 }
 if(labels.checked){let occupied=new Map();for(const [a,x,y,n] of peaks.values()){let k=`${x},${y}`,offset=occupied.get(k)||0;occupied.set(k,offset+1);let tx=Math.min(W-280,Math.max(8,(x-.5)*cw+12)),ty=Math.max(24,(y-.5)*ch-12)+offset*25;node('line',{x1:(x-.5)*cw,y1:(y-.5)*ch,x2:tx,y2:ty,stroke:color(a),'stroke-width':2},annotations);let t=node('text',{x:tx,y:ty,fill:color(a),'font-size':21,'font-family':'sans-serif','font-weight':700,stroke:'white','stroke-width':5,'paint-order':'stroke'},annotations);t.textContent=`${DATA.labels[a]} (${n})`;}}
 document.getElementById('status').textContent=`${visits.size} mapped visits · ${entries.length} activity/cell combinations · largest cell count: ${entries.length?max:0}`;
}
for(const c of [day,period,mode,labels])c.onchange=draw;
document.getElementById('all').onclick=()=>{keys.forEach(a=>active.add(a));checks.forEach(c=>c.checked=true);draw()};
document.getElementById('none').onclick=()=>{active.clear();checks.forEach(c=>c.checked=false);draw()};
document.getElementById('download').onclick=()=>{let copy=svg.cloneNode(true);copy.setAttribute('width',W);copy.setAttribute('height',H);let url=URL.createObjectURL(new Blob([new XMLSerializer().serializeToString(copy)],{type:'image/svg+xml'}));let a=document.createElement('a');a.href=url;a.download='activity-map.svg';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)};
draw();
</script></html>'''
    document = document.replace("__DATA__", config).replace("__PNG__", base64.b64encode(png).decode("ascii"))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(document, encoding="utf-8")
    print(f"Created {args.output}: {len(points)} visit/activity/cell selections; map {width} x {height}.")


if __name__ == "__main__":
    main()
