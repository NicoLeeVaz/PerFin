"""Reproduce the link-only optional toolbox. Standard library; no network."""
import json
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def render(catalog):
    cards=[]
    for t in catalog['tools']:
        cards.append('<article data-search="'+escape((t['category']+' '+t['name']+' '+t['publisher']).lower(),quote=True)+'">'
          '<small>'+escape(t['category'])+' · '+escape(t['mode'])+'</small><h2>'+escape(t['name'])+'</h2>'
          '<p>'+escape(t['purpose'])+'</p><p><b>Source:</b> '+escape(t['publisher'])+'</p>'
          '<p><b>Use:</b> '+escape(t['action'])+'</p><p><b>License:</b> '+escape(t['license'])+'</p>'
          '<p class="status">'+escape(t['decision'])+' · File/runtime not verified</p>'
          '<a target="_blank" rel="noopener noreferrer" href="'+escape(t['url'],quote=True)+'">Open publisher / documentation ↗</a></article>')
    return '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>PerFin Optional Finance Toolbox</title><style>
body{font:16px/1.55 system-ui,sans-serif;color:#173540;background:#f3f7f7;margin:0}header,main,footer{max-width:1180px;margin:auto;padding:30px}header{padding-top:45px}h1{font-size:42px;line-height:1.1;margin:10px 0}h2{font-size:21px;margin:8px 0}a{color:#076b67}small{font-weight:700;color:#506f76}.note{padding:18px;background:#fff4dc;border-left:4px solid #ad7b22;margin:20px 0}input{padding:14px;font:inherit;width:100%;border:1px solid #9ab2b5;border-radius:6px;box-sizing:border-box}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(285px,1fr));gap:18px}article{padding:23px;background:white;border:1px solid #d7e2e4;border-radius:9px}article p{font-size:14px;margin:12px 0}.status{font-size:12px!important;background:#edf5f4;padding:8px}article[hidden]{display:none}footer{font-size:13px}button{font:inherit;padding:8px 12px;cursor:pointer}@media print{input,button{display:none}.grid{display:block}article{break-inside:avoid;margin:12px 0}body{background:white}}
</style><header><small>PERFIN / OPTIONAL EXTRAS / RESEARCHED 2026-11-05</small><h1>Finance toolbox</h1>
<p>Mortgage payoff, loan comparisons, savings, retirement and household planning. Choose only the extras you want.</p>
<div class="note"><b>Catalog inclusion is not installation or approval.</b> Publisher pages were reviewed; downloadable binaries and native Excel behavior were not. All extras start disabled. Download only a blank template, test it with invented values, then keep your working copy local. Store add-ins and online sheets are separate online choices.</div>
<p><a href="README.md">Local registration instructions</a> · <a href="acceptance.md">Math and privacy checks</a> · <a href="catalog.json">Machine-readable catalog</a></p>
<label for="search">Find by topic, provider or tool</label><input id="search" placeholder="Mortgage, loan, savings, Microsoft, community…"><p id="count" aria-live="polite"></p>
<button onclick="window.print()">Print / save PDF</button></header><main><div class="grid">'''+''.join(cards)+'''</div></main>
<footer>No external scripts, fonts, images or automatic network requests. Clicking a source opens its website. This page does not accept financial data or calculate results. PerFin remains the ledger; optional tools are separate what-if workbooks.</footer>
<script>const cards=[...document.querySelectorAll('article')];const input=document.getElementById('search');function filter(){let n=0;const q=input.value.toLowerCase().trim();cards.forEach(c=>{c.hidden=!c.dataset.search.includes(q);if(!c.hidden)n++});document.getElementById('count').textContent=n+' of '+cards.length+' tools'}input.addEventListener('input',filter);filter();</script></html>'''


if __name__=='__main__':
    catalog=json.loads((ROOT/'catalog.json').read_text(encoding='utf-8'))
    (ROOT/'index.html').write_text(render(catalog),encoding='utf-8')
