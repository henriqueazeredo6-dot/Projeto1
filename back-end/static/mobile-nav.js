(function () {
    var sidebar = document.querySelector(".dashboard-sidebar");
    var nav = document.querySelector(".sidebar-nav");

    if (!sidebar || !nav || document.querySelector(".mobile-options-bar")) {
        return;
    }

    var activeLink = nav.querySelector(".sidebar-link.is-active");
    var activeLabel = activeLink ? activeLink.textContent.trim() : "Menu";
    var bar = document.createElement("div");
    bar.className = "mobile-options-bar";
    bar.innerHTML = [
        '<span class="mobile-options-label">Tela: ',
        '<strong></strong>',
        "</span>",
        '<button class="mobile-nav-toggle" type="button" aria-label="Selecionar tela" aria-expanded="false">',
        '<span aria-hidden="true">...</span>',
        "</button>"
    ].join("");

    bar.querySelector("strong").textContent = activeLabel;
    document.body.appendChild(bar);

    var toggle = bar.querySelector(".mobile-nav-toggle");

    function closeMenu() {
        document.body.classList.remove("mobile-nav-open");
        toggle.setAttribute("aria-expanded", "false");
    }

    function toggleMenu() {
        var isOpen = document.body.classList.toggle("mobile-nav-open");
        toggle.setAttribute("aria-expanded", isOpen ? "true" : "false");
    }

    toggle.addEventListener("click", function (event) {
        event.stopPropagation();
        toggleMenu();
    });

    nav.addEventListener("click", function (event) {
        if (event.target.closest(".sidebar-link")) {
            closeMenu();
        }
    });

    document.addEventListener("click", function (event) {
        if (!document.body.classList.contains("mobile-nav-open")) {
            return;
        }

        if (!event.target.closest(".sidebar-nav") && !event.target.closest(".mobile-options-bar")) {
            closeMenu();
        }
    });

    document.addEventListener("keydown", function (event) {
        if (event.key === "Escape") {
            closeMenu();
        }
    });
}());
