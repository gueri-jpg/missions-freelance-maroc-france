# -*- coding: utf-8 -*-
"""
Sources AUTRES que LinkedIn — les cabinets de placement publient leurs missions
en régie sur leur propre ATS (souvent plus complet et plus frais que LinkedIn).

Chaque collecteur renvoie une liste d'« annonces » au MÊME format que celles
issues de LinkedIn (poste, entite, ville, url, date_pub, texte, emploi_label,
nb_candidats_txt, cloturee, republication, source) afin d'alimenter la même
couche classifier.py.

Avantage clé : un flux ATS ne liste que les postes OUVERTS -> cloturee = False
est FIABLE (contrairement à LinkedIn où la clôture n'est pas exposée).
"""

import re
import json
import html
import requests
from bs4 import BeautifulSoup

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
HDR = {"User-Agent": UA, "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8"}

MOROCCO_HINTS = ["casablanca", "maroc", "morocco", "rabat", "tanger",
                 "marrakech", "casa-anfa", "settat"]
FRANCE_HINTS = ["paris", "france", "île-de-france", "ile-de-france", "lyon",
                "vitrolles", "lille", "nantes", "bordeaux", "toulouse"]


def _text_from_html(html):
    return BeautifulSoup(html or "", "lxml").get_text(" ", strip=True)


def _loc_of(jobposting):
    jl = (jobposting or {}).get("jobLocation")
    if isinstance(jl, list) and jl:
        jl = jl[0]
    if isinstance(jl, dict):
        addr = jl.get("address")
        if isinstance(addr, dict):
            return addr.get("addressLocality") or addr.get("addressRegion") or ""
        if isinstance(addr, str):
            return addr
    return ""


# ------------------------------------------------------ TRUSTED ADVISORS (Teamtailor)
def collect_trusted_advisors(country="maroc", max_pages=8):
    """Flux JSON public (JSON Feed) de Trusted Advisors — cabinet spécialisé
    banque à Casablanca. Ne liste que les postes ouverts."""
    hints = MOROCCO_HINTS if country == "maroc" else FRANCE_HINTS
    url = "https://jobs.trustedadvisors-group.com/jobs.json"
    out, seen, pages = [], set(), 0
    while url and pages < max_pages:
        try:
            r = requests.get(url, headers=HDR, timeout=25)
            r.raise_for_status()
            d = r.json()
        except Exception as e:
            print(f"  ! Trusted Advisors ({e})")
            break
        for it in d.get("items", []):
            jp = it.get("_jobposting", {}) or {}
            loc = _loc_of(jp)
            title = it.get("title", "")
            texte = _text_from_html(it.get("content_html", ""))
            # Filtre pays sur la localisation STRUCTURÉE (précis) ; à défaut,
            # sur le titre uniquement (pas le corps, trop bruyant).
            ref = loc.lower() if loc else title.lower()
            if not any(h in ref for h in hints):
                continue
            u = it.get("url", "")
            if u in seen:
                continue
            seen.add(u)
            iso = str(jp.get("datePosted") or it.get("date_published") or "")[:10]
            out.append({
                "poste": title,
                "entite": "Trusted Advisors",
                "ville": loc or ("Casablanca" if country == "maroc" else ""),
                "url": u,
                "date_pub": iso if re.match(r"\d{4}-\d{2}-\d{2}", iso) else "",
                "posted_relative": "",
                "texte": texte,
                "emploi_label": ("Freelance" if "freelance" in title.lower()
                                 else ""),
                "nb_candidats_txt": "",
                "cloturee": False,          # flux = uniquement postes ouverts
                "open_confirme": True,      # ouverture CONFIRMÉE par le flux ATS
                "republication": "",
                "source": "Trusted Advisors (ATS)",
            })
        url = d.get("next_url")
        pages += 1
    print(f"  Trusted Advisors : {len(out)} missions {country}.")
    return out


# ------------------------------------------------------------- WERIN GROUP (WordPress)
def collect_werin(country="maroc", max_jobs=40):
    """Job board WordPress (WP Job Manager) de Werin Group — missions data/BI/IT
    chez grands comptes à Casablanca. Chaque page /jobs/ porte un JSON-LD."""
    if country != "maroc":
        return []
    base = "https://www.weringroup.ma"
    try:
        r = requests.get(base + "/offres-de-missions-freelance/", headers=HDR, timeout=25)
        slugs = sorted(set(re.findall(r"/jobs/([a-z0-9\-]+)/", r.text)))
    except Exception as e:
        print(f"  ! Werin Group ({e})")
        return []
    out = []
    for slug in slugs[:max_jobs]:
        try:
            rr = requests.get(f"{base}/jobs/{slug}/", headers=HDR, timeout=20)
            soup = BeautifulSoup(rr.text, "lxml")
        except Exception:
            continue
        jp = None
        for s in soup.select("script[type='application/ld+json']"):
            try:
                d = json.loads(s.string or "{}")
            except Exception:
                continue
            if isinstance(d, dict) and d.get("@type") == "JobPosting":
                jp = d
                break
        if not jp:
            continue
        iso = str(jp.get("datePosted") or "")[:10]
        out.append({
            "poste": html.unescape(jp.get("title") or slug.replace("-", " ").title()),
            "entite": "Werin Group",
            "ville": _loc_of(jp) or "Casablanca",
            "url": f"{base}/jobs/{slug}/",
            "date_pub": iso if re.match(r"\d{4}-\d{2}-\d{2}", iso) else "",
            "posted_relative": "",
            "texte": _text_from_html(jp.get("description", "")),
            "emploi_label": "Freelance",
            "nb_candidats_txt": "",
            "cloturee": False,
            "open_confirme": True,       # job board = offres en cours
            "republication": "",
            "source": "Werin Group (ATS)",
        })
    print(f"  Werin Group : {len(out)} missions {country}.")
    return out


# --------------------------------------------------------------- FREE-WORK (France)
def collect_free_work(country="france", max_pages=6):
    """API REST publique de Free-Work (job board freelance FR, format Hydra).
    contracts=contractor => on ne récupère QUE des missions freelance/régie.
    Expose le TJM (dailySalary), la durée, la ville, le mode (remote)."""
    if country != "france":
        return []
    base = "https://www.free-work.com/api/job_postings"
    hdr = dict(HDR)
    hdr["Accept"] = "application/ld+json"
    out, seen = [], set()
    # Secteur + ROLE. On cherchait le secteur SEUL : une mission intitulee
    # "PMO - pilotage de projets strategiques IT" (l'offre etalon) n'etait
    # trouvee que si le mot "banque" trainait dans son resume. On ajoute donc
    # les roles de pilotage ; le filtre bancaire du classifieur trie ensuite.
    # ("monétique" retire : le paiement est hors perimetre, c'etait 100% jete.)
    for kw in ["banque", "bancaire", "finance de marché", "crédit", "assurance",
               "PMO", "chef de projet IT", "pilotage de projet",
               "conduite du changement", "chef de projet transformation",
               # Recherche pilotee par les POLES + COMPETENCES (2026-07-22),
               # mais en ROLE + POLE (pas le pole seul, sinon on ramene les
               # traders sur "salle des marches", les testeurs sur "monetique"...
               # cf. remarque utilisatrice : resserrer sur CE QUI EST INCLUS).
               "AMOA banque", "business analyst banque",
               "AMOA salle des marchés", "AMOA finance de marché",
               "AMOA monétique", "chef de projet monétique",
               "AMOA gestion d'actifs", "AMOA asset management",
               "AMOA KYC conformité", "business analyst risques bancaires",
               "AMOA ALM", "AMOA bancassurance", "AMOA SIRH",
               "AMOA cash management", "chef de projet AMOA banque"]:
        page = 1
        while page <= max_pages:
            params = {"contracts": "contractor", "searchKeywords": kw,
                      "itemsPerPage": 30, "page": page}
            try:
                r = requests.get(base, params=params, headers=hdr, timeout=25)
                d = r.json()
            except Exception as e:
                print(f"  ! Free-Work ({e})")
                break
            members = d.get("hydra:member", [])
            if not members:
                break
            for it in members:
                slug = it.get("slug", "")
                if not slug or slug in seen:
                    continue
                seen.add(slug)
                loc = it.get("location") or {}
                city = (loc.get("city") or loc.get("addressLocality")
                        or loc.get("label") or "") if isinstance(loc, dict) else ""
                comp = (it.get("company") or {}).get("name", "") if isinstance(it.get("company"), dict) else ""
                desc = (_text_from_html(it.get("description", "")) + " "
                        + _text_from_html(it.get("candidateProfile", "")))
                iso = str(it.get("publishedAt") or it.get("createdAt") or "")[:10]
                tjm = it.get("dailySalary") or it.get("maxDailySalary") or it.get("minDailySalary")
                duree = ""
                if it.get("durationValue"):
                    duree = f"{it['durationValue']} {it.get('durationPeriod', '')}".strip()
                if tjm:
                    duree = (duree + f" · TJM {tjm}").strip(" ·")
                job = it.get("job") or {}
                jslug = job.get("slug") if isinstance(job, dict) else ""
                url = f"https://www.free-work.com/fr/tech-it/{jslug or 'consultant'}/job-mission/{slug}"
                out.append({
                    "poste": html.unescape(it.get("title", "")),
                    "entite": comp or "Free-Work (ESN)",
                    "ville": city,
                    "url": url,
                    "date_pub": iso if re.match(r"\d{4}-\d{2}-\d{2}", iso) else "",
                    "posted_relative": "",
                    # contracts=contractor => on annonce explicitement la régie
                    "texte": "Mission freelance en régie. " + desc,
                    "emploi_label": "Freelance",
                    "nb_candidats_txt": "",
                    "cloturee": False,
                    "open_confirme": True,
                    "republication": "",
                    "duree": duree or "NC",
                    "source": "Free-Work (ATS)",
                })
            if len(members) < 30:
                break
            page += 1
    print(f"  Free-Work : {len(out)} missions {country}.")
    return out


# ---------------------------------------------------- GEC-ZOHO (SPA, navigateur headless)
# Indices de pays pour router une mission GEC (le board GEC mêle Maroc ET France).
GEC_FR_HINTS = ["paris", "france", "seine", "yvelines", "hauts-de", "val-de",
                "essonne", "marne", "lyon", "lille", "nantes", "bordeaux",
                "toulouse", "défense", "defense", "courbevoie", "nanterre",
                "ile-de", "île-de", "rennes", "strasbourg", "vitrolles"]
GEC_MA_HINTS = ["casa", "maroc", "morocco", "rabat", "tanger", "tétouan",
                "tetouan", "marrakech", "settat", "anfa", "mohammedia",
                "kenitra", "fès", "fes", "oujda", "agadir", "salé", "sale"]
_GEC_CACHE = None   # rendu headless mis en cache : une seule lecture par process


def _gec_country(ville):
    v = (ville or "").lower()
    if any(h in v for h in GEC_FR_HINTS):
        return "france"
    if any(h in v for h in GEC_MA_HINTS):
        return "maroc"
    return "maroc"      # défaut : GEC est basé à Casablanca


def _gec_render(max_detail):
    """Rend la SPA Zoho de GEC et lit chaque fiche. Renvoie TOUTES les missions
    (Maroc + France mélangés), avec leur vraie ville."""
    from playwright.sync_api import sync_playwright
    cards = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(user_agent=UA)
        page.goto("https://gec-groupe.zohorecruit.com/jobs/Careers", timeout=45000)
        try:
            page.wait_for_selector("a[href*='/jobs/Careers/']", timeout=20000)
        except Exception:
            pass
        page.wait_for_timeout(2500)
        cards = page.eval_on_selector_all(
            "a[href*='/jobs/Careers/']",
            "els => els.map(e => ({t: e.innerText.trim(), h: e.href}))")
        browser.close()

    uniq, seen = [], set()
    for c in cards:
        h, t = c.get("h", ""), (c.get("t") or "").strip()
        if re.search(r"/Careers/\d+", h) and t and h not in seen:
            seen.add(h)
            uniq.append((h, t.split("\n")[0].strip()[:120]))

    def _field(body, *labels):
        for lab in labels:
            m = re.search(re.escape(lab) + r"\s*\n\s*([^\n]+)", body)
            if m:
                return m.group(1).strip()
        return ""

    out = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(user_agent=UA)
        for h, titre in uniq[:max_detail]:
            desc, secteur, ville, emploi, iso = "", "", "", "", ""
            try:
                page.goto(h, timeout=40000)
                page.wait_for_timeout(1400)
                body = page.inner_text("body")
                emploi = _field(body, "Type d'emploi", "Type d’emploi")
                ville = _field(body, "Ville")
                secteur = _field(body, "Secteur d'activité", "Secteur d’activité")
                d = _field(body, "Date ouverte")
                m = re.match(r"(\d{2})/(\d{2})/(\d{4})", d or "")
                if m:
                    iso = f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
                dm = re.search(r"Description du poste\s*\n(.+)", body, re.S)
                desc = (dm.group(1) if dm else body).strip()
            except Exception:
                pass
            out.append({
                "poste": titre,
                "entite": "GEC _ Global Experts Consulting",
                "ville": ville or "Casablanca",
                "url": h,
                "date_pub": iso,
                "posted_relative": "",
                "texte": f"Mission en régie. Secteur : {secteur}. {desc or titre}",
                "emploi_label": emploi or "Freelance",
                "nb_candidats_txt": "",
                "cloturee": False,
                "open_confirme": True,
                "republication": "",
                "source": "GEC-Zoho (headless)",
            })
        browser.close()
    return out


def collect_gec_zoho(country="maroc", max_detail=80):
    """GEC (Global Experts Consulting) — job board Zoho Recruit rendu en JS
    (navigateur headless requis). GEC = cabinet de placement EN RÉGIE, banque.
    Le board mêle missions MAROC et FRANCE : on route chaque mission d'après sa
    vraie ville, et on ne renvoie que celles du pays demandé.
    Rendu une seule fois par process (cache), puis filtré par pays."""
    global _GEC_CACHE
    if country not in ("maroc", "france"):
        return []
    try:
        import playwright.sync_api  # noqa: F401  (vérifie la dispo)
    except ImportError:
        print("  ! GEC-Zoho : Playwright absent "
              "(pip install playwright && python -m playwright install chromium)")
        return []
    if _GEC_CACHE is None:
        try:
            _GEC_CACHE = _gec_render(max_detail)
        except Exception as e:
            print(f"  ! GEC-Zoho headless ({e})")
            _GEC_CACHE = []
    out = [dict(a) for a in _GEC_CACHE if _gec_country(a["ville"]) == country]
    print(f"  GEC-Zoho : {len(out)} missions {country}.")
    return out


# ---------------------------------------------------------------- REGISTRE
COLLECTORS = {
    "trusted_advisors": collect_trusted_advisors,
    "werin_group": collect_werin,
    "free_work": collect_free_work,
    "gec_zoho": collect_gec_zoho,
    # extensible : capfi, adaptive_it... (à ajouter quand l'endpoint est fiable)
}


def collect_all_ats(country="maroc"):
    """Interroge toutes les sources ATS et renvoie la liste d'annonces fusionnée.
    Un échec de source n'interrompt pas les autres."""
    annonces = []
    for name, fn in COLLECTORS.items():
        try:
            annonces += fn(country)
        except Exception as e:
            print(f"  ! source ATS '{name}' indisponible : {e}")
    return annonces


if __name__ == "__main__":
    import json
    res = collect_all_ats("maroc")
    print(f"\nTOTAL ATS maroc : {len(res)}")
    for a in res[:12]:
        print(f"  - {a['poste'][:60]:60s} | {a['ville']} | {a['date_pub']}")
