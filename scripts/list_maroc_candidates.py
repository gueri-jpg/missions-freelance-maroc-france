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
cache_urls = [(c.get('url') or '').split('?')[0].rstrip('/') for c in cache]
vues_urls = set(vues.keys())
new_items = [c for c in cache if ((c.get('url') or '').split('?')[0].rstrip('/') not in vues_urls)]
print(f"Found {len(new_items)} candidate new offers in cache_annonces_maroc.json not in annonces_vues.json")
for i, c in enumerate(new_items, start=1):
    u = (c.get('url') or '').split('?')[0].rstrip('/')
    print(f"{i}. {u} | title: {c.get('poste')!s} | company: {c.get('entite')!s}")
# Optionally, try to run similarity estimation if similarite is available
try:
    import similarite as S
    print('\nRunning similarity estimation (may use cache, no external Gemini).')
    res = S.similarite(new_items, use_embeddings=True)
    for i, r in enumerate(res, start=1):
        print(f"{i}. verdict: {S.verdict_similarite(r)} | score: {r.get('score_global')} | reason: {r.get('raison')}")
except Exception as e:
    print('similarity module not available or failed:', e)
