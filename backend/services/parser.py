from pypdf import PdfReader

def parse_pdf_text(file_path: str):
    reader = PdfReader(file_path)
    full_text = ""
    for page in reader.pages:
        text = page.extract_text()
        if text:
            full_text += text + "\n"
    
    # Filter and extract concise key-value metric lines
    metrics = {}
    for line in full_text.splitlines():
        line = line.strip()
        if ":" in line:
            parts = line.split(":", 1)
            key = parts[0].strip()
            val = parts[1].strip()
            
            # Keep keys and values concise to exclude long paragraphs or prose
            if len(key) < 40 and len(val) < 60 and not key.lower().startswith(("case", "date", "note", "summary")):
                metrics[key] = val
                
    return metrics, full_text
