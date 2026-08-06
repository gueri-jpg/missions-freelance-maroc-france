# -*- coding: utf-8 -*-
import json, os
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
cache_path = os.path.join(root, 'cache_annonces_maroc.json')
vues_path = os.path.join(root, 'annonces_vues.json')
if not os.path.exists(cache_path) or not os.path.exists(vues_path):
    print('missing files')
    raise SystemExit(1)
with open(cache_path, 'r', encoding='utf-8') as f:
    cache = json.load(f)
with open(vues_path, 'r', encoding='utf-8') as f:
    vues = json.load(f)

candidates = [c for c in cache if ((c.get('url') or '').split('?')[0].rstrip('/') not in vues.keys())]
print(f'Candidates count: {len(candidates)}')
for i,c in enumerate(candidates[:5],1):
    print(f'{i}. { (c.get("url") or "") } | {c.get("poste")!s} | {c.get("entite")!s}')

try:
    import sys
    sys.path.insert(0, root)
    import similarite as S
except Exception as e:
    print('cannot import similarite:', e)
    raise SystemExit(0)

print('\nRunning similarite.similarite (may use cached embeddings/Gemini).')
res = S.similarite(candidates, use_embeddings=True)

hors = []
for i,r in enumerate(res):
    v = S.verdict_similarite(r)
    if v == 'HORS_PERIMETRE (similarité)':
        c = candidates[i]
        u = (c.get('url') or '').split('?')[0].rstrip('/')
        hors.append((u, c.get('poste'), c.get('entite'), r.get('score_global'), r.get('raison')))

print(f'\nHORS_PERIMETRE count: {len(hors)}')
for i,h in enumerate(hors,1):
    print(f'{i}. {h[0]} | title: {h[1]!s} | company: {h[2]!s} | score: {h[3]} | reason: {h[4]!s}')
