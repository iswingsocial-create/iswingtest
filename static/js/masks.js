(function () {
  var tools = document.getElementById("mask-tools");
  var canvas = document.getElementById("mask-canvas");
  var field = document.getElementById("masks-json");
  if (!tools || !canvas || !field) return;
  var ctx = canvas.getContext("2d");
  var img = new Image();
  var masks = [];
  var undo = [];
  var redo = [];
  var selected = -1;
  var drag = null;

  function write() {
    field.value = JSON.stringify(masks);
  }
  function snapshot() {
    undo.push(JSON.stringify(masks));
    if (undo.length > 40) undo.shift();
    redo = [];
  }
  function roundRect(x, y, w, h, r) {
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r);
    ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r);
    ctx.arcTo(x, y, x + w, y, r);
    ctx.closePath();
  }
  function draw() {
    if (!img.width) return;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
    masks.forEach(function (mask, index) {
      var bw = Math.max(8, mask.w * canvas.width);
      var bh = Math.max(8, mask.h * canvas.height);
      var x = mask.x * canvas.width;
      var y = mask.y * canvas.height;
      ctx.save();
      ctx.translate(x + bw / 2, y + bh / 2);
      ctx.rotate(((mask.rotation || 0) * Math.PI) / 180);
      if (mask.type === "blur") {
        ctx.beginPath();
        ctx.ellipse(0, 0, bw / 2, bh / 2, 0, 0, Math.PI * 2);
        ctx.fillStyle = "rgba(80, 48, 224, 0.35)";
        ctx.fill();
        ctx.fillStyle = "#fff";
        ctx.font = "14px sans-serif";
        ctx.textAlign = "center";
        ctx.fillText("flou", 0, 4);
      } else {
        drawSticker(mask.emoji || "happy", bw, bh);
      }
      if (index === selected) {
        ctx.strokeStyle = "#c9b6ff";
        ctx.lineWidth = 2;
        ctx.beginPath();
        if (mask.type === "blur") ctx.ellipse(0, 0, bw / 2, bh / 2, 0, 0, Math.PI * 2);
        else ctx.ellipse(0, 0, bw / 2, bh / 2, 0, 0, Math.PI * 2);
        ctx.stroke();
      }
      ctx.restore();
    });
    write();
  }
  function hit(px, py) {
    for (var i = masks.length - 1; i >= 0; i -= 1) {
      var mask = masks[i];
      var x = mask.x * canvas.width;
      var y = mask.y * canvas.height;
      var bw = mask.w * canvas.width;
      var bh = mask.h * canvas.height;
      if (px >= x && py >= y && px <= x + bw && py <= y + bh) return i;
    }
    return -1;
  }
  function syncSliders() {
    var mask = masks[selected];
    if (!mask) return;
    var size = document.getElementById("mask-size");
    var rot = document.getElementById("mask-rot");
    var strength = document.getElementById("mask-strength");
    if (size) size.value = String(Math.round(mask.w * 100));
    if (rot) rot.value = String(mask.rotation || 0);
    if (strength) strength.value = String(mask.strength || 12);
  }
  function drawSticker(code, bw, bh) {
    var x = -bw / 2;
    var y = -bh / 2;
    if (code === "devil") {
      ctx.fillStyle = "#c42030";
      ctx.beginPath();
      ctx.moveTo(x + bw * 0.22, y + bh * 0.30);
      ctx.lineTo(x + bw * 0.32, y + bh * 0.02);
      ctx.lineTo(x + bw * 0.42, y + bh * 0.30);
      ctx.fill();
      ctx.beginPath();
      ctx.moveTo(x + bw * 0.58, y + bh * 0.30);
      ctx.lineTo(x + bw * 0.68, y + bh * 0.02);
      ctx.lineTo(x + bw * 0.78, y + bh * 0.30);
      ctx.fill();
      ctx.beginPath();
      ctx.ellipse(0, y + bh * 0.58, bw * 0.38, bh * 0.38, 0, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = "#1a1020";
      ctx.beginPath();
      ctx.ellipse(x + bw * 0.36, y + bh * 0.50, Math.max(2, bw * 0.05), Math.max(2, bh * 0.06), 0, 0, Math.PI * 2);
      ctx.ellipse(x + bw * 0.64, y + bh * 0.50, Math.max(2, bw * 0.05), Math.max(2, bh * 0.06), 0, 0, Math.PI * 2);
      ctx.fill();
    } else if (code === "pineapple") {
      ctx.fillStyle = "#2e8b3a";
      ctx.beginPath();
      ctx.moveTo(0, y + bh * 0.02);
      ctx.lineTo(x + bw * 0.30, y + bh * 0.32);
      ctx.lineTo(x + bw * 0.48, y + bh * 0.18);
      ctx.fill();
      ctx.beginPath();
      ctx.moveTo(0, y + bh * 0.02);
      ctx.lineTo(x + bw * 0.70, y + bh * 0.32);
      ctx.lineTo(x + bw * 0.52, y + bh * 0.18);
      ctx.fill();
      ctx.fillStyle = "#f0c428";
      ctx.beginPath();
      ctx.ellipse(0, y + bh * 0.58, bw * 0.28, bh * 0.36, 0, 0, Math.PI * 2);
      ctx.fill();
    } else {
      ctx.fillStyle = "#ffd628";
      ctx.beginPath();
      ctx.ellipse(0, 0, bw * 0.46, bh * 0.46, 0, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = "#1a1020";
      ctx.beginPath();
      ctx.ellipse(x + bw * 0.36, y + bh * 0.40, Math.max(2, bw * 0.05), Math.max(2, bh * 0.06), 0, 0, Math.PI * 2);
      ctx.ellipse(x + bw * 0.64, y + bh * 0.40, Math.max(2, bw * 0.05), Math.max(2, bh * 0.06), 0, 0, Math.PI * 2);
      ctx.fill();
      ctx.beginPath();
      ctx.strokeStyle = "#1a1020";
      ctx.lineWidth = Math.max(2, bw / 16);
      ctx.arc(0, y + bh * 0.52, Math.min(bw, bh) * 0.22, 0.25, Math.PI - 0.25);
      ctx.stroke();
    }
  }
  function add(type, code) {
    snapshot();
    masks.push({
      type: type,
      x: 0.38,
      y: 0.32,
      w: 0.24,
      h: 0.2,
      rotation: 0,
      strength: 12,
      emoji: code || (type === "sticker" ? "happy" : "")
    });
    selected = masks.length - 1;
    syncSliders();
    draw();
  }
  window.iswingAfterCrop = function (blob) {
    masks = [];
    undo = [];
    redo = [];
    selected = -1;
    var url = URL.createObjectURL(blob);
    img.onload = function () {
      var max = 800;
      canvas.width = Math.min(max, img.naturalWidth || img.width);
      canvas.height = Math.max(1, Math.round(canvas.width * (img.naturalHeight || img.height) / (img.naturalWidth || img.width)));
      tools.hidden = false;
      draw();
      URL.revokeObjectURL(url);
    };
    img.src = url;
  };
  canvas.addEventListener("pointerdown", function (event) {
    var rect = canvas.getBoundingClientRect();
    var px = (event.clientX - rect.left) * (canvas.width / rect.width);
    var py = (event.clientY - rect.top) * (canvas.height / rect.height);
    selected = hit(px, py);
    syncSliders();
    if (selected >= 0) {
      snapshot();
      drag = {id: event.pointerId, x: px, y: py};
      canvas.setPointerCapture(event.pointerId);
    }
    draw();
  });
  canvas.addEventListener("pointermove", function (event) {
    if (!drag || selected < 0) return;
    var rect = canvas.getBoundingClientRect();
    var px = (event.clientX - rect.left) * (canvas.width / rect.width);
    var py = (event.clientY - rect.top) * (canvas.height / rect.height);
    var mask = masks[selected];
    mask.x = Math.min(0.95, Math.max(-0.2, mask.x + (px - drag.x) / canvas.width));
    mask.y = Math.min(0.95, Math.max(-0.2, mask.y + (py - drag.y) / canvas.height));
    drag.x = px;
    drag.y = py;
    draw();
  });
  canvas.addEventListener("pointerup", function () { drag = null; });
  function bind(id, fn) {
    var node = document.getElementById(id);
    if (node) node.addEventListener("click", fn);
  }
  document.querySelectorAll("[data-sticker]").forEach(function (node) {
    node.addEventListener("click", function () { add("sticker", node.getAttribute("data-sticker") || "happy"); });
  });
  bind("mask-blur", function () { add("blur"); });
  bind("mask-delete", function () {
    if (selected < 0) return;
    snapshot();
    masks.splice(selected, 1);
    selected = masks.length - 1;
    draw();
  });
  bind("mask-undo", function () {
    if (!undo.length) return;
    redo.push(JSON.stringify(masks));
    masks = JSON.parse(undo.pop());
    selected = Math.min(selected, masks.length - 1);
    draw();
  });
  bind("mask-redo", function () {
    if (!redo.length) return;
    undo.push(JSON.stringify(masks));
    masks = JSON.parse(redo.pop());
    draw();
  });
  bind("mask-done", function () {
    write();
    tools.hidden = true;
    var modal = document.getElementById("cropper");
    if (modal) modal.hidden = true;
  });
  ["mask-size", "mask-rot", "mask-strength"].forEach(function (id) {
    var node = document.getElementById(id);
    if (!node) return;
    node.addEventListener("pointerdown", function () { if (selected >= 0) snapshot(); });
    node.addEventListener("input", function () {
      if (selected < 0) return;
      var mask = masks[selected];
      if (id === "mask-size") {
        var value = Math.max(0.08, Math.min(0.7, (parseFloat(node.value) || 18) / 100));
        mask.w = value;
        mask.h = value * 0.85;
      } else if (id === "mask-rot") {
        mask.rotation = parseFloat(node.value) || 0;
      } else {
        mask.strength = parseFloat(node.value) || 12;
      }
      draw();
    });
  });
  document.addEventListener("keydown", function (event) {
    if (tools.hidden) return;
    var tag = (event.target && event.target.tagName) || "";
    if (tag === "INPUT" || tag === "TEXTAREA") return;
    if (event.key === "Delete" || event.key === "Backspace") {
      event.preventDefault();
      if (selected < 0) return;
      snapshot();
      masks.splice(selected, 1);
      selected = masks.length - 1;
      draw();
    }
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "z" && !event.shiftKey) {
      event.preventDefault();
      document.getElementById("mask-undo").click();
    }
    if ((event.ctrlKey || event.metaKey) && (event.key.toLowerCase() === "y" || (event.shiftKey && event.key.toLowerCase() === "z"))) {
      event.preventDefault();
      document.getElementById("mask-redo").click();
    }
  });
})();
