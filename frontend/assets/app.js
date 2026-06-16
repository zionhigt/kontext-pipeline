const $ = (id) => document.getElementById(id);
const form = $("edit-form");
const drop = $("drop");
const fileInput = $("images");
const thumbs = $("thumbs");
const progressSec = $("progress");
const statusList = $("status-list");
const resultsSec = $("results");
const gallery = $("gallery");

function renderThumbs(files) {
  thumbs.innerHTML = "";
  for (const f of files) {
    const img = document.createElement("img");
    img.src = URL.createObjectURL(f);
    img.alt = f.name;
    thumbs.appendChild(img);
  }
}

drop.addEventListener("click", () => fileInput.click());
fileInput.addEventListener("change", () => renderThumbs(fileInput.files));

["dragenter", "dragover"].forEach((ev) =>
  drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); })
);
["dragleave", "drop"].forEach((ev) =>
  drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("over"); })
);
drop.addEventListener("drop", (e) => {
  fileInput.files = e.dataTransfer.files;
  renderThumbs(fileInput.files);
});

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!fileInput.files.length) return;

  const fd = new FormData();
  fd.append("prompt", $("prompt").value);
  fd.append("steps", $("steps").value);
  fd.append("guidance", $("guidance").value);
  fd.append("seed", $("seed").value);
  for (const f of fileInput.files) fd.append("images", f);

  const btn = form.querySelector("button");
  btn.disabled = true;

  const res = await fetch("/edit", { method: "POST", body: fd });
  if (!res.ok) {
    alert("Erreur: " + (await res.text()));
    btn.disabled = false;
    return;
  }
  const { batch_id } = await res.json();
  progressSec.classList.remove("hidden");
  resultsSec.classList.add("hidden");
  poll(batch_id, btn);
});

async function poll(batchId, btn) {
  while (true) {
    const r = await fetch(`/status/${batchId}`);
    const data = await r.json();
    statusList.innerHTML = data.jobs
      .map((j) => `<li class="state-${j.state}">image ${j.idx} — ${j.state}${j.error ? " (" + j.error + ")" : ""}</li>`)
      .join("");
    const allDone = data.jobs.every((j) => j.state === "done" || j.state === "error");
    if (allDone) {
      await showResults(batchId);
      btn.disabled = false;
      return;
    }
    await new Promise((r) => setTimeout(r, 1500));
  }
}

async function showResults(batchId) {
  const r = await fetch(`/result/${batchId}`);
  const { results } = await r.json();
  gallery.innerHTML = results
    .map((res) =>
      res.url
        ? `<figure>
             <img src="${res.url}" alt="result ${res.idx}" />
             <figcaption>image ${res.idx}</figcaption>
             <a class="dl" href="${res.url}" download>télécharger</a>
           </figure>`
        : `<figure><figcaption class="state-error">image ${res.idx} — ${res.state}</figcaption></figure>`
    )
    .join("");
  resultsSec.classList.remove("hidden");
}
