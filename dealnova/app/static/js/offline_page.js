(function () {
  var btn = document.getElementById("retryBtn");
  if (!btn) return;
  btn.addEventListener("click", function () {
    window.location.reload();
  });
})();

