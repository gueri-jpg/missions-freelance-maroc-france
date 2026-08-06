# -*- coding: utf-8 -*-
"""Envoi du mail de notification quotidien — équivalent Python de
`Send-ExcelNotification` dans run_daily.ps1, pour tourner sous GitHub
Actions (pas d'accès à `Send-MailMessage` de PowerShell côté Linux).

Mêmes variables d'environnement que la version PowerShell (SMTP_SERVER,
SMTP_PORT, SMTP_USER, SMTP_PASS, FROM_EMAIL, TUTOR_EMAILS, CC_EMAILS) —
définies comme secrets GitHub Actions plutôt que lues depuis .env."""
import os
import smtplib
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


def envoyer_notification(xlsx_path, statut, resume=""):
    smtp_server = os.environ.get("SMTP_SERVER")
    smtp_port = int(os.environ.get("SMTP_PORT") or "587")
    smtp_user = os.environ.get("SMTP_USER")
    smtp_pass = os.environ.get("SMTP_PASS")
    from_email = os.environ.get("FROM_EMAIL") or smtp_user
    to_emails = os.environ.get("TUTOR_EMAILS", "")
    cc_emails = os.environ.get("CC_EMAILS", "")

    if not (smtp_server and smtp_user and smtp_pass and from_email and to_emails):
        print("  [mail] Envoi ignoré : variables SMTP manquantes "
              "(SMTP_SERVER, SMTP_USER, SMTP_PASS, FROM_EMAIL, TUTOR_EMAILS).")
        return

    to_list = [e.strip() for e in to_emails.replace(";", ",").split(",") if e.strip()]
    cc_list = [e.strip() for e in cc_emails.replace(";", ",").split(",") if e.strip()]

    msg = MIMEMultipart()
    msg["From"] = from_email
    msg["To"] = ", ".join(to_list)
    if cc_list:
        msg["Cc"] = ", ".join(cc_list)
    msg["Subject"] = f"Sourcing missions - mise à jour du {statut}"
    corps = (
        "Bonjour,\n\n"
        "Le run quotidien (GitHub Actions) a mis à jour le fichier de sourcing.\n\n"
        f"{resume}\n\n"
        f"Statut : {statut}\n\n"
        "Cordialement,\nAutomatisation Sourcing"
    )
    msg.attach(MIMEText(corps, "plain", "utf-8"))

    if xlsx_path and os.path.exists(xlsx_path):
        with open(xlsx_path, "rb") as f:
            piece = MIMEApplication(f.read(), Name=os.path.basename(xlsx_path))
        piece["Content-Disposition"] = f'attachment; filename="{os.path.basename(xlsx_path)}"'
        msg.attach(piece)

    destinataires = to_list + cc_list
    try:
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(from_email, destinataires, msg.as_string())
        log = f"  [mail] Envoyé à {', '.join(to_list)}"
        if cc_list:
            log += f" avec CC {', '.join(cc_list)}"
        print(log)
    except Exception as e:
        print(f"  [mail] ERREUR envoi : {e}")
