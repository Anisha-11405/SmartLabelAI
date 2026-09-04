document.addEventListener("DOMContentLoaded", () => {
  const fileInput = document.getElementById("fileInput");
  const analyzeBtn = document.getElementById("analyze");
  const preview = document.getElementById("preview");
  const badge = document.getElementById("badge");
  const fieldsContainer = document.getElementById("fields");
  const rawPre = document.getElementById("raw");
  const resultDiv = document.getElementById("result");
  const diag = document.getElementById("diag");
  const reportActions = document.getElementById("reportActions");
  const printReportBtn = document.getElementById("printReportBtn");
  const downloadJsonBtn = document.getElementById("downloadJsonBtn");

  let currentInspectionData = null;

  // Diagnostics
  fetch("/api/health")
    .then(r => r.json())
    .then(data => {
      if (data.tesseract) {
        diag.innerHTML = `<span style="color:#15803d; font-weight:600;">Ready:</span> Tesseract detected at <code>${data.path}</code>`;
      } else {
        diag.innerHTML = `<span style="color:#b91c1c; font-weight:600;">Error:</span> Tesseract missing at <code>${data.path}</code>`;
      }
    })
    .catch(err => {
      diag.innerHTML = `<span style="color:#b91c1c;">Backend unreachable: ${err.message}</span>`;
    });

  fileInput.addEventListener("change", () => {
    preview.innerHTML = "";
    Array.from(fileInput.files).forEach(file => {
      const img = document.createElement("img");
      img.src = URL.createObjectURL(file);
      img.style.width = "90px";
      img.style.height = "90px";
      img.style.objectFit = "cover";
      img.style.borderRadius = "4px";
      img.style.border = "1px solid #cbd5e1";
      preview.appendChild(img);
    });
  });

  analyzeBtn.addEventListener("click", async () => {
    if (!fileInput.files || fileInput.files.length === 0) {
      alert("Please upload at least one label image first.");
      return;
    }

    analyzeBtn.disabled = true;
    analyzeBtn.innerText = "Analyzing Legal Metrology Rules...";
    badge.innerText = "Processing";
    reportActions.style.display = "none";

    const formData = new FormData();
    Array.from(fileInput.files).forEach(f => formData.append("files", f));

    try {
      const resp = await fetch("/api/analyze", {
        method: "POST",
        body: formData
      });

      const data = await resp.json();
      if (!resp.ok || data.error) throw new Error(data.error || "Compliance inspection failed.");

      currentInspectionData = data;
      badge.innerText = "Completed";
      rawPre.textContent = data.ocr_raw || "No raw text extracted.";

      // Render raw extracted declarations list
      fieldsContainer.innerHTML = "";
      const declarations = data.declarations || {};
      for (const [key, value] of Object.entries(declarations)) {
        const row = document.createElement("div");
        row.className = "field-row";
        const labelName = key.replace(/_/g, " ").toUpperCase();
        row.innerHTML = `<strong>${labelName}</strong> <span>${value || '<em style="color:#94a3b8">Not detected</em>'}</span>`;
        fieldsContainer.appendChild(row);
      }

      // Render Detailed Audit Report
      const rep = data.compliance_report;
      const borderCol = rep.score >= 80 ? "#15803d" : (rep.score >= 60 ? "#a16207" : "#b91c1c");
      const timestamp = new Date().toLocaleString("en-IN", { timeZoneName: "short" });

      let html = `
        <div class="audit-summary" style="border-left: 5px solid ${borderCol};">
          <div class="audit-summary-top">
            <div>
              <span class="report-tag">FORMAL INSPECTION DOSSIER</span>
              <h3 style="color: ${borderCol}; margin: 4px 0 2px 0;">${rep.verdict}</h3>
              <p style="margin: 0; font-size: 13px; color: #475569;">
                <b>Statute:</b> Legal Metrology Act, 2009 &amp; Packaged Commodities Rules, 2011 (as amended)
              </p>
            </div>
            <div class="audit-score-pill" style="border-color: ${borderCol}; color: ${borderCol};">
              <div class="score-num">${rep.score}%</div>
              <div class="score-lbl">${rep.passed_rules} / ${rep.total_rules} Passed</div>
            </div>
          </div>

          <div class="audit-meta-grid">
            <div><b>Inspection ID:</b> ${data.inspection_id}</div>
            <div><b>Generated:</b> ${timestamp}</div>
            <div><b>Product / Item:</b> ${declarations.commodity_name || "Unspecified"}</div>
            <div><b>Batch / Lot:</b> ${declarations.batch_number || "Not Stated"}</div>
          </div>
        </div>

        <table class="report-table">
          <thead>
            <tr>
              <th style="width: 15%;">Rule Citation</th>
              <th style="width: 25%;">Mandatory Requirement</th>
              <th style="width: 25%;">Scanned Label Content</th>
              <th style="width: 10%;">Finding</th>
              <th style="width: 25%;">Legal Notice / Corrective Action</th>
            </tr>
          </thead>
          <tbody>
      `;

      rep.rules.forEach(r => {
        html += `
          <tr>
            <td><b>${r.rule}</b></td>
            <td>${r.declaration}</td>
            <td>${r.found}</td>
            <td><span class="status-tag status-${r.status}">${r.status}</span></td>
            <td class="remediation-text">${r.remediation}</td>
          </tr>
        `;
      });

      html += `
          </tbody>
        </table>
        
        <div class="report-disclaimer">
          <strong>Statutory Notice:</strong> This audit report is generated automatically by OCR screening under Rule 6, Legal Metrology (Packaged Commodities) Rules, 2011. Non-compliance with mandatory declarations triggers penal proceedings under Section 36 of the Legal Metrology Act, 2009.
        </div>
      `;

      resultDiv.innerHTML = html;
      reportActions.style.display = "flex";

    } catch (err) {
      badge.innerText = "Failed";
      resultDiv.innerHTML = `
        <div style="color: #b91c1c; padding: 12px; background: #fee2e2; border-radius: 4px; font-size: 13px;">
          <strong>Scan Aborted:</strong> ${err.message}
        </div>
      `;
    } finally {
      analyzeBtn.disabled = false;
      analyzeBtn.innerText = "Run Compliance Audit";
    }
  });

  // Action: Print / PDF
  printReportBtn.addEventListener("click", () => {
    window.print();
  });

  // Action: JSON Download
  downloadJsonBtn.addEventListener("click", () => {
    if (!currentInspectionData) return;
    const blob = new Blob([JSON.stringify(currentInspectionData, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${currentInspectionData.inspection_id}_audit_report.json`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  });
});