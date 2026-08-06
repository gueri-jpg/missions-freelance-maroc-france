# -*- coding: utf-8 -*-
import json, os
from copy import deepcopy
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
import sys
sys.path.insert(0, root)
import linkedin_sourcing_regie as LSR

cache_path = os.path.join(root, 'cache_annonces_maroc.json')
vues_path = os.path.join(root, 'annonces_vues.json')
if not os.path.exists(cache_path) or not os.path.exists(vues_path):
    print('missing files')
    raise SystemExit(1)
with open(cache_path, 'r', encoding='utf-8') as f:
    annonces = json.load(f)
with open(vues_path, 'r', encoding='utf-8') as f:
    vues = json.load(f)
# Copy vues so we don't alter the file
vues_copy = deepcopy(vues)
items = LSR.classify_all(annonces, LSR.dt.date.today().isoformat())
# Apply similarity only to non-ECARTEE
LSR._appliquer_similarite([a for a in items if a['verdict'] != 'ÉCARTÉE'])
# Process country to get nouveaux list (it also updates the vues_copy)
items_proc = LSR.process_country('maroc', annonces, vues_copy, LSR.dt.date.today().isoformat())
# process_country returns items list; but it printed nouveaux internally.
# We can reconstruct nouveaux as items where 'nouveau' True and verdict != ECARTEE
nouveaux = [a for a in items_proc if a.get('nouveau') and a.get('verdict') != 'ÉCARTÉE']
print(f"{len(nouveaux)} nouveaux (verdict != ÉCARTÉE)")
for i,a in enumerate(nouveaux,1):
    u = (a.get('url') or '').split('?')[0].rstrip('/')
    sv = a.get('sim_verdict')
    print(f"{i}. {u} | title: {a.get('poste')!s} | company: {a.get('entite')!s} | sim_verdict: {sv}")
