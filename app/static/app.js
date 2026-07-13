// Anbieter-Auswahl füllt Host/Port automatisch vor.
(function () {
    const select = document.getElementById("provider-select");
    const hostInput = document.getElementById("host-input");
    const portInput = document.getElementById("port-input");
    if (!select || !hostInput || !portInput) return;

    function applyPreset() {
        const opt = select.options[select.selectedIndex];
        const host = opt.getAttribute("data-host") || "";
        const port = opt.getAttribute("data-port") || "993";
        if (host) hostInput.value = host;
        portInput.value = port;
    }

    select.addEventListener("change", applyPreset);
    if (!hostInput.value) applyPreset();
})();
