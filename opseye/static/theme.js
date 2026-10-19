// Theme switch of the status page: system, light or dark. The choice is
// remembered in localStorage when the browser allows it.
(function () {
  var select = document.getElementById("theme");
  var key = "ops-eye-theme";

  function apply(value) {
    if (value === "auto") {
      document.documentElement.removeAttribute("data-theme");
    } else {
      document.documentElement.setAttribute("data-theme", value);
    }
  }

  try {
    var saved = localStorage.getItem(key) || "auto";
    select.value = saved;
    apply(saved);
  } catch (e) {
    // Storage is blocked: the page follows the system theme.
  }

  select.addEventListener("change", function () {
    try {
      localStorage.setItem(key, select.value);
    } catch (e) {
      // Not remembered for the next visit, but applied below.
    }
    apply(select.value);
  });
})();
