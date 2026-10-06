document.addEventListener("DOMContentLoaded", () => {
  const tokenInput = document.getElementById("token");
  const saveBtn = document.getElementById("saveBtn");
  const msg = document.getElementById("msg");

  chrome.storage.local.get(["rpc_token"], (res) => {
    if (res.rpc_token) tokenInput.value = res.rpc_token;
  });

  saveBtn.addEventListener("click", () => {
    const val = tokenInput.value.trim().toUpperCase();
    chrome.storage.local.set({ rpc_token: val }, () => {
      msg.innerText = "Токен сохранен!";
      setTimeout(() => { msg.innerText = ""; }, 2000);
    });
  });
});