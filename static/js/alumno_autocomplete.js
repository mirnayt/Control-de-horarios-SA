(function () {
  function debounce(fn, ms) {
    var t;
    return function () {
      var ctx = this, args = arguments;
      clearTimeout(t);
      t = setTimeout(function () { fn.apply(ctx, args); }, ms);
    };
  }

  function bind(root) {
    var input = root.querySelector(".alumno-ac-q");
    var hidden = root.querySelector(".alumno-ac-id");
    var list = root.querySelector(".alumno-ac-list");
    if (!input || !hidden || !list) return;

    var url = root.getAttribute("data-url");
    var navigate = root.getAttribute("data-navigate") || "";
    var activos = root.getAttribute("data-activos") || "";
    var adultos = root.getAttribute("data-adultos") || "";

    function hide() { list.hidden = true; list.innerHTML = ""; }

    function choose(item) {
      hidden.value = item.id;
      input.value = item.text;
      hide();
      if (navigate) {
        var dest = navigate + (navigate.indexOf("?") >= 0 ? "&" : "?") + "alumno_id=" + item.id;
        window.location.href = dest;
      }
    }

    var search = debounce(function () {
      var q = (input.value || "").trim();
      if (q.length < 1) {
        hide();
        return;
      }
      var qs = "q=" + encodeURIComponent(q);
      if (activos) qs += "&activos=1";
      if (adultos) qs += "&adultos=1";
      fetch(url + "?" + qs, { headers: { "X-Requested-With": "XMLHttpRequest" } })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          var results = data.results || [];
          list.innerHTML = "";
          if (!results.length) {
            var empty = document.createElement("li");
            empty.className = "alumno-ac-empty";
            empty.textContent = "Sin resultados";
            list.appendChild(empty);
            list.hidden = false;
            return;
          }
          results.forEach(function (item) {
            var li = document.createElement("li");
            li.className = "alumno-ac-item";
            var extra = [item.tipo, item.sucursal, item.telefono].filter(Boolean).join(" · ");
            li.innerHTML = "<strong>#" + item.id + " " + item.text + "</strong>" +
              (extra ? "<span>" + extra + "</span>" : "");
            li.addEventListener("mousedown", function (e) {
              e.preventDefault();
              choose(item);
            });
            list.appendChild(li);
          });
          list.hidden = false;
        })
        .catch(function () { hide(); });
    }, 200);

    input.addEventListener("input", function () {
      if (!input.value.trim()) hidden.value = "";
      search();
    });
    input.addEventListener("focus", function () {
      if ((input.value || "").trim()) search();
    });
    input.addEventListener("blur", function () {
      setTimeout(hide, 150);
    });
  }

  document.querySelectorAll(".alumno-ac").forEach(bind);
})();
