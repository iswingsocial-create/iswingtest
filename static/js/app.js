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
    if (!actionEl || actionEl.disabled || actionEl.getAttribute("data-busy") === "1") return;
    event.preventDefault();
    var id = actionEl.getAttribute("data-id");
    var action = actionEl.getAttribute("data-action");
    var card = actionEl.closest("article.tinder-card");
    var locked = [];
    if (action === "like" || action === "pass") {
      var nodes = card ? card.querySelectorAll("[data-action='like'], [data-action='pass']") : [actionEl];
      Array.prototype.forEach.call(nodes, function (btn) {
        btn.disabled = true;
        btn.setAttribute("data-busy", "1");
        locked.push(btn);
      });
    }
    var tokenInput = document.querySelector("[name=csrfmiddlewaretoken]");
    var token = tokenInput ? tokenInput.value : "";
    if (!token) {
      var row = document.cookie.split("; ").find(function (part) { return part.indexOf("csrftoken=") === 0; });
      token = row ? decodeURIComponent(row.split("=").slice(1).join("=")) : "";
    }
    if (!window.__iswingKeys) window.__iswingKeys = {};
    var slot = action + ":" + id;
    if ((action === "like" || action === "pass") && !window.__iswingKeys[slot]) {
      window.__iswingKeys[slot] = Date.now().toString(36) + Math.random().toString(36).slice(2);
    }
    var body = new URLSearchParams();
    if (window.__iswingKeys[slot]) body.set("client_key", window.__iswingKeys[slot]);
    function unlock(keepLike) {
      locked.forEach(function (btn) {
        if (keepLike && btn.getAttribute("data-action") === "like") return;
        btn.disabled = false;
        btn.removeAttribute("data-busy");
      });
    }
    fetch("/actions/" + action + "/" + id + "/", {
      method: "POST",
      headers: {"X-CSRFToken": token, "Content-Type": "application/x-www-form-urlencoded"},
      body: body,
    }).then(function (res) { return res.json().then(function (data) { return {ok: res.ok, data: data}; }); })
      .then(function (result) {
        var ui = document.body.dataset;
        var msg = document.getElementById("action-msg");
        function show(text) {
          if (!text) return;
          if (!msg) { alert(text); return; }
          msg.hidden = false;
          msg.textContent = text;
        }
        if (!result.ok) {
          var exhausted = action === "like" && result.data.likes_left === 0;
          unlock(exhausted);
          show(result.data.error || ui.refused || "");
          var line = document.getElementById("likes-left");
          if (line && result.data.likes_left !== undefined && result.data.likes_left !== null) {
            line.setAttribute("data-left", String(result.data.likes_left));
          }
          return;
        }
        if (window.__iswingKeys[slot]) delete window.__iswingKeys[slot];
        if ((action === "like" || action === "superlike") && result.data.match && !result.data.already) {
          var modal = document.getElementById("match-modal");
          if (modal) {
            var meImg = document.getElementById("match-modal-me");
            var otherImg = document.getElementById("match-modal-other");
            var sub = document.getElementById("match-modal-sub");
            var sendBtn = document.getElementById("match-modal-send");
            if (meImg) meImg.src = result.data.my_avatar || "";
            if (otherImg) otherImg.src = result.data.other_avatar || "";
            if (sub && result.data.other_name) sub.textContent = (ui.matchWith || "C'est un match avec {name} !").replace("{name}", result.data.other_name);
            if (sendBtn && result.data.match_id) sendBtn.href = "/messages/" + result.data.match_id + "/";
            modal.hidden = false;
            var close = document.getElementById("match-modal-close");
            if (close) close.onclick = function () { modal.hidden = true; };
            modal.onclick = function (e) { if (e.target === modal) modal.hidden = true; };
          } else {
            show(ui.match || "");
          }
        }
        if (action === "superlike") {
          actionEl.textContent = actionEl.getAttribute("data-superliked-label") || actionEl.textContent;
          actionEl.disabled = true;
          actionEl.classList.add("on");
        }
        if (action === "favorite") {
          var on = !!result.data.on;
          actionEl.setAttribute("aria-pressed", on ? "true" : "false");
          actionEl.textContent = on ? (actionEl.getAttribute("data-on") || "Favori") : (actionEl.getAttribute("data-off") || actionEl.textContent);
          actionEl.classList.toggle("on", on);
        }
        if (card && action !== "favorite") {
          card.classList.add("leaving");
          card.setAttribute("aria-hidden", "true");
          window.setTimeout(function () {
            if (card.parentNode) card.remove();
            window.location.replace(window.location.pathname + window.location.search);
          }, 180);
          return;
        }
        if (action === "like") {
          actionEl.textContent = actionEl.getAttribute("data-liked-label") || ui.liked || "OK";
          actionEl.disabled = true;
          actionEl.setAttribute("aria-pressed", "true");
          actionEl.classList.add("on");
          var next = actionEl.getAttribute("data-redirect");
          if (next) {
            var wait = result.data.match && !result.data.already ? 25000 : 400;
            window.setTimeout(function () { window.location.assign(next); }, wait);
          }
        }
      }).catch(function () {
        unlock(false);
        var msg = document.getElementById("action-msg");
        var text = document.body.dataset.lost || "";
        if (msg && text) { msg.hidden = false; msg.textContent = text; }
        else if (text) alert(text);
      });
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
            thread.setAttribute("data-after", after);
            var wrap = document.createElement("div");
            wrap.className = "msg" + (msg.mine ? " mine" : "");
            if (msg.avatar) {
              var av = document.createElement("img");
              av.className = "avatar";
              av.src = msg.avatar;
              av.alt = "";
              wrap.appendChild(av);
            }
            var bubble = document.createElement("div");
            bubble.className = "bubble";
            if (msg.author) {
              var who = document.createElement("span");
              who.className = "who";
              who.textContent = msg.author;
              bubble.appendChild(who);
            }
            if (msg.body) {
              var bp = document.createElement("p");
              bp.className = "body";
              bp.textContent = msg.body;
              bubble.appendChild(bp);
            }
            if (msg.video) {
              var video = document.createElement("video");
              video.controls = true;
              video.playsInline = true;
              video.setAttribute("playsinline", "");
              video.src = msg.video;
              if (msg.thumb || msg.photo) video.poster = msg.thumb || msg.photo;
              bubble.appendChild(video);
            } else if (msg.photo) {
              var link = document.createElement("a");
              link.className = "shared-photo";
              link.href = msg.photo;
              var img = document.createElement("img");
              img.src = msg.thumb || msg.photo;
              img.alt = "";
              link.appendChild(img);
              bubble.appendChild(link);
            }
            if (msg.mine && msg.contact) {
              var note = document.createElement("p");
              note.className = "contact-note";
              note.textContent = thread.getAttribute("data-contact-notice") || "";
              if (note.textContent) bubble.appendChild(note);
            }
            wrap.appendChild(bubble);
            log.appendChild(wrap);
          });
        }).catch(function () {});
    }, 4000);
  }
  var geo = document.getElementById("geo-btn");
  if (geo) {
    var geoLabel = geo.textContent;
    var geoStatus = document.getElementById("geo-status");
    function geoSay(text) {
      if (geoStatus) geoStatus.textContent = text || "";
    }
    function geoRestore() {
      geo.disabled = false;
      geo.textContent = geoLabel;
    }
    function geoStart() {
      geo.disabled = true;
      geo.textContent = geo.getAttribute("data-wait") || geoLabel;
      navigator.geolocation.getCurrentPosition(function (pos) {
        var lat = pos.coords.latitude.toFixed(4);
        var lng = pos.coords.longitude.toFixed(4);
        var latInput = document.getElementById("lat");
        var lngInput = document.getElementById("lng");
        if (latInput) latInput.value = lat;
        if (lngInput) lngInput.value = lng;
        var form = geo.form || (latInput && latInput.form);
        var city = form && form.querySelector("[name=city]");
        var foundTpl = geo.getAttribute("data-found") || "";
        function finish(name) {
          if (city && name) city.value = name;
          geoSay(foundTpl.replace("{city}", name || ""));
          if (!form) { geoRestore(); return; }
          var flag = form.querySelector("[name=from_gps]");
          if (!flag) {
            flag = document.createElement("input");
            flag.type = "hidden";
            flag.name = "from_gps";
            form.appendChild(flag);
          }
          flag.value = "1";
          form.submit();
        }
        fetch("/villes/proche/?lat=" + encodeURIComponent(lat) + "&lng=" + encodeURIComponent(lng))
          .then(function (r) { return r.json(); })
          .then(function (data) { finish(data && data.name ? data.name : ""); })
          .catch(function () { finish(""); });
      }, function (err) {
        geoRestore();
        var code = err && err.code;
        if (code === 1) geoSay(geo.getAttribute("data-denied") || "");
        else if (code === 2) geoSay(geo.getAttribute("data-unavailable") || "");
        else geoSay(geo.getAttribute("data-timeout") || "");
      }, {enableHighAccuracy: true, timeout: 30000, maximumAge: 0});
    }
    geo.addEventListener("click", function () {
      if (!navigator.geolocation) {
        geoSay(geo.getAttribute("data-unavailable") || "");
        return;
      }
      if (navigator.permissions && navigator.permissions.query) {
        navigator.permissions.query({name: "geolocation"}).then(function (result) {
          if (result && result.state === "denied") {
            geoSay(geo.getAttribute("data-denied") || "");
            return;
          }
          geoStart();
        }).catch(function () { geoStart(); });
      } else {
        geoStart();
      }
    });
  }
  document.querySelectorAll("[data-city]").forEach(function (city) {
    var box = city.parentElement.querySelector(".city-results");
    if (!box) {
      box = document.createElement("div");
      box.className = "city-results";
      city.insertAdjacentElement("afterend", box);
    }
    var form = city.form;
    var latInput = form && form.querySelector("[name=city_lat], [name=lat]");
    var lngInput = form && form.querySelector("[name=city_lng], [name=lng]");
    var picked = "";
    if (latInput && lngInput && String(latInput.value || "").trim() && String(lngInput.value || "").trim() && city.value.trim()) {
      picked = city.value;
    }
    var cityTimer;
    var buttons = [];
    var active = -1;
    function paint() {
      buttons.forEach(function (button, index) {
        if (index === active) button.setAttribute("aria-selected", "true");
        else button.removeAttribute("aria-selected");
      });
    }
    function clearCoords() {
      if (latInput) latInput.value = "";
      if (lngInput) lngInput.value = "";
      picked = "";
    }
    function applyRow(row) {
      var mode = city.getAttribute("data-city");
      city.value = mode === "filter" || mode === "admin" ? row.name : row.label;
      picked = city.value;
      if (latInput) latInput.value = row.lat;
      if (lngInput) lngInput.value = row.lng;
      var country = form && form.querySelector("[name=country]");
      var ref = form && form.querySelector("[name=city_ref]");
      if (country && mode === "admin" && row.country) country.value = row.country;
      if (ref && mode === "admin") ref.value = row.ref || "";
      box.innerHTML = "";
      buttons = [];
      active = -1;
    }
    city.addEventListener("keydown", function (event) {
      if (!buttons.length) return;
      if (event.key === "ArrowDown") {
        event.preventDefault();
        active = (active + 1) % buttons.length;
        paint();
      } else if (event.key === "ArrowUp") {
        event.preventDefault();
        active = (active - 1 + buttons.length) % buttons.length;
        paint();
      } else if (event.key === "Enter" && active >= 0) {
        event.preventDefault();
        buttons[active].click();
      }
    });
    city.addEventListener("input", function () {
      if (city.value !== picked) clearCoords();
      clearTimeout(cityTimer);
      cityTimer = setTimeout(function () {
        if (city.value.trim().length < 2) { box.innerHTML = ""; buttons = []; active = -1; return; }
        fetch("/villes/?q=" + encodeURIComponent(city.value.trim()))
          .then(function (r) { return r.json(); })
          .then(function (data) {
            box.innerHTML = "";
            buttons = [];
            active = -1;
            var rows = data.results || [];
            if (!rows.length) { box.textContent = document.body.dataset.citynone || ""; return; }
            rows.forEach(function (row) {
              var button = document.createElement("button");
              button.type = "button";
              button.textContent = row.label;
              button.addEventListener("click", function () { applyRow(row); });
              box.appendChild(button);
              buttons.push(button);
            });
          }).catch(function () { box.textContent = document.body.dataset.lost || ""; });
      }, 200);
    });
  });
  document.addEventListener("keydown", function (event) {
    if (event.key !== "Escape") return;
    var menu = document.getElementById("main-menu");
    var menuBtn = document.getElementById("menu-btn");
    if (!menu || menu.hidden || !menuBtn) return;
    menu.hidden = true;
    menuBtn.setAttribute("aria-expanded", "false");
    menuBtn.focus();
  });
  var menuBtn = document.getElementById("menu-btn");
  var menu = document.getElementById("main-menu");
  if (menuBtn && menu) {
    menuBtn.addEventListener("click", function (event) {
      event.stopPropagation();
      var open = menu.hidden;
      menu.hidden = !open;
      menuBtn.setAttribute("aria-expanded", open ? "true" : "false");
      if (open) {
        var current = menu.querySelector("[aria-current='page']") || menu.querySelector("a");
        if (current) current.focus();
      }
    });
    document.addEventListener("click", function (event) {
      if (menu.hidden) return;
      if (menu.contains(event.target) || menuBtn.contains(event.target)) return;
      menu.hidden = true;
      menuBtn.setAttribute("aria-expanded", "false");
    });
  }
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
  document.querySelectorAll(".pw-toggle").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var wrap = btn.closest(".pw-wrap");
      var input = wrap && wrap.querySelector("input");
      if (!input) return;
      var showing = input.type === "password";
      input.type = showing ? "text" : "password";
      btn.setAttribute("aria-pressed", showing ? "true" : "false");
      var label = btn.getAttribute(showing ? "data-hide" : "data-show") || "";
      btn.setAttribute("aria-label", label);
      btn.title = label;
    });
  });
})();

/* Affiche le nom du fichier choisi dans les accordéons d'upload */
(function () {
  document.addEventListener("change", function (e) {
    var input = e.target;
    if (!input.matches('.upload-drop input[type="file"]')) return;
    var drop = input.closest(".upload-drop");
    var name = drop && drop.querySelector("[data-name]");
    if (name) name.textContent = input.files.length ? input.files[0].name : "";
  });
})();
