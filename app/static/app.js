// Anbieter-Auswahl: Host/Port vorfüllen und passenden Hinweis anzeigen.
(function () {
    const select = document.getElementById("provider-select");
    const hostInput = document.getElementById("host-input");
    const portInput = document.getElementById("port-input");
    const hintBox = document.getElementById("provider-hint");
    if (!select || !hostInput || !portInput) return;

    const hints = {
        gmail:
            "Gmail braucht ein App-Passwort (normale Passwörter blockiert Google): " +
            "1) Im Google-Konto die Bestätigung in zwei Schritten aktivieren. " +
            "2) Auf myaccount.google.com/apppasswords ein App-Passwort erstellen. " +
            "3) Dieses 16-stellige Passwort hier eintragen.",
        gmx:
            "Bei GMX zuerst IMAP erlauben: GMX-Webmail → Einstellungen (Zahnrad) → " +
            "POP3/IMAP → POP3 und IMAP Zugriff erlauben aktivieren. " +
            "Mit Zwei-Faktor-Anmeldung: anwendungsspezifisches Passwort erstellen.",
        webde:
            "Bei WEB.DE zuerst IMAP erlauben: Webmail → Einstellungen → POP3/IMAP aktivieren.",
        ionos:
            "Das Postfach-Passwort verwenden (das aus Webmail/Apple Mail), " +
            "nicht das IONOS-Kundenkonto-Passwort.",
        outlook:
            "Outlook/Microsoft-Konten brauchen meist ein App-Passwort: " +
            "account.microsoft.com → Sicherheit → Zwei-Faktor aktivieren → App-Passwort erstellen.",
    };

    function applyPreset() {
        const opt = select.options[select.selectedIndex];
        const host = opt.getAttribute("data-host") || "";
        const port = opt.getAttribute("data-port") || "993";
        if (host) hostInput.value = host;
        portInput.value = port;
        if (hintBox) {
            const hint = hints[select.value] || "";
            hintBox.textContent = hint;
            hintBox.style.display = hint ? "block" : "none";
        }
    }

    select.addEventListener("change", applyPreset);
    applyPreset();
})();
