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
        hotmail:
            "Hotmail/Live sind Microsoft-Konten und brauchen meist ein App-Passwort: " +
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

// Passwort anzeigen/verbergen: Augen-Icon an allen Passwortfeldern.
(function () {
    const EYE =
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
        '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7z"/><circle cx="12" cy="12" r="3"/></svg>';
    const EYE_OFF =
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
        '<path d="m3 3 18 18"/>' +
        '<path d="M10.6 5.1C11 5 11.5 5 12 5c6.5 0 10 7 10 7a17.6 17.6 0 0 1-2.9 3.9M6.6 6.6C4 8.4 2 12 2 12s3.5 7 10 7c1.4 0 2.7-.3 3.9-.8"/>' +
        '<path d="M9.9 9.9a3 3 0 0 0 4.2 4.2"/></svg>';

    document.querySelectorAll('input[type="password"]').forEach(function (input) {
        const wrap = document.createElement("span");
        wrap.className = "pw-wrap";
        input.parentNode.insertBefore(wrap, input);
        wrap.appendChild(input);

        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "pw-toggle";
        btn.setAttribute("aria-label", "Passwort anzeigen");
        btn.tabIndex = -1;
        btn.innerHTML = EYE;
        btn.addEventListener("click", function () {
            const show = input.type === "password";
            input.type = show ? "text" : "password";
            btn.innerHTML = show ? EYE_OFF : EYE;
            btn.setAttribute("aria-label", show ? "Passwort verbergen" : "Passwort anzeigen");
        });
        wrap.appendChild(btn);
    });
})();
