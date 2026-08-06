# -*- coding: utf-8 -*-
import os, json, sys
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, root)
from linkedin_sourcing_regie import classify_all, _appliquer_similarite
import linkedin_sourcing_regie as LSR

with open(os.path.join(root,'cache_annonces_maroc.json'),'r',encoding='utf-8') as f:
    cache = json.load(f)
# Titles/companies observed in the run log
targets = [
    ('Vision Business Consulting','Senior Business Intelligence Developer'),
    ('GEC _ Global Experts Consulting','Consultant Chef de Projet Hub d\'Intégration'),
    ('IFCAR SOLUTIONS','Senior Manager LAB/FT'),
]
matches = []
for c in cache:
    ent = (c.get('entite') or '').lower()
    poste = (c.get('poste') or '').lower()
    for comp,title in targets:
        if comp.lower() in ent and title.split()[0].lower() in poste:
            matches.append(c)

print('Found matches:', len(matches))
# Classify these matches
items = classify_all(matches, LSR.dt.date.today().isoformat())
_appliquer_similarite([a for a in items if a['verdict'] != 'ÉCARTÉE'])
for a in items:
    print(a.get('url'), '|', a.get('poste'), '| sim_verdict=', a.get('sim_verdict'))
