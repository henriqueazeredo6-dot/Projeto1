(function () {
    var sidebar = document.querySelector(".dashboard-sidebar");
    var nav = document.querySelector(".sidebar-nav");

    if (!sidebar || !nav || document.querySelector(".mobile-options-bar")) {
        return;
    }

    var bar = document.createElement("div");
    var options = document.createElement("div");
    var brand = sidebar.querySelector(".sidebar-brand") || sidebar;
    var topButton = sidebar.querySelector(".mobile-menu-button");

    bar.className = "mobile-options-bar";
    bar.setAttribute("aria-label", "Navegacao principal");
    options.className = "mobile-options-scroll";

    if (!topButton) {
        topButton = document.createElement("button");
        topButton.type = "button";
        topButton.className = "mobile-menu-button";
        topButton.setAttribute("aria-label", "Abrir menu");
        topButton.innerHTML = "<span></span><span></span><span></span>";
        brand.appendChild(topButton);
    }

    topButton.setAttribute("aria-expanded", "false");

    function setMenuOpen(isOpen) {
        document.body.classList.toggle("mobile-nav-open", isOpen);
        topButton.setAttribute("aria-expanded", isOpen ? "true" : "false");
    }

    topButton.addEventListener("click", function (event) {
        event.preventDefault();
        event.stopPropagation();
        setMenuOpen(!document.body.classList.contains("mobile-nav-open"));
    });

    nav.querySelectorAll(".sidebar-link").forEach(function (link) {
        var option = link.cloneNode(true);

        option.classList.remove("sidebar-link");
        option.classList.add("mobile-option-link");
        option.removeAttribute("id");

        if (link.classList.contains("is-active")) {
            option.classList.add("is-active");
            option.setAttribute("aria-current", "page");
        }

        options.appendChild(option);
    });

    nav.addEventListener("click", function (event) {
        if (event.target.closest(".sidebar-link")) {
            setMenuOpen(false);
        }
    });

    document.addEventListener("click", function (event) {
        if (
            document.body.classList.contains("mobile-nav-open") &&
            !event.target.closest(".sidebar-nav") &&
            !event.target.closest(".mobile-menu-button")
        ) {
            setMenuOpen(false);
        }
    });

    document.addEventListener("keydown", function (event) {
        if (event.key === "Escape") {
            setMenuOpen(false);
        }
    });

    bar.appendChild(options);
    document.body.appendChild(bar);

    var activeOption = options.querySelector(".mobile-option-link.is-active");
    if (activeOption) {
        try {
            activeOption.scrollIntoView({ block: "nearest", inline: "center" });
        } catch (error) {
            options.scrollLeft = Math.max(0, activeOption.offsetLeft - 24);
        }
    }
}());
