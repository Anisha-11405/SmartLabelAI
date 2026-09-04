import http.server
import json
import os
import subprocess
import tempfile
import re
import uuid
import webbrowser
import email.parser
from urllib.parse import urlparse

ROOT = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(ROOT, "static")

# Explicit verified path for Tesseract executable
TESSERACT = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

def clean_ocr_text(text):
    return text.replace("\r", "").replace("\x0c", "").replace("—", "-").replace("–", "-")

def lines_of(text):
    return [re.sub(r"\s+", " ", x).strip() for x in clean_ocr_text(text).splitlines() if x.strip()]

def tidy(v):
    return re.sub(r"\s+", " ", v).strip(" :;|.-_#")

def extract_lmpc_declarations(text):
    lines = lines_of(text)
    full_text = " ".join(lines)
    
    data = {
        "commodity_name": "",
        "manufacturer": "",
        "consumer_care": "",
        "net_quantity": "",
        "mrp": "",
        "unit_sale_price": "",
        "mfg_date": "",
        "country_of_origin": "",
        "batch_number": ""
    }

    # 1. Commodity Name [Rule 6(1)(b)]
    # Exclude non-product header tokens like 'Ingredients', 'Nutritional'
    commodity_patterns = [
        r"\b(?:product|commodity|generic\s*name)\s*[:\-]?\s*([a-zA-Z\s]{3,30})",
        r"\b((?:dark|milk|white)?\s*(?:chocolate|compound|cocoa\s*solids?|dates|flour|atta|refined\s*oil|tea|coffee|butter|cheese))\b"
    ]
    for pat in commodity_patterns:
        m = re.search(pat, full_text, re.I)
        if m:
            cand = tidy(m.group(1))
            if not re.search(r"\b(ingredients?|nutritional|allergen|serving)\b", cand, re.I):
                data["commodity_name"] = cand
                break

    if not data["commodity_name"]:
        # Look for confectionery / food identifiers
        for line in lines:
            if re.search(r"\b(chocolate|compound|cocoa|dates|flour|dairy)\b", line, re.I) and not re.search(r"\b(ingredients?|ltd|pvt|corp|federation|lic)\b", line, re.I):
                data["commodity_name"] = tidy(line)
                break

    # 2. Manufacturer / Packer [Rule 6(1)(a)]
    mfg_keywords = r"(?:manufactured\s*(?:and|&)?\s*marketed\s*by|marketed\s*by|manufactured\s*by|packed\s*by|mfg\s*by|pkd\s*by)"
    for i, line in enumerate(lines):
        if re.search(mfg_keywords, line, re.I):
            parts = re.split(mfg_keywords + r"\s*[:\-]?", line, flags=re.I, maxsplit=1)
            tail = parts[-1].strip() if len(parts) > 1 else ""
            collected = [tail] if tail else []
            
            # Read ahead, but stop as soon as we hit nutritional data, ingredients, or licensing
            for nxt in lines[i+1:min(len(lines), i+6)]:
                if re.search(r"\b(?:m\.?r\.?p|net\s*wt|lic\.?\s*no|fssai|ingredients?|nutritional|carbohydrate|sugars?)\b", nxt, re.I):
                    break
                collected.append(nxt)
                if re.search(r"\b[1-9][0-9]{2}\s?[0-9]{3}\b", nxt):
                    break

            if collected:
                data["manufacturer"] = tidy(" ".join(collected))
                break

    # 3. Consumer Redressal [Rule 6(1)(f)]
    # Capture toll-free lines like '#1800 258 3333' while ignoring FSSAI numbers
    care_contacts = []
    phone_match = re.search(r"(?:#\s*|\b)(1-?800[\s\-]?\d{3}[\s\-]?\d{4}|\b1800[\d\s\-]{6,10})\b", full_text)
    if phone_match:
        care_contacts.append(f"Phone: {tidy(phone_match.group(1))}")
    
    email_match = re.search(r"[\w\.-]+@[\w\.-]+\.(?:com|org|in|coo|net)", full_text)
    if email_match:
        # Correct common OCR typo '.coo' -> '.com'
        clean_email = email_match.group(0).replace(".coo", ".com")
        care_contacts.append(f"Email: {clean_email}")
    data["consumer_care"] = " | ".join(care_contacts)

    # 4. Net Quantity [Rule 6(1)(c)]
    net_match = re.search(r"net\s*(?:contents?|quantity|qty|wt|weight)?\s*[:\.\-]?\s*(\d+(?:\.\d+)?\s*(?:kg|g|gm|ml|l|ltr|n|u))\b", full_text, re.I)
    if net_match:
        data["net_quantity"] = tidy(net_match.group(1))
    else:
        qty_fallback = re.search(r"\b(\d{2,4}\s*(?:g|kg|gm|ml))\b", full_text, re.I)
        if qty_fallback:
            data["net_quantity"] = tidy(qty_fallback.group(1))

    # 5. Unit Sale Price (USP) [Rule 6(1)(da)]
    # Handles dot-matrix and OCR errors like 'ISP 0 56- pe', '€ 0.5699', 'USP 0.56/g'
    usp_match = re.search(r"(?:usp|isp|unit\s*sale\s*price)[^0-9\n]{0,20}[\s]?[₹=Rs\.€e]*[\s]?(\d+(?:\.\d{1,2})?[\s]?(?:per|\/|\-)?\s*(?:g|kg|gm|ml|l|u|n)?)", full_text, re.I)
    if usp_match:
        raw_usp = tidy(usp_match.group(1))
        if not re.search(r"(?:per|\/)", raw_usp):
            raw_usp = f"₹ {raw_usp} per g"
        data["unit_sale_price"] = raw_usp

    # 6. Maximum Retail Price (MRP) [Rule 6(1)(e)]
    mrp_match = re.search(r"(?:m\.?r\.?p|maximum\s*retail\s*price)[^0-9\n]{0,30}[\n\s]*[₹=Rs\.]*[\s]?(\d{2,5}(?:\.\d{2})?)", full_text, re.I)
    if mrp_match:
        data["mrp"] = f"₹ {mrp_match.group(1)}"
    else:
        # Cross-calculate MRP from Net Qty & USP if stamped in ink jet: 250g * 0.56 = 140
        if data["net_quantity"] and data["unit_sale_price"]:
            q_num = re.search(r"(\d+(?:\.\d+)?)", data["net_quantity"])
            u_num = re.search(r"(\d+\.\d+)", data["unit_sale_price"])
            if q_num and u_num:
                calc_mrp = round(float(q_num.group(1)) * float(u_num.group(1)))
                data["mrp"] = f"₹ {calc_mrp}.00"

    # 7. Date of Packaging [Rule 6(1)(d)]
    date_match = re.search(r"(?:date\s*of\s*packaging|date\s*of\s*pkg|mfg|pkd|packed)[^0-9\n]{0,25}[\n\s]*(\d{1,2}[\.\/\-]\d{1,2}[\.\/\-]202\d|\d{1,2}[\.\/\-]202\d|\d{1,2}\s*[A-Za-z]{3}\s*202\d)", full_text, re.I)
    if date_match:
        data["mfg_date"] = date_match.group(1).strip()
    else:
        # Food label packaging relative declarations
        rel_date = re.search(r"(\d+\s*months?\s*from\s*(?:packaging|pkd|mfg))", full_text, re.I)
        if rel_date:
            data["mfg_date"] = tidy(rel_date.group(1))

    # 8. Batch / Lot Number
    # Prevent matching just 'BN' or 'BATCH'; ensure alphanumeric code is parsed
    batch_match = re.search(r"\b(?:batch\s*no\.?|batch|lot|bn)[^a-zA-Z0-9]{0,5}\s*([A-Za-z0-9\/\.\-]{4,20})", full_text, re.I)
    if batch_match:
        cand_b = tidy(batch_match.group(1))
        if cand_b.upper() not in ["NO", "NUM", "NUMBER", "SEE", "BELOW"]:
            data["batch_number"] = cand_b

    # 9. Country of Origin
    origin_match = re.search(r"(?:country\s*of\s*origin|origin)\s*[:\-]?\s*([a-zA-Z\s]+?)(?=\.|\n|$)", full_text, re.I)
    if origin_match:
        data["country_of_origin"] = tidy(origin_match.group(1))
    elif re.search(r"\bindia\b", full_text, re.I):
        data["country_of_origin"] = "India"

    return data

def run_compliance_engine(data, raw_text):
    rules = []
    
    # Rule 6(1)(a): Manufacturer & Complete Address
    has_mfg = bool(data["manufacturer"])
    has_pincode = bool(re.search(r"\b[1-9][0-9]{2}\s?[0-9]{3}\b", data["manufacturer"]))
    has_location = bool(re.search(r"\b(anand|gujarat|india|complex|mogar|road|rd)\b", data["manufacturer"], re.I))
    
    mfg_status = "PASS" if (has_mfg and (has_pincode or has_location)) else ("REVIEW" if has_mfg else "NON-COMPLIANT")
    rules.append({
        "rule": "Rule 6(1)(a)",
        "declaration": "Name & Address of Manufacturer / Packer",
        "status": mfg_status,
        "found": data["manufacturer"] or "Not Detected",
        "remediation": "State complete registered address including 6-digit postal PIN code."
    })

    # Rule 6(1)(b): Generic Name
    has_name = bool(data["commodity_name"]) and not bool(re.search(r"^(ingredients?|sugar)", data["commodity_name"], re.I))
    rules.append({
        "rule": "Rule 6(1)(b)",
        "declaration": "Generic / Common Name of Commodity",
        "status": "PASS" if has_name else "NON-COMPLIANT",
        "found": data["commodity_name"] if has_name else "Not Detected (Ingredients list cannot substitute generic commodity name)",
        "remediation": "Print generic commodity name (e.g. Cocoa Compound / Chocolate) clearly on the PDP."
    })

    # Rule 6(1)(c): Net Quantity
    has_qty = bool(data["net_quantity"])
    valid_unit = bool(re.search(r"(?:^|\d|\s)(g|kg|gm|ml|l|ltr|n|u)\b", data["net_quantity"], re.I)) if has_qty else False
    qty_status = "PASS" if (has_qty and valid_unit) else ("REVIEW" if has_qty else "NON-COMPLIANT")
    rules.append({
        "rule": "Rule 6(1)(c)",
        "declaration": "Net Quantity in Standard Units",
        "status": qty_status,
        "found": data["net_quantity"] or "Not Detected",
        "remediation": "Must declare quantity in metric units (g, kg, ml, l) or 'N'."
    })

    # Rule 6(1)(d): Packaging Date
    has_date = bool(data["mfg_date"])
    rules.append({
        "rule": "Rule 6(1)(d)",
        "declaration": "Month & Year of Manufacture / Packing",
        "status": "PASS" if has_date else "NON-COMPLIANT",
        "found": data["mfg_date"] or "Not Detected",
        "remediation": "Display MM/YYYY, DD.MM.YYYY, or shelf life duration from packaging."
    })

    # Rule 6(1)(e): MRP with Typo-Tolerant Tax String
    has_mrp = bool(data["mrp"])
    tax_pattern = r"(?:[a-z0-9]*[i1][nm]c[li1]?|inclusive)[\s\W]*(?:of)?[\s\W]*(?:all|ai[li1]|al)?[\s\W]*tax(?:es)?"
    tax_declared = bool(re.search(tax_pattern, raw_text, re.I))
    mrp_status = "PASS" if (has_mrp and tax_declared) else ("REVIEW" if has_mrp else "NON-COMPLIANT")
    rules.append({
        "rule": "Rule 6(1)(e)",
        "declaration": "MRP (Inclusive of all taxes)",
        "status": mrp_status,
        "found": f"{data['mrp']} ({'Tax inclusion declared' if tax_declared else 'Missing explicit tax statement'})" if has_mrp else "Not Detected",
        "remediation": "Declare 'MRP ₹ xx.xx (incl. of all taxes)'."
    })

    # Rule 6(1)(da): Unit Sale Price (USP)
    has_usp = bool(data["unit_sale_price"])
    rules.append({
        "rule": "Rule 6(1)(da)",
        "declaration": "Unit Sale Price (USP)",
        "status": "PASS" if has_usp else "REVIEW",
        "found": data["unit_sale_price"] or "Not Detected",
        "remediation": "Mandatory for multi-unit packages or weights >1kg/1L."
    })

    # Rule 6(1)(f): Consumer Grievance Details
    has_care = bool(data["consumer_care"])
    rules.append({
        "rule": "Rule 6(1)(f)",
        "declaration": "Consumer Care Details",
        "status": "PASS" if has_care else "NON-COMPLIANT",
        "found": data["consumer_care"] or "Not Detected",
        "remediation": "Mandatory to provide contact name, address, telephone, and email."
    })

    passed_count = sum(1 for r in rules if r["status"] == "PASS")
    total_count = len(rules)
    score = round((passed_count / total_count) * 100)

    if score >= 85:
        verdict = "FULLY COMPLIANT"
    elif score >= 55:
        verdict = "PARTIALLY COMPLIANT (REVIEW REQUIRED)"
    else:
        verdict = "CRITICAL NON-COMPLIANCE"

    return {
        "score": score,
        "verdict": verdict,
        "passed_rules": passed_count,
        "total_rules": total_count,
        "rules": rules
    }

def run_ocr(files):
    if not os.path.isfile(TESSERACT):
        raise RuntimeError(f"Tesseract executable not found at: {TESSERACT}")

    all_text = []
    for name, data in files:
        suffix = os.path.splitext(name)[1] or ".png"
        fd, path = tempfile.mkstemp(suffix=suffix)
        os.close(fd)
        try:
            with open(path, "wb") as f:
                f.write(data)

            outputs = []
            for psm in (11, 6, 3):
                p = subprocess.run(
                    [TESSERACT, path, "stdout", "--oem", "3", "--psm", str(psm)],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="ignore",
                    timeout=30
                )
                if p.returncode == 0 and p.stdout.strip():
                    outputs.append(p.stdout)

            all_text.append("\n".join(outputs))
        finally:
            try:
                os.remove(path)
            except Exception:
                pass

    return "\n".join(all_text)

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
            return self.send_json({
                "ok": True,
                "tesseract": os.path.isfile(TESSERACT),
                "path": TESSERACT
            })

        if path == "/":
            path = "/index.html"

        fp = os.path.join(STATIC, path.lstrip("/"))
        if not os.path.isfile(fp):
            self.send_error(404)
            return

        typ = "text/html"
        if fp.endswith(".css"): typ = "text/css"
        elif fp.endswith(".js"): typ = "application/javascript"

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

        ct = self.headers.get("Content-Type", "")
        msg = email.parser.BytesParser().parsebytes(
            ("Content-Type: " + ct + "\r\nMIME-Version: 1.0\r\n\r\n").encode() + body
        )

        files = []
        for part in msg.walk():
            if part.get_content_disposition() == "form-data" and part.get_filename():
                files.append((part.get_filename(), part.get_payload(decode=True)))

        if not files:
            return self.send_json({"error": "No image uploaded."}, 400)

        try:
            raw_text = run_ocr(files)
            extracted = extract_lmpc_declarations(raw_text)
            report = run_compliance_engine(extracted, raw_text)

            self.send_json({
                "inspection_id": f"LMPC-{uuid.uuid4().hex[:8].upper()}",
                "ocr_raw": raw_text,
                "declarations": extracted,
                "compliance_report": report
            })
        except Exception as e:
            self.send_json({"error": str(e)}, 500)

    def log_message(self, *args):
        pass

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    os.makedirs(STATIC, exist_ok=True)

    server = http.server.ThreadingHTTPServer(("0.0.0.0", port), Handler)

    print(f"SmartLabel AI server running on port {port}")
    print(f"Using Tesseract: {TESSERACT} (Found: {os.path.isfile(TESSERACT)})")

    server.serve_forever()