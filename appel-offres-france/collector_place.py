"""Collecte complémentaire depuis les profils acheteurs "AWS-Achat/Atexo"
(PLACE — marches-publics.gouv.fr — et Maximilien — marches.maximilien.fr,
portail des marchés publics d'Île-de-France), utilisés par une grande partie
des administrations françaises comme profil acheteur.

Pourquoi cette source : BOAMP n'est obligatoire qu'au-delà de certains
seuils ; en-dessous, un acheteur en procédure adaptée peut publier
uniquement sur son profil acheteur (souvent PLACE ou une plateforme
régionale comme Maximilien) sans jamais passer par BOAMP. Ces opportunités
sont invisibles pour collector_boamp.py.

Ni PLACE ni Maximilien n'exposent d'API publique — la recherche "Toutes les
consultations" est un formulaire HTML classique, piloté ici via Playwright
(recherche par mot-clé + filtre "Procédure adaptée", tous deux disponibles
sans compte). Constaté empiriquement : les deux plateformes tournent sur le
même logiciel (mêmes routes ?page=Entreprise.EntrepriseAdvancedSearch, mêmes
identifiants de champ ctl0_CONTENU_PAGE_...) — un seul jeu de fonctions
suffit, paramétré par domaine.

Bonus constaté : le lien "Télécharger le RC" présent sur de nombreux
résultats pointe vers un PDF accessible SANS authentification (vérifié en
direct : .../index.php?page=Entreprise.EntrepriseDownloadReglement&id=...
retourne un PDF valide sans session/cookie) — contrairement à la plupart
des profils acheteurs qui exigent un compte pour tout document du DCE.
"""
from __future__ import annotations

import logging
from typing import Any

from playwright.sync_api import sync_playwright

import config

logger = logging.getLogger(__name__)

# Plateformes connues tournant sur le même logiciel de profil acheteur.
PLATFORMS = {
    "PLACE": "https://www.marches-publics.gouv.fr",
    "Maximilien": "https://marches.maximilien.fr",
}

# Mots-clés IT à rechercher (sous-ensemble ciblé de config.MOTS_CLES_IT_FORTS,
# adapté à un moteur de recherche par mot-clé plutôt qu'à une analyse de
# texte — un mot par requête pour rester dans la sémantique "contient" du
# formulaire ; la précision finale est assurée par filter_classify, pas par
# ce choix de mots-clés).
DEFAULT_KEYWORDS = [
    "logiciel", "applicatif", "progiciel", "sirh",
    "système d'information", "cybersécurité",
    "site internet", "site web", "application mobile",
    "base de données", "power bi", "business intelligence", "talend",
    "développement web", "développement mobile", "développement logiciel",
    "développement informatique",
]

_APOSTROPHE_VARIANTS = str.maketrans({"’": "'", "‘": "'", "´": "'", "`": "'"})

_MOIS = {
    "janv": 1, "fevr": 2, "févr": 2, "mars": 3, "avr": 4, "mai": 5, "juin": 6,
    "juil": 7, "aout": 8, "août": 8, "sept": 9, "oct": 10, "nov": 11, "dec": 12, "déc": 12,
}

_JS_EXTRACT_ROWS = r"""
() => {
  const rows = Array.from(document.querySelectorAll('.item_consultation'));
  return rows.map(row => {
    const q = (sel) => row.querySelector(sel);
    const text = (el) => el ? el.textContent.trim().replace(/\s+/g, ' ') : null;
    const procAbbr = q('.cons_procedure abbr');
    const categorie = q('.cons_categorie span');
    const refDiv = q('.objet-line .small.pull-left');
    const intituleSpan = q('.objet-line .truncate span');
    const objetSpan = q('[id*=panelBlocObjet] .small span');
    const orgSpan = q('[id*=panelBlocDenomination] .small');
    const lieu = q('.lieux-exe span span');
    const dateMinDay = q('.date-min .day span');
    const dateMinMonth = q('.date-min .month span');
    const dateMinYear = q('.date-min .year span');
    const dateEndDay = q('.cloture-line .day span');
    const dateEndMonth = q('.cloture-line .month span');
    const dateEndYear = q('.cloture-line .year span');
    let rcHref = null;
    for (const a of row.querySelectorAll('a')) {
      if (a.href && a.href.includes('EntrepriseDownloadReglement')) { rcHref = a.href; break; }
    }
    let consultHref = null;
    for (const a of row.querySelectorAll('a')) {
      if (a.href && a.href.includes('/entreprise/consultation/')) { consultHref = a.href; break; }
    }
    return {
      procedure_abbr: text(procAbbr),
      procedure_libelle: procAbbr ? procAbbr.getAttribute('data-original-title') : null,
      categorie: text(categorie),
      reference: text(refDiv),
      intitule: text(intituleSpan),
      objet: text(objetSpan),
      organisme: text(orgSpan),
      lieu: text(lieu),
      date_pub: [text(dateMinDay), text(dateMinMonth), text(dateMinYear)],
      date_limite: [text(dateEndDay), text(dateEndMonth), text(dateEndYear)],
      consult_url: consultHref,
      rc_url: rcHref,
    };
  });
}
"""


class PlaceError(Exception):
    """Erreur de communication avec une plateforme de type PLACE/Maximilien."""


def _parse_month(month_str: str | None) -> int | None:
    if not month_str:
        return None
    key = month_str.strip().rstrip(".").lower()
    if key in _MOIS:
        return _MOIS[key]
    for k, v in _MOIS.items():
        if key.startswith(k) or k.startswith(key):
            return v
    return None


def _parse_place_date(parts: list[str | None] | None) -> str | None:
    """Convertit [jour, mois_abrégé_fr, année] extraits du DOM en date ISO.
    Retourne None si une des trois composantes est absente/non
    interprétable — ne jamais deviner (règle d'exactitude)."""
    if not parts or len(parts) != 3:
        return None
    day_s, month_s, year_s = parts
    if not day_s or not month_s or not year_s:
        return None
    month = _parse_month(month_s)
    if month is None:
        return None
    try:
        return f"{int(year_s):04d}-{month:02d}-{int(day_s):02d}"
    except ValueError:
        return None


def normalize_place_record(raw: dict, source_label: str = "PLACE") -> dict:
    """Normalise une ligne de résultat au même schéma que
    collector_boamp.normalize_boamp_record — permet de réutiliser
    filter_classify.filter_and_classify() sans logique dédiée."""
    categorie = (raw.get("categorie") or "").strip().upper()
    return {
        "id": f"{source_label.upper()}-{raw['reference']}" if raw.get("reference") else None,
        "source": source_label,
        "date_publication": _parse_place_date(raw.get("date_pub")),
        "date_limite": _parse_place_date(raw.get("date_limite")),
        "acheteur": raw.get("organisme"),
        "departement": raw.get("lieu"),
        "objet": raw.get("objet") or raw.get("intitule"),
        "descripteur_libelle": [],
        "procedure_libelle": raw.get("procedure_libelle"),
        "type_procedure": "PROCEDURE_ADAPTE" if raw.get("procedure_abbr") == "MAPA" else None,
        "procedure_categorise": None,
        "type_marche": [categorie] if categorie else [],
        "nature_categorise": "appeloffre/standard",
        "nature_categorise_libelle": None,
        "cpv": [],
        "montant_estime": None,
        "devise": None,
        "accord_cadre": False,
        # Le lien RC direct (PDF public, sans authentification, vérifié en
        # direct) est plus utile que la simple page de consultation quand il
        # est disponible — priorité au document exploitable.
        "lien_profil_acheteur": raw.get("rc_url") or raw.get("consult_url"),
        "lien_rc_direct": raw.get("rc_url"),
        "criteres_attribution": None,
        "duree": None,
        "url_avis": raw.get("consult_url"),
        "donnees_raw": raw,
    }


_SEARCH_MAX_ATTEMPTS = 3
# Constaté en direct : le délai nécessaire après un postback dépend de la
# taille du jeu de résultats (recherche floue -> parfois des centaines de
# lignes malgré un mot-clé précis, ex. "power bi" -> 193 résultats). 900ms
# suffisait pour un petit jeu de résultats mais provoquait un contexte JS
# détruit de façon reproductible sur les gros ; 2500ms est fiable dans les
# deux cas testés.
_SETTLE_DELAY_MS = 2500


def _search_keyword_once(page: Any, search_url: str, keyword: str, max_pages: int = 5) -> list[dict]:
    page.goto(search_url, timeout=30000, wait_until="networkidle")
    page.fill("#ctl0_CONTENU_PAGE_AdvancedSearch_keywordSearch", keyword)
    page.wait_for_load_state("networkidle", timeout=30000)
    page.select_option("#ctl0_CONTENU_PAGE_AdvancedSearch_procedureType", "3")  # Procédure adaptée
    page.click("#ctl0_CONTENU_PAGE_AdvancedSearch_lancerRecherche")
    page.wait_for_load_state("networkidle", timeout=30000)
    # Le formulaire PRADO déclenche parfois un second rechargement juste
    # après que "networkidle" soit atteint (postback en deux temps) — sans
    # cette pause, evaluate() peut tomber sur un contexte JS détruit en
    # plein milieu de cette seconde navigation.
    page.wait_for_timeout(_SETTLE_DELAY_MS)

    try:
        page.select_option("#ctl0_CONTENU_PAGE_resultSearch_listePageSizeTop", "20")
        page.wait_for_load_state("networkidle", timeout=30000)
        page.wait_for_timeout(_SETTLE_DELAY_MS)
    except Exception:
        pass  # pas de sélecteur affiché -> tient déjà sur une seule page

    rows: list[dict] = []
    for _ in range(max_pages):
        rows.extend(page.evaluate(_JS_EXTRACT_ROWS))
        next_link = page.locator(
            'a[data-original-title="Aller à la page suivante"], '
            'a:has(span[data-original-title="Aller à la page suivante"])'
        )
        if next_link.count() == 0:
            break
        try:
            next_link.first.click()
            page.wait_for_load_state("networkidle", timeout=30000)
            page.wait_for_timeout(_SETTLE_DELAY_MS)
        except Exception:
            break

    return [row for row in rows if _row_matches_keyword(row, keyword)]


def _row_matches_keyword(raw: dict, keyword: str) -> bool:
    """Vérifie côté client que le mot-clé apparaît bien dans l'objet ou
    l'intitulé. Constaté empiriquement : la recherche PLACE/Maximilien
    traite un mot-clé multi-mots comme un OU entre mots individuels (ex.
    'power bi' remonte ~200 résultats en procédure adaptée, la plupart sans
    rapport — probablement matchés sur 'bi' seul) — le mode 'recherche
    exacte' ne change rien à ce comportement, et le guillemetage littéral
    casse la recherche (aucun résultat). Seule une vérification a
    posteriori sur le texte réellement affiché élimine ce bruit."""
    text = f"{raw.get('objet') or ''} {raw.get('intitule') or ''}".lower().translate(_APOSTROPHE_VARIANTS)
    return keyword.lower().translate(_APOSTROPHE_VARIANTS) in text


def _search_keyword(page: Any, search_url: str, keyword: str, max_pages: int = 5) -> list[dict]:
    """Enveloppe _search_keyword_once avec des ré-essais, pour absorber les
    aléas réseau/serveur résiduels (le principal cas de contexte JS détruit —
    délai de rechargement sous-estimé sur les gros jeux de résultats — est
    déjà couvert par _SETTLE_DELAY_MS)."""
    last_exc: Exception | None = None
    for attempt in range(_SEARCH_MAX_ATTEMPTS):
        try:
            return _search_keyword_once(page, search_url, keyword, max_pages=max_pages)
        except Exception as exc:
            last_exc = exc
            logger.warning(
                "%s : tentative %d/%d échouée pour %r (%s)",
                search_url, attempt + 1, _SEARCH_MAX_ATTEMPTS, keyword, exc,
            )
    raise last_exc if last_exc else RuntimeError("échec inattendu")


def collect(
    keywords: list[str] | None = None,
    max_records: int = 200,
    base_url: str = PLATFORMS["PLACE"],
    source_label: str = "PLACE",
) -> list[dict]:
    """Collecte les avis en procédure adaptée pour une liste de mots-clés
    (défaut : DEFAULT_KEYWORDS) sur une plateforme de type PLACE/Maximilien,
    dédoublonnés par référence. Best-effort : scraping d'un formulaire
    public, sans compte. Une erreur sur un mot-clé n'interrompt pas la
    collecte des autres (résilience)."""
    keywords = keywords or DEFAULT_KEYWORDS
    search_url = f"{base_url}/?page=Entreprise.EntrepriseAdvancedSearch&searchAnnCons&type=multicriteres"
    seen: dict[str, dict] = {}

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(user_agent=config.USER_AGENT)
            for keyword in keywords:
                if len(seen) >= max_records:
                    break
                try:
                    rows = _search_keyword(page, search_url, keyword)
                except Exception as exc:
                    logger.warning("%s : échec recherche pour %r (%s) — ignoré", source_label, keyword, exc)
                    continue
                for raw in rows:
                    normalized = normalize_place_record(raw, source_label=source_label)
                    if normalized["id"] and normalized["id"] not in seen:
                        seen[normalized["id"]] = normalized
            browser.close()
    except Exception as exc:
        raise PlaceError(f"Erreur lors de la collecte {source_label} : {exc}") from exc

    return list(seen.values())[:max_records]


def collect_all_platforms(keywords: list[str] | None = None, max_records_per_platform: int = 200) -> list[dict]:
    """Collecte sur toutes les plateformes connues (PLATFORMS). Une
    plateforme en échec n'empêche pas la collecte des autres."""
    results: list[dict] = []
    for label, base_url in PLATFORMS.items():
        try:
            results.extend(collect(keywords, max_records_per_platform, base_url=base_url, source_label=label))
        except PlaceError as exc:
            logger.error("Échec collecte %s (non bloquant) : %s", label, exc)
    return results
