"""Collecte des avis de consultation depuis le Portail Marocain des Marchés
Publics (PMMP) — https://www.marchespublics.gov.ma.

Constaté empiriquement : ce portail tourne sur le même moteur "profil
acheteur" (PRADO postback, conventions d'identifiants
`ctl0_CONTENU_PAGE_...`) que PLACE/Maximilien en France
(collector_place.py) — même famille de logiciel, thème d'affichage
différent (table classique ici, cartes côté France). La recherche
multicritères est accessible sans compte, mais un WAF bloque les requêtes
dépourvues d'en-têtes de navigateur réalistes (403 constaté avec un
User-Agent générique, 200 dès qu'un User-Agent + Accept-Language de
navigateur sont envoyés) — d'où l'usage de Playwright plutôt que `requests`.

Catégorie ciblée : domaineActivite=3.19 = "Services de technologies de
l'information et télécommunications" (équivalent du CPV 72 pour ce
référentiel, trouvée en énumérant les liens de catégorie de la page
d'accueil publique). Le portail expose un paramètre `&EnCours` (consultations
dont la date limite n'est pas dépassée), mais le combiner avec
`domaineActivite` casse le moteur de recherche côté serveur (testé en
direct — cf. config.py) : on interroge donc `domaineActivite=3.19` seul
(toutes dates) et `filter_classify.is_deadline_too_soon` écarte les
consultations déjà closes en aval, via la date limite réellement extraite
par ligne.
"""
from __future__ import annotations

import logging
import re
import time
from typing import Any

import requests
from playwright.sync_api import sync_playwright

import config

logger = logging.getLogger(__name__)


class MarocCollectorError(Exception):
    """Erreur de communication ou de structure inattendue pour la source PMMP."""


_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

_JS_EXTRACT_ROWS = r"""
() => {
  const rows = Array.from(document.querySelectorAll('tr')).filter(
    tr => tr.querySelector('td[headers="cons_ref"]')
  );
  return rows.map(row => {
    const q = (sel) => row.querySelector(sel);
    const text = (el) => el ? el.textContent.trim().replace(/\s+/g, ' ') : null;

    // Constaté en direct : PRADO affiche parfois un texte (potentiellement
    // tronqué) suivi d'une info-bulle cachée (classe "info-bulle") contenant
    // la version COMPLÈTE du même champ, plus un marqueur "..." (classe
    // "info-suite") — tous cachés en CSS mais présents dans le DOM, donc
    // capturés ensemble par .textContent brut, ce qui donnait "TRONQUÉ ...
    // COMPLET" (ou "X ... X" quand le texte est assez court pour ne pas être
    // tronqué). L'info-bulle est TOUJOURS la version complète quand
    // présente ; fieldText() la préfère et retombe sur le texte du
    // conteneur (marqueurs retirés) sinon.
    const fieldText = (el) => {
      if (!el) return null;
      const bulle = el.querySelector('.info-bulle');
      if (bulle) {
        const t = text(bulle);
        if (t) return t;
      }
      const clone = el.cloneNode(true);
      clone.querySelectorAll('.info-suite, .info-bulle').forEach(n => n.remove());
      return text(clone);
    };

    const refSpan = q('[id*=panelBlocIntitule] .ref');
    const objetDiv = q('[id*=panelBlocObjet]');
    const acheteurDiv = q('[id*=panelBlocDenomination]');
    const categorieDiv = q('[id*=panelBlocCategorie]');
    const procDiv = row.querySelector('[id*=type_procedure]');
    // Panneau précis plutôt que le <td> entier : celui-ci contient aussi un
    // second bloc caché (codes NUTS) avec sa propre info-bulle, sans rapport
    // avec le lieu d'exécution affiché.
    const lieuPanel = q('[id*=panelBlocLieuxExec]');

    let dateLimite = null;
    for (const el of row.querySelectorAll('td[headers="cons_dateEnd"] .cloture-line')) {
      const t = text(el);
      if (t) { dateLimite = t; break; }
    }

    let datePub = null;
    const refTd = q('td[headers="cons_ref"]');
    if (refTd) {
      for (const div of refTd.querySelectorAll(':scope > div')) {
        const t = text(div);
        if (t && /^\d{2}\/\d{2}\/\d{4}$/.test(t)) { datePub = t; break; }
      }
    }

    let detailHref = null;
    for (const a of row.querySelectorAll('a')) {
      const href = a.getAttribute('href');
      if (href && href.includes('EntrepriseDetailConsultation')) { detailHref = a.href; break; }
    }

    return {
      reference: text(refSpan),
      objet: fieldText(objetDiv),
      acheteur: fieldText(acheteurDiv),
      categorie: fieldText(categorieDiv),
      procedure: fieldText(procDiv),
      lieu: fieldText(lieuPanel),
      date_publication: datePub,
      date_limite: dateLimite,
      detail_url: detailHref,
    };
  });
}
"""

_LABEL_PREFIX_RE = re.compile(r"^(objet|acheteur public)\s*:\s*", re.IGNORECASE)
_REF_ORG_RE = re.compile(r"refConsultation=([^&]+)&orgAcronyme=([^&]+)")
_TOOLTIP_DUPLICATE_RE = re.compile(r"^(.*?)\s\.\.\.\s(.*)$", re.DOTALL)


def _clean_label(value: str | None) -> str | None:
    if not value:
        return None
    return _LABEL_PREFIX_RE.sub("", value).strip() or None


def _dedupe_tooltip_text(value: str | None) -> str | None:
    """Filet de sécurité côté Python contre le bug d'info-bulle PRADO
    (`fieldText()` dans `_JS_EXTRACT_ROWS` le corrige déjà côté extraction,
    mais cette logique JS n'est pas testable unitairement) : un texte
    "TRONQUÉ ... COMPLET" (visible potentiellement tronqué + info-bulle
    cachée, capturés ensemble) doit toujours garder la partie APRÈS le
    premier ' ... ' — c'est systématiquement la version complète, jamais
    l'inverse (constaté en direct sur une dizaine d'avis PMMP réels)."""
    if not value:
        return value
    m = _TOOLTIP_DUPLICATE_RE.match(value.strip())
    if not m:
        return value
    complete = m.group(2).strip()
    return complete or value


def _clean_date(value: str | None) -> str | None:
    """Normalise 'JJ/MM/AAAA[ HH:MM]' -> 'AAAA-MM-JJ'. Retourne None si non
    parsable — ne jamais deviner (règle d'exactitude)."""
    if not value:
        return None
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})", value.strip())
    if not m:
        return None
    day, month, year = m.groups()
    return f"{year}-{month}-{day}"


def normalize_maroc_record(raw: dict) -> dict | None:
    """Normalise une ligne PMMP vers le schéma commun. Retourne None si
    l'objet est absent (ligne d'en-tête/artefact d'extraction)."""
    objet = _dedupe_tooltip_text(_clean_label(raw.get("objet")))
    if not objet:
        return None
    reference = raw.get("reference") or "non précisé"
    detail_url = raw.get("detail_url")

    lien_dce = None
    m = _REF_ORG_RE.search(detail_url) if detail_url else None
    if m:
        ref_consultation, org_acronyme = m.groups()
        # Formulaire de demande de téléchargement du DCE — un choix
        # "anonyme" existe (constaté en direct : radio
        # EntrepriseFormulaireDemande_choixAnonyme), pas besoin de compte,
        # mais nécessite de remplir raison sociale/email et d'accepter les
        # CGU avant d'obtenir le fichier — pas un lien de fichier direct.
        # Automatisation du remplissage : voir README (non implémentée).
        lien_dce = (
            f"{config.MA_PMMP_BASE_URL}/index.php"
            f"?page=entreprise.EntrepriseDemandeTelechargementDce"
            f"&refConsultation={ref_consultation}&orgAcronyme={org_acronyme}"
        )

    return {
        "id": f"MA-{reference}" if reference != "non précisé" else f"MA-{objet[:40]}",
        "pays": "Maroc",
        "source": "PMMP",
        "reference": reference,
        "objet": objet,
        "acheteur": _dedupe_tooltip_text(_clean_label(raw.get("acheteur"))) or "non précisé",
        "type_marche": raw.get("categorie"),
        "procedure_libelle": raw.get("procedure"),
        "lieu_execution": _dedupe_tooltip_text(raw.get("lieu")),
        "date_publication": _clean_date(raw.get("date_publication")),
        "date_limite": _clean_date(raw.get("date_limite")),
        "devise": "MAD",
        "montant_estime": None,
        "url_avis": (
            f"{config.MA_PMMP_BASE_URL}/index.php{detail_url[detail_url.index('?'):]}"
            if detail_url and "?" in detail_url
            else config.MA_PMMP_SEARCH_URL_IT
        ),
        "lien_dce": lien_dce,
    }


_ESTIMATION_RE = re.compile(
    r'id="[^"]*_labelReferentielZoneText"[^>]*>\s*([\d\s,.]+)\s*<', re.IGNORECASE
)
_CAUTION_RE = re.compile(
    r'id="[^"]*_cautionProvisoire"[^>]*>\s*([\d\s,.]+)\s*MAD', re.IGNORECASE
)


def _parse_montant_mad(raw: str | None) -> float | None:
    """Parse un montant au format marocain ('354 000,00' -> 354000.0).
    Retourne None si non parsable ou si la valeur est '0,00' (constaté en
    direct : c'est la valeur par défaut du champ quand rien n'est renseigné,
    pas un vrai montant nul — ne jamais faire passer un défaut technique
    pour une donnée, même principe que le sentinel de date DGMP-CI)."""
    if not raw:
        return None
    cleaned = raw.strip().replace(" ", "").replace("\xa0", "").replace(",", ".")
    try:
        value = float(cleaned)
    except ValueError:
        return None
    return value if value > 0 else None


def fetch_consultation_details(url: str) -> dict:
    """Récupère l'estimation (montant estimatif TTC) et la caution
    provisoire depuis la page détail d'une consultation — page rendue côté
    serveur (confirmé en direct : `requests` seul suffit, sans Playwright).
    Retourne {} en cas d'échec réseau ou de structure inattendue (best
    effort — ne doit jamais interrompre l'enrichissement d'un lot pour une
    seule page défaillante)."""
    headers = {
        "User-Agent": config.USER_AGENT,
        "Accept-Language": "fr-FR,fr;q=0.9",
        "Referer": config.MA_PMMP_SEARCH_URL_IT,
    }
    try:
        resp = requests.get(url, headers=headers, timeout=config.HTTP_TIMEOUT)
    except requests.RequestException as exc:
        logger.warning("PMMP détail %s : erreur réseau (non bloquant) : %s", url, exc)
        return {}
    if not resp.ok:
        return {}

    html = resp.text
    montant_match = _ESTIMATION_RE.search(html)
    caution_match = _CAUTION_RE.search(html)

    montant = _parse_montant_mad(montant_match.group(1)) if montant_match else None
    caution = _parse_montant_mad(caution_match.group(1)) if caution_match else None

    return {
        "montant_estime": f"{montant:,.2f} MAD".replace(",", " ").replace(".", ",") if montant else None,
        "montant_estime_valeur": montant,
        "caution_provisoire": f"{caution:,.2f} MAD".replace(",", " ").replace(".", ",") if caution else None,
    }


def enrich_records_with_details(records: list[dict]) -> list[dict]:
    """Enrichit chaque avis avec montant estimatif et caution provisoire,
    en récupérant la page détail de CHAQUE avis (best-effort, jamais
    d'exception qui interromprait le lot). À appeler uniquement sur un
    ensemble déjà filtré/restreint (candidats IT retenus) — jamais sur
    l'intégralité des ~1098 avis de la catégorie, qui multiplierait les
    requêtes vers le portail sans nécessité."""
    enriched: list[dict] = []
    for i, record in enumerate(records):
        if i > 0:
            time.sleep(config.REQUEST_DELAY_SECONDS)
        details = fetch_consultation_details(record["url_avis"])
        enriched.append({**record, **details})
    return enriched


def _extract_rows_from_page(page: Any) -> list[dict]:
    """Exécute l'extraction JS avec une tentative de repli : comme pour
    collector_place.py (PRADO), un postback peut déclencher un second
    rechargement juste après qu'un état de chargement soit atteint,
    détruisant le contexte JS en plein milieu d'un evaluate()."""
    try:
        return page.evaluate(_JS_EXTRACT_ROWS)
    except Exception as exc:
        if "context was destroyed" not in str(exc).lower():
            raise
        page.wait_for_load_state("load", timeout=30000)
        page.wait_for_timeout(2500)
        return page.evaluate(_JS_EXTRACT_ROWS)


def collect(max_pages: int = 10) -> list[dict]:
    """Parcourt la catégorie "Services de technologies de l'information et
    télécommunications" (domaineActivite=3.19, toutes dates confondues — cf.
    config.py pour la raison de ne pas combiner "&EnCours" à cette requête)
    et retourne les avis normalisés, tous pages confondues (jusqu'à
    `max_pages`, taille de page portée à 500 quand disponible).

    Les consultations déjà closes sont incluses dans le résultat brut : c'est
    filter_classify.is_deadline_too_soon (appliqué en aval, comme pour les
    autres sources) qui les écarte via la date limite réellement extraite par
    ligne — pas un filtre serveur. Aucun filtrage par mots-clés IT côté
    client n'est nécessaire ici : la catégorie interrogée EST le domaine IT
    du référentiel officiel marocain (pas de recall à élargir)."""
    results: list[dict] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent=_UA, locale="fr-FR")
        page = context.new_page()

        try:
            page.goto(config.MA_PMMP_SEARCH_URL_IT, timeout=45000, wait_until="load")
        except Exception as exc:
            browser.close()
            raise MarocCollectorError(f"Erreur de navigation PMMP : {exc}") from exc

        page.wait_for_timeout(2500)

        # NB : le sélecteur de taille de page (#...listePageSizeTop) a été
        # testé et écarté — le changer déclenche un postback qui réinitialise
        # le filtre domaineActivite côté serveur (page 1 revient vide après
        # sélection, reproduit systématiquement). On reste donc sur la
        # pagination par défaut (10/page) et on borne le nombre de pages via
        # `max_pages` plutôt que la taille de page — plus lent (~8-10s/page)
        # mais fiable. `max_pages=110` couvre l'intégralité des ~1098 avis
        # actuellement recensés dans cette catégorie (toutes dates).
        try:
            total_text = page.locator("#ctl0_CONTENU_PAGE_resultSearch_nombreElement").inner_text(timeout=5000)
            logger.info("PMMP : %s avis au total dans la catégorie IT (toutes dates)", total_text.strip())
        except Exception:
            pass

        for page_num in range(1, max_pages + 1):
            raw_rows = _extract_rows_from_page(page)
            logger.info("PMMP : page %d, %d ligne(s) brute(s)", page_num, len(raw_rows))
            for raw in raw_rows:
                normalized = normalize_maroc_record(raw)
                if normalized is not None:
                    results.append(normalized)

            next_link = page.locator(
                'a[title="Aller à la page suivante"], '
                'a:has(img[title="Aller à la page suivante"])'
            )
            if next_link.count() == 0:
                logger.info("PMMP : pas de lien 'page suivante' après la page %d — arrêt (fin de liste)", page_num)
                break
            try:
                next_link.first.click()
                page.wait_for_load_state("load", timeout=30000)
                page.wait_for_timeout(2500)
            except Exception as exc:
                # Un échec de clic/navigation n'est PAS forcément la fin de la
                # liste (constaté en direct : un run s'est arrêté silencieusement
                # à la page 31/110 sans le signaler, avant ce correctif) — on
                # retente une fois après une pause plus longue avant d'abandonner
                # réellement, et on log dans tous les cas pour ne plus jamais
                # avoir une pagination tronquée sans trace.
                logger.warning(
                    "PMMP : échec navigation page suivante après la page %d (%s) — nouvelle tentative...",
                    page_num, exc,
                )
                try:
                    page.wait_for_timeout(5000)
                    next_link.first.click()
                    page.wait_for_load_state("load", timeout=30000)
                    page.wait_for_timeout(2500)
                except Exception as exc2:
                    logger.error(
                        "PMMP : abandon de la pagination après la page %d (%s) — "
                        "résultat partiel (%d avis collectés sur cette page et les précédentes)",
                        page_num, exc2, len(results),
                    )
                    break

        browser.close()

    logger.info("PMMP : %d avis normalisés (catégorie IT, toutes dates)", len(results))
    return results
