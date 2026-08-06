# -*- coding: utf-8 -*-
import json, os
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
with open(os.path.join(root,'cache_annonces_maroc.json'),'r',encoding='utf-8') as f:
    cache=json.load(f)
queries = [
    ('Vision Business Consulting','Senior Business Intelligence Developer'),
    ('GEC _ Global Experts Consulting','Consultant Chef de Projet Hub d\'Intégration'),
    ('IFCAR SOLUTIONS','Senior Manager LAB/FT'),
]
for comp,title in queries:
    found=False
    for c in cache:
        if comp.lower() in (c.get('entite') or '').lower() and title.split()[0].lower() in (c.get('poste') or '').lower():
            print(comp,'|',title,'->',c.get('url'))
            found=True
            break
    if not found:
        print('Not found in cache for',comp,'|',title)
import os
out = { 'matches': [] }
for comp,title in queries:
    for c in cache:
        if comp.lower() in (c.get('entite') or '').lower() and title.split()[0].lower() in (c.get('poste') or '').lower():
            out['matches'].append({'company': comp, 'title': title, 'url': c.get('url')})
            break
with open(os.path.join(os.path.dirname(root),'outputs','maroc_new_matches.json'),'w',encoding='utf-8') as f:
    import json
    os.makedirs(os.path.join(os.path.dirname(root),'outputs'),exist_ok=True)
    json.dump(out,f,ensure_ascii=False,indent=2)
print('Wrote outputs/maroc_new_matches.json')
