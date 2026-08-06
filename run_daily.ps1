# =====================================================================
#  RUNNER quotidien du scraper (missions regie / banque).
#  Appele par la tache planifiee via run_daily.bat  (ne pas lancer les deux).
#
#  Test manuel RAPIDE (sans re-scraper) :
#     powershell -ExecutionPolicy Bypass -File run_daily.ps1 "reclass france"
#  Run REEL complet :
#     powershell -ExecutionPolicy Bypass -File run_daily.ps1
#
#  NB : ASCII uniquement. Windows PowerShell 5.1 lit les .ps1 en ANSI ;
#       des accents sans BOM peuvent casser le parsing du script.
# =====================================================================

param([string]$Mode = "both")

$ErrorActionPreference = "Continue"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

$dir     = "c:\Users\PAVILION\Downloads\A explorer\A explorer"
$logDir  = Join-Path $dir "logs"
$py      = "C:\Users\PAVILION\AppData\Local\Programs\Python\Python313\python.exe"
$majFile = Join-Path $dir "_DERNIERE_MAJ.txt"

if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Force -Path $logDir | Out-Null }
# Journal HORODATE par run : deux runs ne se verrouillent jamais mutuellement.
$log = Join-Path $logDir ("run_" + (Get-Date -Format 'yyyy-MM-dd_HHmmss') + ".log")

# Ecritures .NET (atomiques) + try/catch : un verrou ne fait jamais planter le run.
function Log($m) {
    try { [IO.File]::AppendAllText($log, ("[{0}] {1}`r`n" -f (Get-Date -Format 'HH:mm:ss'), $m), [Text.Encoding]::UTF8) } catch {}
}
function Maj($t) {
    try { [IO.File]::WriteAllText($majFile, $t, (New-Object Text.UTF8Encoding $true)) } catch {}
}

function Load-DotEnv {
    param([string]$path)
    if (-not (Test-Path $path)) { return }

    foreach ($line in Get-Content $path | Where-Object { $_.Trim() -and -not $_.Trim().StartsWith('#') }) {
        if ($line -match '^[^#]*=') {
            $parts = $line -split '=', 2
            $name = $parts[0].Trim()
            $value = $parts[1].Trim().Trim('"').Trim("'")
            if ($name) { Set-Item -Path "env:$name" -Value $value }
        }
    }
}

function Send-ExcelNotification {
    param(
        [string]$xlsxFile,
        [string]$status
    )

    $smtpServer = $env:SMTP_SERVER
    $smtpPort   = if ($env:SMTP_PORT) { [int]$env:SMTP_PORT } else { 587 }
    $smtpUser   = $env:SMTP_USER
    $smtpPass   = $env:SMTP_PASS
    $from       = if ($env:FROM_EMAIL) { $env:FROM_EMAIL } else { "rgueriatou@gmail.com" }
    $to         = if ($env:TUTOR_EMAILS) { $env:TUTOR_EMAILS } else { "Amina.chevalier@cfconsulting.ma,abderrahmane.elbaghdadi@cfconsulting.ma,rgueriatou@gmail.com" }
    $cc         = if ($env:CC_EMAILS) { $env:CC_EMAILS } else { "rgueriatou@gmail.com" }

    if (-not ($smtpServer -and $smtpUser -and $smtpPass -and $from -and $to)) {
        Log "Envoi mail ignoré : variables SMTP manquantes (SMTP_SERVER, SMTP_USER, SMTP_PASS, FROM_EMAIL, TUTOR_EMAILS)."
        return
    }

    if (-not (Test-Path $xlsxFile)) {
        Log "Envoi mail ignoré : fichier introuvable $xlsxFile"
        return
    }

    try {
        $securePass = ConvertTo-SecureString $smtpPass -AsPlainText -Force
        $cred = New-Object System.Management.Automation.PSCredential($smtpUser, $securePass)

        $subject = "Sourcing missions - mise à jour du $status"
        $body = @"
Bonjour,

Le run quotidien a généré le fichier suivant :
$xlsxFile

Statut : $status

Cordialement,
Automatisation Sourcing
"@

        $toList = @()
        if ($to) { $toList = ($to -split '[,;]' | ForEach-Object { $_.Trim() } | Where-Object { $_ }) }
        $ccList = @()
        if ($cc) { $ccList = ($cc -split '[,;]' | ForEach-Object { $_.Trim() } | Where-Object { $_ }) }

        $mailParams = @{
            From       = $from
            To         = $toList
            Subject    = $subject
            Body       = $body
            SmtpServer = $smtpServer
            Port       = $smtpPort
            UseSsl     = $true
            Credential = $cred
            Attachments = $xlsxFile
        }
        if ($ccList.Count) { $mailParams.Cc = $ccList }

        Send-MailMessage @mailParams
        $logMessage = "Mail envoyé à " + ($toList -join ", ")
        if ($ccList.Count) { $logMessage += " avec CC " + ($ccList -join ", ") }
        Log $logMessage
    } catch {
        Log ("Erreur envoi mail : " + $_.Exception.Message)
    }
}

Load-DotEnv (Join-Path $dir ".env")
Set-Location $dir
Log "=== Demarrage (mode=$Mode) ==="

# Signal IMMEDIAT : on voit tout de suite que ca tourne.
$start = Get-Date -Format "dd/MM/yyyy HH:mm"
Maj "MISE A JOUR EN COURS depuis $start ...`r`n(l'Excel sera pret dans quelques minutes)"

# --- Scraper Python ----------------------------------------------------------
$exitCode = 1
$out = ""
try {
    $pyArgs = @($Mode -split '\s+' | Where-Object { $_ })
    $out = (& $py "linkedin_sourcing_regie.py" @pyArgs 2>&1 | Out-String)
    $exitCode = $LASTEXITCODE
    try { [IO.File]::AppendAllText($log, $out, [Text.Encoding]::UTF8) } catch {}
    Log "Python termine (exit=$exitCode)"
} catch {
    Log ("ERREUR Python : " + $_.Exception.Message)
}

# --- Signal de fin : _DERNIERE_MAJ.txt (TOUJOURS ecrit) ----------------------
$line = ""
try {
    $mm = [regex]::Matches($out, '===>[^\r\n]*')
    if ($mm.Count) { $line = $mm[$mm.Count - 1].Value.Trim() }
} catch {}
if (-not $line) {
    if ($exitCode -eq 0) { $line = "Scraping OK (voir dossier logs)." }
    else { $line = "ECHEC du scraping (exit=$exitCode) - voir dossier logs." }
}
$stamp = Get-Date -Format "dd/MM/yyyy HH:mm"
$xlsx  = "Sourcing_regie_banque.xlsx"
$xlsxPath = Join-Path $dir $xlsx
Maj "DERNIERE MISE A JOUR : $stamp`r`n$line`r`nFichier : $xlsx"
Log "_DERNIERE_MAJ.txt ecrit"

if ($exitCode -eq 0) {
    Send-ExcelNotification -xlsxFile $xlsxPath -status "réussie"
} else {
    Send-ExcelNotification -xlsxFile $xlsxPath -status "échouée"
}

# --- Notification Windows ----------------------------------------------------
# IMPORTANT : il faut un AppId DEJA ENREGISTRE dans Windows, sinon le toast est
# cree mais JAMAIS affiche (c'etait le bug : "Sourcing.Regie.Banque" n'existe pas).
#
# 2026-07-19 : le toast partait bien ("Toast affiche" dans le journal) mais
# l'utilisatrice ne voyait rien. Cause : un toast normal s'affiche ~7 s puis
# disparait ; la tache finit vers 08:5x, souvent en son absence. Corrige par :
#   - scenario "reminder"  -> le toast RESTE a l'ecran jusqu'a ce qu'on le ferme
#   - ExpirationTime +48 h -> il persiste dans le Centre de notifications
#   - Tag/Group            -> une seule entree, remplacee a chaque run
try {
    [void][Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime]
    [void][Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom, ContentType = WindowsRuntime]

    $titre   = "Sourcing missions - mise a jour du $stamp"
    # URI du fichier pour le bouton "Ouvrir" (antislashs -> slashs, espaces -> %20)
    $xlsxUri = (Join-Path $dir $xlsx).Replace('\', '/').Replace(' ', '%20')
    $xmlTxt = @"
<toast scenario="reminder">
  <visual><binding template="ToastGeneric">
    <text>$titre</text>
    <text>$line</text>
    <text>Fichier : $xlsx</text>
  </binding></visual>
  <actions>
    <action content="Ouvrir le fichier" arguments="file:///$xlsxUri" activationType="protocol"/>
    <action content="OK" arguments="dismiss" activationType="system"/>
  </actions>
</toast>
"@
    $xml = New-Object Windows.Data.Xml.Dom.XmlDocument
    $xml.LoadXml($xmlTxt)
    $toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
    $toast.Tag   = "sourcing"
    $toast.Group = "sourcing"
    $toast.ExpirationTime = [DateTimeOffset]::Now.AddHours(48)
    $appId = "{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe"
    [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($appId).Show($toast)
    Log "Toast affiche (persistant 48h)"
} catch {
    Log ("Toast indisponible : " + $_.Exception.Message)
}

Log "=== Fin (exit=$exitCode) ==="
Write-Output ("Termine - " + $log)
exit $exitCode
