(function(){
  var GATE_KEY = "iswing_age_ok";
  var gate = document.getElementById("age-gate"), page = document.getElementById("page");
  var ok = false; try { ok = localStorage.getItem(GATE_KEY) === "1"; } catch (e) {}
  if (!gate || ok) return;
  var last = document.activeElement;
  gate.hidden = false; if (page) page.setAttribute("aria-hidden", "true");
  document.documentElement.style.overflow = "hidden";
  var yes = document.getElementById("age-yes"); yes && yes.focus();
  function close(){
    gate.hidden = true; if (page) page.removeAttribute("aria-hidden");
    document.documentElement.style.overflow = "";
    try { localStorage.setItem(GATE_KEY, "1"); } catch (e) {}
    last && last.focus && last.focus();
  }
  yes && yes.addEventListener("click", close);
  gate.addEventListener("keydown", function(e){
    if (e.key !== "Tab") return;
    var f = gate.querySelectorAll("a,button"), first = f[0], lastEl = f[f.length - 1];
    if (e.shiftKey && document.activeElement === first){ e.preventDefault(); lastEl.focus(); }
    else if (!e.shiftKey && document.activeElement === lastEl){ e.preventDefault(); first.focus(); }
  });
})();
