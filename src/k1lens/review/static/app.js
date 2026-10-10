(function () {
  var reviewer = document.getElementById("reviewer");
  if (!reviewer) {
    return;
  }
  function sync() {
    var name = reviewer.value.trim();
    document.querySelectorAll("[data-actor]").forEach(function (input) {
      input.value = name;
    });
  }
  reviewer.addEventListener("input", sync);
  document.querySelectorAll("form").forEach(function (form) {
    form.addEventListener("submit", sync);
  });
})();
