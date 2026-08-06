# -*- coding: utf-8 -*-
"""Mesure avant/après pour les correctifs de classifier.py.

Usage : python mesure_avant_apres.py
"""
from classifier import detect_domaine

POSITIVES = [
    "Chef de projet Infrastructure / Gouvernance projets",
    "PMO Infra / Production bancaire – Freelance (REF03)",
    "Directeur de projet – domaine référentiel / urbanisation SI",
    "Chef de projet SI – Agile / Jira / Confluence",
    "Responsable applicatif / Chef de projet SI – BPM",
    "Chef de projet SI / Chef de projet AMOA",
    "Chef de projet Infrastructure Réseaux",
    "Chef de projet SIRH Data Migration",
    "PMO Chef de projet Simulation ALM",
    "Chef de projet Sinistres",
    "PMO Senior – Programme de transformation IT / bascule CMDB",
    "Chargé de recette / homologation SI bancaire",
    "PMO cyber senior – programme sécurité bancaire",
]
NEGATIVES = [
    "Ingénieur Infrastructure Cloud",
    "Administrateur réseau senior",
    "Expert Cybersécurité SOC",
    "Ingénieur DevOps Kubernetes",
    "Architecte Infrastructure",
    "Technicien support N1",
    "Test Manager SI bancaire",
    "Testeur automaticien",
    "Développeur Java Spring",
    "Data Scientist / MLOps",
]


def classify_titles(titles):
    results = []
    for titre in titles:
        coeur, dok, hors, pilotage = detect_domaine(titre, "")
        verdict = "ECARTE" if hors else "GARDÉ"
        results.append((titre, coeur, dok, hors, verdict))
    return results


def main():
    print("=== OFFRES ATTENDUES DANS LE PÉRIMÈTRE ===")
    pos = classify_titles(POSITIVES)
    for titre, coeur, dok, hors, verdict in pos:
        print(f"{verdict:5} | coeur={coeur} dok={dok} hors={hors} | {titre}")
    keep = sum(1 for _, _, _, hors, _ in pos if not hors)
    print(f"Conservées attendues : {keep}/{len(pos)}")

    print("\n=== OFFRES ATTENDUES HORS PÉRIMÈTRE ===")
    neg = classify_titles(NEGATIVES)
    for titre, coeur, dok, hors, verdict in neg:
        print(f"{verdict:5} | coeur={coeur} dok={dok} hors={hors} | {titre}")
    kept_neg = sum(1 for _, _, _, hors, _ in neg if not hors)
    print(f"Faussement conservées : {kept_neg}/{len(neg)}")


if __name__ == '__main__':
    main()
