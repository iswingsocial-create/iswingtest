(function () {
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/sw.js").catch(function () {});
  }
  var installBtn = document.getElementById("install-btn");
  var deferred;
  var standalone = window.matchMedia("(display-mode: standalone)").matches || window.navigator.standalone;
  window.addEventListener("beforeinstallprompt", function (event) {
    event.preventDefault();
    deferred = event;
    if (!standalone && installBtn) installBtn.hidden = false;
  });
  if (installBtn) {
    installBtn.addEventListener("click", function () {
      if (!deferred) { window.location.href = "/installer/"; return; }
      deferred.prompt();
      deferred = null;
      installBtn.hidden = true;
    });
  }
  document.addEventListener("click", function (event) {
    var confirmEl = event.target.closest("[data-confirm]");
    if (confirmEl && !window.confirm(confirmEl.getAttribute("data-confirm"))) {
      event.preventDefault();
      event.stopPropagation();
      return;
    }
    var actionEl = event.target.closest("[data-action]");
    if (!actionEl || actionEl.disabled) return;
    event.preventDefault();
    var id = actionEl.getAttribute("data-id");
    var action = actionEl.getAttribute("data-action");
    var tokenInput = document.querySelector("[name=csrfmiddlewaretoken]");
    var token = tokenInput ? tokenInput.value : "";
    if (!token) {
      var row = document.cookie.split("; ").find(function (part) { return part.indexOf("csrftoken=") === 0; });
      token = row ? decodeURIComponent(row.split("=").slice(1).join("=")) : "";
    }
    fetch("/actions/" + action + "/" + id + "/", {
      method: "POST",
      headers: {"X-CSRFToken": token},
    }).then(function (res) { return res.json().then(function (data) { return {ok: res.ok, data: data}; }); })
      .then(function (result) {
        var ui = document.body.dataset;
        var msg = document.getElementById("action-msg");
        function show(text) {
          if (!msg) { alert(text); return; }
          msg.hidden = false;
          msg.textContent = text;
        }
        if (!result.ok) { show(result.data.error || ui.refused || "action refusée"); return; }
        if (action === "like") {
          actionEl.textContent = actionEl.getAttribute("data-liked-label") || ui.liked || "OK";
          actionEl.disabled = true;
          actionEl.setAttribute("aria-pressed", "true");
          actionEl.classList.add("on");
          if (result.data.already) show(ui.already || "");
          else if (result.data.match) show(ui.match || "Match");
        }
        if (action === "favorite") {
          var on = !!result.data.on;
          actionEl.setAttribute("aria-pressed", on ? "true" : "false");
          actionEl.textContent = on ? (actionEl.getAttribute("data-on") || "Favori") : (actionEl.getAttribute("data-off") || actionEl.textContent);
          actionEl.classList.toggle("on", on);
        }
        var card = actionEl.closest("article");
        if (card && card.classList.contains("tinder-card") && action !== "favorite") {
          setTimeout(function () { window.location.reload(); }, 700);
        }
      }).catch(function () { alert(document.body.dataset.lost || "connexion perdue"); });
  });
  var key = document.getElementById("client-key");
  if (key) key.value = Date.now().toString(36) + Math.random().toString(36).slice(2);
  var thread = document.getElementById("thread");
  if (thread) {
    var after = thread.getAttribute("data-after");
    setInterval(function () {
      fetch("/messages/" + thread.getAttribute("data-match") + "/poll/?after=" + after)
        .then(function (r) { return r.json(); })
        .then(function (data) {
          var log = document.getElementById("log");
          (data.messages || []).forEach(function (msg) {
            after = msg.id;
            var p = document.createElement("p");
            p.textContent = msg.body || "";
            if (msg.mine) p.className = "mine";
            if (msg.video) {
              var video = document.createElement("video");
              video.controls = true;
              video.src = msg.video;
              if (msg.photo) video.poster = msg.photo;
              p.appendChild(video);
            } else if (msg.photo) {
              var img = document.createElement("img");
              img.src = msg.photo;
              img.alt = "";
              p.appendChild(img);
            }
            log.appendChild(p);
          });
        }).catch(function () {});
    }, 4000);
  }
  var geo = document.getElementById("geo-btn");
  if (geo) {
    geo.addEventListener("click", function () {
      if (!navigator.geolocation) return;
      navigator.geolocation.getCurrentPosition(function (pos) {
        document.getElementById("lat").value = pos.coords.latitude.toFixed(2);
        document.getElementById("lng").value = pos.coords.longitude.toFixed(2);
      }, function () { alert(document.body.dataset.geodenied || "Position refusée. Indiquez une ville."); });
    });
  }
  document.querySelectorAll("[data-city]").forEach(function (city) {
    var box = city.parentElement.querySelector(".city-results");
    if (!box) {
      box = document.createElement("div");
      box.className = "city-results";
      city.insertAdjacentElement("afterend", box);
    }
    var cityTimer;
    city.addEventListener("input", function () {
      clearTimeout(cityTimer);
      cityTimer = setTimeout(function () {
        if (city.value.trim().length < 2) { box.innerHTML = ""; return; }
        fetch("/villes/?q=" + encodeURIComponent(city.value.trim()))
          .then(function (r) { return r.json(); })
          .then(function (data) {
            box.innerHTML = "";
            var rows = data.results || [];
            if (!rows.length) { box.textContent = document.body.dataset.citynone || ""; return; }
            rows.forEach(function (row) {
              var button = document.createElement("button");
              button.type = "button";
              button.textContent = row.label;
              button.addEventListener("click", function () {
                var mode = city.getAttribute("data-city");
                city.value = mode === "filter" || mode === "admin" ? row.name : row.label;
                var form = city.form;
                var lat = form && form.querySelector("[name=city_lat], [name=lat]");
                var lng = form && form.querySelector("[name=city_lng], [name=lng]");
                var country = form && form.querySelector("[name=country]");
                var ref = form && form.querySelector("[name=city_ref]");
                if (lat && mode !== "filter") lat.value = row.lat;
                if (lng && mode !== "filter") lng.value = row.lng;
                if (country && mode === "admin" && row.country) country.value = row.country;
                if (ref && mode === "admin") ref.value = row.ref || "";
                box.innerHTML = "";
              });
              box.appendChild(button);
            });
          }).catch(function () { box.textContent = document.body.dataset.lost || ""; });
      }, 200);
    });
  });
  var cropInput = document.querySelector("[data-crop]");
  var modal = document.getElementById("cropper");
  var canvas = document.getElementById("crop-canvas");
  if (cropInput && modal && canvas) {
    var zoom = document.getElementById("crop-zoom");
    var ctx = canvas.getContext("2d");
    canvas.width = 800;
    canvas.height = 1000;
    var img = new Image();
    var state = {scale: 1, x: 0, y: 0, drag: false, lx: 0, ly: 0};
    function draw() {
      ctx.fillStyle = "#000";
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      if (!img.width) return;
      var base = Math.max(canvas.width / img.width, canvas.height / img.height) * state.scale;
      var w = img.width * base;
      var h = img.height * base;
      ctx.drawImage(img, (canvas.width - w) / 2 + state.x, (canvas.height - h) / 2 + state.y, w, h);
    }
    cropInput.addEventListener("change", function () {
      var file = cropInput.files && cropInput.files[0];
      if (!file || file.type.indexOf("image/") !== 0) return;
      var reader = new FileReader();
      reader.onload = function () {
        img.onload = function () {
          state.scale = 1; state.x = 0; state.y = 0;
          if (zoom) zoom.value = "1";
          modal.hidden = false;
          draw();
        };
        img.src = reader.result;
      };
      reader.readAsDataURL(file);
    });
    if (zoom) zoom.addEventListener("input", function () { state.scale = parseFloat(zoom.value) || 1; draw(); });
    canvas.addEventListener("pointerdown", function (event) {
      state.drag = true; state.lx = event.clientX; state.ly = event.clientY;
    });
    canvas.addEventListener("pointermove", function (event) {
      if (!state.drag) return;
      state.x += event.clientX - state.lx;
      state.y += event.clientY - state.ly;
      state.lx = event.clientX; state.ly = event.clientY;
      draw();
    });
    canvas.addEventListener("pointerup", function () { state.drag = false; });
    document.getElementById("crop-apply").addEventListener("click", function () {
      canvas.toBlob(function (blob) {
        if (!blob || typeof DataTransfer === "undefined") { modal.hidden = true; return; }
        var dt = new DataTransfer();
        dt.items.add(new File([blob], "photo.jpg", {type: "image/jpeg"}));
        cropInput.files = dt.files;
        if (window.iswingAfterCrop) window.iswingAfterCrop(blob);
        else modal.hidden = true;
      }, "image/jpeg", 0.9);
    });
    document.getElementById("crop-full").addEventListener("click", function () { modal.hidden = true; });
  }
})();
