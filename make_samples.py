"""Generate the made-up sample reports used for testing. No real patient data.

Usage: python make_samples.py
"""
import pymupdf

SAMPLES = {
    # The lab's flag (L) contradicts its own range: 4,200 is inside 4,000-11,000.
    "sample_conflict_flag.pdf": [
        "COMPLETE BLOOD COUNT (SAMPLE - NOT A REAL PATIENT)",
        "Test            Result   Units       Reference Range   Flag",
        "Hemoglobin      14.1     g/dL        13.0 - 17.0",
        "WBC Count       4,200    /uL         4,000 - 11,000    L",
        "Platelets       250      x10^3/uL    150 - 400",
    ],
    # Indian digit grouping (lakh style).
    "sample_indian_grouping.pdf": [
        "COMPLETE BLOOD COUNT (SAMPLE - NOT A REAL PATIENT)",
        "Test              Result      Units    Reference Range         Flag",
        "Hemoglobin        13.5        g/dL     13.0 - 17.0",
        "Total WBC Count   8,500       /cumm    4,000 - 11,000",
        "Platelet Count    1,32,000    /cumm    1,50,000 - 4,50,000     L",
    ],
}


def write_pdf(path: str, lines: list[str]) -> None:
    doc = pymupdf.open()
    page = doc.new_page()
    y = 72
    for line in lines:
        page.insert_text((50, y), line, fontname="cour", fontsize=10)
        y += 16
    doc.save(path)
    doc.close()


if __name__ == "__main__":
    for name, lines in SAMPLES.items():
        write_pdf(name, lines)
        print("wrote", name)
