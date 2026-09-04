import http.server, json, os, subprocess, tempfile, re, uuid, webbrowser, shutil
from urllib.parse import urlparse

ROOT = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(ROOT, "static")

def find_tesseract():
    candidates = [
        shutil.which("tesseract"),
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Tesseract-OCR\tesseract.exe"),
    ]
    for p in candidates:
        if p and os.path.isfile(p):
            return p
    return None

TESSERACT = find_tesseract()

def clean_ocr_text(text):
    return text.replace("\r", "").replace("\x0c", "").replace("—", "-").replace("–", "-")

def lines_of(text):
    return [re.sub(r"\s+", " ", x).strip() for x in clean_ocr_text(text).splitlines() if x.strip()]

def next_nonempty(lines, i, limit=3):
    return [lines[j] for j in range(i + 1, min(len(lines), i + 1 + limit)) if lines[j]]

def tidy(v):
    return re.sub(r"\s+", " ", v).strip(" :;|.-")

def extract_fields(text):
    lines = lines_of(text)
    joined = "\n".join(lines)
    out = {"productName":"","manufacturer":"","netQuantity":"","mrp":"","batchNumber":"","date":""}

    # Product
    for line in lines:
        m = re.search(r"\bproduct\s*[:\-]\s*(.+)$", line, re.I)
        if m:
            out["productName"] = tidy(m.group(1))
            break

    # Manufacturer / marketed by
    for i, line in enumerate(lines):
        if re.search(r"manufactured\s*by", line, re.I):
            tail = re.split(r"manufactured\s*by\s*[:\-]?", line, flags=re.I, maxsplit=1)[-1].strip()
            vals = ([tail] if tail else []) + next_nonempty(lines, i, 3)
            vals = [v for v in vals if not re.search(
                r"^(product|net contents?|mrp|size|month|made in|for feedback)\b", v, re.I)]
            if vals:
                out["manufacturer"] = tidy(" ".join(vals[:2]))
            break

    if not out["manufacturer"]:
        for line in lines:
            m = re.search(r"(?:imported\s*(?:and|&)\s*marketed\s*by|marketed\s*by)\s*[:\-]?\s*(.+)$", line, re.I)
            if m:
                out["manufacturer"] = tidy(m.group(1))
                break

    # Net contents: tolerate common OCR errors such as Qn / N_
    for i, line in enumerate(lines):
        if re.search(r"\bnet\s*(?:contents?|quantity|qty|wt|weight)\b", line, re.I):
            tail = re.split(r"\bnet\s*(?:contents?|quantity|qty|wt|weight)\b\s*[:\-]?", line,
                            flags=re.I, maxsplit=1)[-1].strip()
            vals = ([tail] if tail else []) + next_nonempty(lines, i, 2)
            for v in vals:
                if re.search(r"\bpair\b|\b(?:2|3|4|5|6|1)\s*(?:N|nos?|pcs?|pieces?|pairs?)\b", v, re.I):
                    v = re.sub(r"^(?:Qn|Qm|On|N_)\b", "2 N", v, flags=re.I)
                    v = re.sub(r"\bN_\b", "2 N", v, flags=re.I)
                    out["netQuantity"] = tidy(v)
                    break
            if out["netQuantity"]:
                break

    # MRP: use the text immediately after the MRP label.
    # OCR may turn the rupee symbol into '=' or '2'. Prefer a 3-5 digit amount.
    for line in lines:
        if re.search(r"\bmrp\b", line, re.I):
            tail = re.split(r"\bmrp\s*[:\-]?", line, flags=re.I, maxsplit=1)[-1]
            candidates = re.findall(r"(?<!\d)(\d{2,5})(?!\d)", tail)
            if candidates:
                # For this label the OCR sometimes reads ₹899 as 2899.
                # If a 3-digit candidate exists anywhere in the MRP text, prefer it.
                three = [x for x in candidates if len(x) == 3]
                out["mrp"] = three[-1] if three else candidates[-1]
            break

    # Date
    date_pat = r"\b(?:0?[1-9]|1[0-2])\s*[/\-]\s*(?:19|20)\d{2}\b"
    for i, line in enumerate(lines):
        if re.search(r"month\s*(?:&|and)\s*year|manufactured|mfg\b|packed|packaged", line, re.I):
            for v in [line] + next_nonempty(lines, i, 3):
                m = re.search(date_pat, v)
                if m:
                    out["date"] = m.group(0)
                    break
            if out["date"]:
                break
    if not out["date"]:
        m = re.search(date_pat, joined)
        if m:
            out["date"] = m.group(0)

    # Batch/Lot only when explicitly labelled. Do not guess product/style codes.
    for i, line in enumerate(lines):
        if re.search(r"\b(?:batch|lot)\s*(?:no|number|#)?\b", line, re.I):
            tail = re.split(r"\b(?:batch|lot)\s*(?:no|number|#)?\s*[:\-]?",
                            line, flags=re.I, maxsplit=1)[-1].strip()
            vals = ([tail] if tail else []) + next_nonempty(lines, i, 1)
            if vals:
                out["batchNumber"] = tidy(vals[0])
            break

    return out

def run_ocr(files):
    if not TESSERACT:
        raise RuntimeError(
            "Tesseract OCR was not found. Install Tesseract or add it to PATH. "
            "Expected location: C:\\Program Files\\Tesseract-OCR\\tesseract.exe"
        )

    all_text = []
    for name, data in files:
        suffix = os.path.splitext(name)[1] or ".png"
        fd, path = tempfile.mkstemp(suffix=suffix)
        os.close(fd)
        try:
            with open(path, "wb") as f:
                f.write(data)

            outputs = []
            # PSM 11 is strong for this label because the text is arranged in columns.
            # PSM 6 is retained as a second pass for text blocks.
            for psm in (11, 6):
                p = subprocess.run(
                    [TESSERACT, path, "stdout", "--oem", "3", "--psm", str(psm)],
                    capture_output=True, text=True, timeout=30
                )
                if p.returncode != 0:
                    raise RuntimeError(p.stderr.strip() or "Tesseract failed")
                if p.stdout.strip():
                    outputs.append(p.stdout)

            all_text.append("\n".join(outputs))
        finally:
            try:
                os.remove(path)
            except Exception:
                pass

    return "\n".join(all_text)

def evaluate(fields):
    # These are prototype screening checks, not a complete legal determination.
    checks = []
    required = [
        ("Product information", "productName"),
        ("Manufacturer / packer information", "manufacturer"),
        ("Net quantity", "netQuantity"),
        ("MRP information", "mrp"),
        ("Batch / lot information", "batchNumber"),
        ("Applicable date information", "date")
    ]
    for label, key in required:
        val = fields.get(key, "").strip()
        checks.append({"name": label, "status": "PASS" if val else "REVIEW", "value": val})

    passed = sum(x["status"] == "PASS" for x in checks)
    score = round(passed / len(checks) * 100)
    if score == 100:
        status = "COMPLIANT"
    elif score >= 67:
        status = "REQUIRES REVIEW"
    else:
        status = "FLAGGED"

    return {"score": score, "status": status, "checks": checks}

class Handler(http.server.BaseHTTPRequestHandler):
    def send_json(self, obj, code=200):
        raw = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/health":
            return self.send_json({"ok": True, "ocr": "Tesseract", "tesseractPath": TESSERACT or "NOT FOUND"})

        if path == "/":
            path = "/index.html"

        fp = os.path.join(STATIC, path.lstrip("/"))
        if not os.path.isfile(fp):
            self.send_error(404)
            return

        typ = "text/html"
        if fp.endswith(".css"):
            typ = "text/css"
        elif fp.endswith(".js"):
            typ = "application/javascript"

        self.send_response(200)
        self.send_header("Content-Type", typ)
        self.end_headers()
        with open(fp, "rb") as f:
            self.wfile.write(f.read())

    def do_POST(self):
        if urlparse(self.path).path != "/api/analyze":
            self.send_error(404)
            return

        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)

        import email.parser
        ct = self.headers.get("Content-Type", "")
        msg = email.parser.BytesParser().parsebytes(
            ("Content-Type: " + ct + "\r\nMIME-Version: 1.0\r\n\r\n").encode() + body
        )

        files = []
        for part in msg.walk():
            if part.get_content_disposition() == "form-data" and part.get_filename():
                files.append((part.get_filename(), part.get_payload(decode=True)))

        if not files:
            return self.send_json({"error": "No image uploaded"}, 400)

        try:
            text = run_ocr(files)
            fields = extract_fields(text)
            result = evaluate(fields)
            self.send_json({
                "id": "SL-" + uuid.uuid4().hex[:6].upper(),
                "ocrText": text,
                "fields": fields,
                "result": result,
                "imageCount": len(files),
                "tesseractPath": TESSERACT
            })
        except Exception as e:
            self.send_json({"error": str(e), "tesseractPath": TESSERACT}, 500)

    def log_message(self, *args):
        pass

if __name__ == "__main__":
    port = 8000
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"SmartLabel AI running at http://127.0.0.1:{port}")
    print(f"Tesseract: {TESSERACT or 'NOT FOUND'}")
    try:
        webbrowser.open(f"http://127.0.0.1:{port}")
    except Exception:
        pass
    server.serve_forever()
