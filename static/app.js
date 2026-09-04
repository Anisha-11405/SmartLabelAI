const $=s=>document.querySelector(s);
const input=$("#fileInput"), preview=$("#preview"), analyze=$("#analyze");
const labels={productName:"Product Name",manufacturer:"Manufacturer / Packer",netQuantity:"Net Quantity",mrp:"MRP",batchNumber:"Batch / Lot Number",date:"Date Information"};

input.addEventListener("change",()=>{
  preview.innerHTML="";
  [...input.files].forEach(f=>{
    const img=document.createElement("img");
    img.className="thumb"; img.src=URL.createObjectURL(f); preview.appendChild(img);
  });
});

async function health(){
  try{
    const r=await fetch("/api/health"); const d=await r.json();
    $("#diag").innerHTML=d.tesseractPath && d.tesseractPath!=="NOT FOUND"
      ? "<b>Tesseract detected:</b> "+d.tesseractPath
      : "<div class='error'><b>Tesseract not detected.</b> Install it or add C:\\Program Files\\Tesseract-OCR to PATH, then restart this server.</div>";
  }catch(e){$("#diag").textContent="Server not reachable."}
}
health();

analyze.addEventListener("click",async()=>{
  if(!input.files.length){alert("Choose a package image first.");return}
  analyze.disabled=true; analyze.textContent="Analyzing...";
  const fd=new FormData(); [...input.files].forEach(f=>fd.append("images",f));
  try{
    const r=await fetch("/api/analyze",{method:"POST",body:fd});
    const d=await r.json();
    if(!r.ok || d.error) throw new Error(d.error||"OCR failed");
    $("#badge").textContent="OCR Complete"; $("#badge").style.background="#e5f7ed";
    const f=d.fields;
    $("#fields").innerHTML=Object.entries(labels).map(([k,v])=>`<div class="field"><span>${v}</span><b>${f[k]||"Not detected"}</b></div>`).join("");
    $("#raw").textContent=d.ocrText||"(empty)";
    const res=d.result;
    $("#result").innerHTML=`<div><h3>${res.status} — ${res.score}%</h3>${res.checks.map(c=>`<p><b>${c.name}:</b> <span class="${c.status==="PASS"?"ok":"review"}">${c.status}</span>${c.value?` — ${c.value}`:""}</p>`).join("")}<p class="hint">Prototype screening only; final legal verification remains with the inspector.</p></div>`;
  }catch(e){
    $("#badge").textContent="OCR Error"; $("#badge").style.background="#ffe8e8";
    $("#result").innerHTML=`<div class="error"><b>${e.message}</b><br><br>Open the VS Code terminal and check the Tesseract path printed when the server starts.</div>`;
  }finally{analyze.disabled=false; analyze.textContent="Analyze with OCR"}
});
