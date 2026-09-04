# SmartLabel AI — OCR Final Fixed Prototype

## Run in VS Code (Windows)

1. Install Tesseract OCR.
2. Confirm:
   `tesseract --version`
3. Open this folder in VS Code.
4. Terminal:
   `python app.py`
5. Open:
   `http://127.0.0.1:8000`

This version automatically checks:
- `tesseract` on PATH
- `C:\Program Files\Tesseract-OCR\tesseract.exe`
- `C:\Program Files (x86)\Tesseract-OCR\tesseract.exe`

If Tesseract is missing, the browser now shows an explicit error instead of silently displaying "Not detected".

For the sample footwear label, the OCR should be able to read:
- Product: W04-FR-CCP-KARMEN
- Net Contents: 2 N (1 Pair)
- MRP: ₹899/-
- Month & Year of Import: 07/2018
- Manufactured By: Payless India Franchising, LLC / Topeka, USA 66607

Batch/Lot is intentionally left for review when no explicit Batch/Lot label is visible.

The compliance rules are prototype screening rules, not a complete legal interpretation of the Legal Metrology rules.
