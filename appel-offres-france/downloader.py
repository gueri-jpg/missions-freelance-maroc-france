"""Téléchargement best-effort des DCE via Playwright (Chromium headless).

Les plateformes de dématérialisation (PLACE / marches-publics.gouv.fr,
AWS-France, etc.) génèrent souvent la liste des pièces en JavaScript — un
simple `requests.get` ne suffit pas, d'où l'usage de Playwright pour rendre
la page avant d'en extraire les liens.

Règles de sécurité et de conformité (section 6 du cahier des charges) :
- Ne JAMAIS contourner une authentification. Si une page de connexion est
  détectée, on s'arrête et on marque "connexion requise" en conservant le
  lien pour un téléchargement manuel par l'utilisateur.
- Repli systématique en cas d'échec ou d'absence de document identifiable :
  "téléchargement manuel — voir lien".
- Exclusion des documents génériques (guides, CGU, FAQ, dépôt de pli).
- Respect de robots.txt et délai minimal entre requêtes vers un même hôte.
"""
from __future__ import annotations

import logging
import time
import urllib.robotparser
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urljoin, urlparse

import config
from extractor import is_generic_document

logger = logging.getLogger(__name__)

DOCUMENT_EXTENSIONS = (".pdf", ".docx", ".doc", ".zip")

LOGIN_INDICATORS = (
    "mot de passe", "identifiant", "se connecter", "connexion",
    "login", "password", "authentification",
)

STATUT_TELECHARGE = "téléchargé"
STATUT_CONNEXION_REQUISE = "connexion requise"
STATUT_MANUEL = "téléchargement manuel — voir lien"
STATUT_ERREUR = "erreur de téléchargement — voir lien"

_robots_cache: dict[str, urllib.robotparser.RobotFileParser | None] = {}
_last_request_time: dict[str, float] = {}


@dataclass
class DownloadResult:
    status: str
    url: str
    files: list[Path] = field(default_factory=list)
    note: str = ""


def _robots_allowed(url: str) -> bool:
    """Vérifie robots.txt pour l'hôte de `url` (best-effort — si robots.txt
    est inaccessible, on autorise par défaut plutôt que de bloquer tout le
    pipeline sur une erreur réseau annexe non bloquante)."""
    parsed = urlparse(url)
    host = f"{parsed.scheme}://{parsed.netloc}"
    if host not in _robots_cache:
        rp: urllib.robotparser.RobotFileParser | None = urllib.robotparser.RobotFileParser()
        rp.set_url(urljoin(host, "/robots.txt"))
        try:
            rp.read()
        except Exception:
            rp = None
        _robots_cache[host] = rp
    rp = _robots_cache[host]
    if rp is None:
        return True
    try:
        return rp.can_fetch(config.USER_AGENT, url)
    except Exception:
        return True


def _throttle(url: str) -> None:
    host = urlparse(url).netloc
    last = _last_request_time.get(host)
    now = time.monotonic()
    if last is not None:
        elapsed = now - last
        if elapsed < config.REQUEST_DELAY_SECONDS:
            time.sleep(config.REQUEST_DELAY_SECONDS - elapsed)
    _last_request_time[host] = time.monotonic()


def _looks_like_login_page(page) -> bool:
    """Détection best-effort d'une page de connexion : champ mot de passe
    présent, ou plusieurs mots-clés évocateurs dans le texte visible."""
    try:
        if page.locator("input[type=password]").count() > 0:
            return True
    except Exception:
        pass
    try:
        body_text = (page.locator("body").inner_text(timeout=5000) or "").lower()
    except Exception:
        body_text = ""
    hits = sum(1 for kw in LOGIN_INDICATORS if kw in body_text)
    return hits >= 2


def _collect_document_links(page, base_url: str) -> list[str]:
    """Extrait les liens vers documents pertinents (PDF/DOCX/ZIP) de la page
    rendue, en excluant les documents génériques (guides, CGU...)."""
    hrefs: list[str] = []
    try:
        anchors = page.locator("a").all()
    except Exception:
        anchors = []
    for a in anchors:
        try:
            href = a.get_attribute("href")
        except Exception:
            href = None
        if not href:
            continue
        lower = href.lower().split("?")[0]
        if not any(lower.endswith(ext) for ext in DOCUMENT_EXTENSIONS):
            continue
        full_url = urljoin(base_url, href)
        filename = urlparse(full_url).path.rsplit("/", 1)[-1]
        if is_generic_document(filename):
            continue
        hrefs.append(full_url)

    seen: set[str] = set()
    unique: list[str] = []
    for h in hrefs:
        if h not in seen:
            seen.add(h)
            unique.append(h)
    return unique


def download_dce(url: str, dest_dir: Path, reference: str = "avis") -> DownloadResult:
    """Tente de télécharger les pièces du DCE depuis `url` (lien profil
    acheteur / avis). Retourne toujours un DownloadResult explicite — jamais
    d'exception qui interromprait le pipeline pour un seul avis en échec."""
    if not url:
        return DownloadResult(status=STATUT_MANUEL, url="", note="Aucun lien disponible")

    if not _robots_allowed(url):
        logger.info("robots.txt interdit l'accès à %s — repli manuel", url)
        return DownloadResult(status=STATUT_MANUEL, url=url, note="robots.txt interdit l'automatisation")

    _throttle(url)

    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("Playwright n'est pas installé (voir requirements.txt)") from exc

    dest_dir.mkdir(parents=True, exist_ok=True)
    downloaded: list[Path] = []

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            # Ajouter notre identifiant à la SUITE de l'UA réel du navigateur
            # (plutôt que de le remplacer) : reste honnête/transparent (le nom
            # du crawler est bien présent, cf. bonnes pratiques façon
            # Googlebot) sans casser la cohérence de fingerprint du navigateur
            # — plusieurs plateformes de dématérialisation servent un contenu
            # dégradé (page de connexion générique) dès que l'UA ne correspond
            # plus exactement à un vrai profil de navigateur.
            probe_page = browser.new_context().new_page()
            real_ua = probe_page.evaluate("navigator.userAgent")
            probe_page.context.close()
            identified_ua = f"{real_ua} {config.USER_AGENT}"

            context = browser.new_context(user_agent=identified_ua, accept_downloads=True)
            page = context.new_page()

            # `url` pointe parfois directement vers un fichier téléchargeable
            # (ex. lien RC direct PLACE/Maximilien) plutôt que vers une page
            # HTML à parcourir. Dans ce cas Chromium/Playwright rapportent la
            # navigation elle-même comme "échouée" ("Download is starting"),
            # même si le téléchargement démarre correctement — même situation
            # que pour les liens de documents individuels ci-dessous, mais ici
            # sur l'URL d'entrée. On le détecte en tentant de récupérer un
            # download avant de retomber sur le flux HTML classique.
            try:
                with page.expect_download(timeout=5000) as dl_info:
                    try:
                        page.goto(url, timeout=30000, wait_until="networkidle")
                    except Exception as goto_exc:
                        if "download" not in str(goto_exc).lower():
                            raise
                download = dl_info.value
                suggested = download.suggested_filename or f"{reference}_direct.pdf"
                target = dest_dir / suggested
                download.save_as(target)
                browser.close()
                return DownloadResult(status=STATUT_TELECHARGE, url=url, files=[target])
            except PlaywrightTimeoutError:
                pass  # pas de téléchargement direct -> page HTML classique, flux normal ci-dessous
            except Exception as exc:
                browser.close()
                logger.warning("Navigation impossible vers %s : %s", url, exc)
                return DownloadResult(status=STATUT_MANUEL, url=url, note=f"Navigation impossible : {exc}")

            if _looks_like_login_page(page):
                browser.close()
                return DownloadResult(status=STATUT_CONNEXION_REQUISE, url=url, note="Authentification requise — non contournée")

            doc_links = _collect_document_links(page, url)
            if not doc_links:
                browser.close()
                return DownloadResult(status=STATUT_MANUEL, url=url, note="Aucun document identifiable automatiquement")

            for i, doc_url in enumerate(doc_links):
                _throttle(doc_url)
                try:
                    with page.expect_download(timeout=15000) as dl_info:
                        # Naviguer directement vers une URL de fichier déclenche
                        # un téléchargement natif du navigateur : Chromium/
                        # Playwright rapportent alors la navigation elle-même
                        # comme "échouée" (le document ne s'affiche jamais),
                        # même si le téléchargement démarre correctement et
                        # que l'event "download" est bien émis. On ignore donc
                        # cette erreur de navigation spécifique ici et on
                        # récupère le téléchargement via dl_info.value.
                        try:
                            page.goto(doc_url, timeout=15000)
                        except Exception as goto_exc:
                            if "download" not in str(goto_exc).lower():
                                raise
                    download = dl_info.value
                    suggested = download.suggested_filename or f"{reference}_{i}.pdf"
                    target = dest_dir / suggested
                    download.save_as(target)
                    downloaded.append(target)
                except Exception as exc:
                    logger.warning("Téléchargement échoué pour %s : %s", doc_url, exc)
                    continue

            browser.close()
    except Exception as exc:
        logger.error("Erreur Playwright pour %s : %s", url, exc)
        return DownloadResult(status=STATUT_ERREUR, url=url, note=str(exc))

    if not downloaded:
        return DownloadResult(status=STATUT_MANUEL, url=url, note="Liens détectés mais téléchargement impossible")

    return DownloadResult(status=STATUT_TELECHARGE, url=url, files=downloaded)
