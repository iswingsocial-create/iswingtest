(function () {
  var form = document.getElementById("video-upload");
  if (!form) return;
  var box = document.getElementById("video-progress");
  var bar = document.getElementById("video-bar");
  var label = document.getElementById("video-progress-label");
  var cancelBtn = document.getElementById("video-cancel");
  var retryBtn = document.getElementById("video-retry");
  var job = {id: "", index: 0, file: null, stopped: false, total: 0};
  var chunkSize = 1000000;

  function csrf() {
    var node = form.querySelector("[name=csrfmiddlewaretoken]");
    return node ? node.value : "";
  }
  function say(text) {
    if (label) label.textContent = text;
  }
  function show(on) {
    if (box) box.hidden = !on;
  }
  function selectedFile() {
    var input = form.querySelector("[name=file]");
    return input && input.files && input.files[0];
  }
  function visibility() {
    var chosen = form.querySelector("[name=visibility]:checked");
    return chosen ? chosen.value : "public";
  }
  function post(body) {
    return fetch("/moi/medias/morceau/", {method: "POST", body: body, credentials: "same-origin"}).then(function (res) {
      return res.json().then(function (data) {
        data._status = res.status;
        return data;
      });
    });
  }
  function sendIndex() {
    var file = job.file;
    var start = job.index * chunkSize;
    if (start >= file.size) return Promise.resolve();
    var end = Math.min(file.size, start + chunkSize);
    var data = new FormData();
    data.append("csrfmiddlewaretoken", csrf());
    data.append("upload_id", job.id);
    data.append("index", String(job.index));
    data.append("total_size", String(file.size));
    data.append("filename", file.name);
    data.append("kind", "video");
    data.append("visibility", visibility());
    data.append("media_rights", "1");
    data.append("media_minor", "1");
    data.append("media_host", "1");
    data.append("chunk", file.slice(start, end), file.name);
    return post(data).then(function (payload) {
      if (job.stopped) return;
      if (!payload.ok) throw new Error(payload.error || "Échec de ce morceau.");
      job.id = payload.upload_id || job.id;
      job.index = payload.next_index;
      if (bar) bar.value = Math.round((payload.received / file.size) * 100);
      say(file.name + " · " + (payload.received || 0) + " / " + file.size + " octets");
      if (payload.photo_id) {
        say(file.name + " · importation terminée. La conversion continue en arrière-plan.");
        if (retryBtn) retryBtn.hidden = true;
        window.setTimeout(function () { window.location = "/moi/?onglet=medias"; }, 700);
        return;
      }
      return sendIndex();
    });
  }
  function start(resume) {
    var file = selectedFile();
    if (!file) {
      say("Choisissez une vidéo.");
      return;
    }
    if (!resume) {
      job = {id: "", index: 0, file: file, stopped: false, total: file.size};
    } else {
      job.file = file;
      job.stopped = false;
    }
    show(true);
    if (retryBtn) retryBtn.hidden = true;
    say(file.name + " · envoi…");
    sendIndex().catch(function (error) {
      say(file.name + " · " + (error.message || "Erreur réseau. Vous pouvez réessayer le morceau en cours."));
      if (retryBtn) retryBtn.hidden = false;
    });
  }
  form.addEventListener("submit", function (event) {
    event.preventDefault();
    start(false);
  });
  if (cancelBtn) cancelBtn.addEventListener("click", function () {
    job.stopped = true;
    var data = new FormData();
    data.append("csrfmiddlewaretoken", csrf());
    data.append("upload_id", job.id);
    data.append("cancel", "1");
    data.append("index", "0");
    data.append("total_size", String(job.total || 0));
    post(data).then(function () {
      say((job.file && job.file.name ? job.file.name + " · " : "") + "Importation annulée.");
      job.id = "";
      job.index = 0;
    });
  });
  if (retryBtn) retryBtn.addEventListener("click", function () { start(true); });
})();
