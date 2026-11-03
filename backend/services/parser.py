import re

def extract_lab_metrics(text: str) -> list[dict]:
    """
    Parses raw text from a medical report to extract lab test names, 
    values, units, and reference ranges using flexible pattern matching.
    """
    metrics = []
    
    # Common pattern for lab lines: Test Name   Value   Unit   (Reference Range)
    # Example: Glucose    99    mg/dL    (70 - 99)
    # This regex looks for a test name, a numeric value with optional decimals, a unit, and an optional range.
    lines = text.split("\n")
    
    # Flexible regex pattern for lab lines
    # Group 1: Test Name, Group 2: Value, Group 3: Unit, Group 4: Reference Range (optional)
    pattern = re.compile(r"^([A-Za-z\s\-\/\(\)]+?)\s+([0-9]+\.?[0-9]*)\s+([a-zA-Z%\/\._]+)(?:\s+([\(\[\{]?\d+[\d\.\-\s\%\<\>]+[\)\]\}]?))?", re.IGNORECASE)

    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        match = pattern.search(line)
        if match:
            test_name = match.group(1).strip()
            test_value = match.group(2).strip()
            unit = match.group(3).strip()
            ref_range = match.group(4).strip() if match.group(4) else "N/A"
            
            # Simple heuristic status check (can be expanded)
            status = "Normal" 
            
            metrics.append({
                "test_name": test_name,
                "test_value": test_value,
                "unit": unit,
                "reference_range": ref_range,
                "status": status
            })
            
    # Fallback / Generic extraction if strict regex lines don't match standard multi-column formats
    if not metrics:
        # Fallback: look for lines containing numbers and common units
        unit_keywords = ["mg/dl", "g/dl", "mmol/l", "u/l", "g/l", "%", "fl", "pg", "cells/ul"]
        for line in lines:
            lower_line = line.lower()
            if any(u in lower_line for u in unit_keywords):
                parts = line.split()
                if len(parts) >= 2:
                    # Try to find a numeric part
                    for i, part in enumerate(parts):
                        if re.match(r"^\d+\.?\d*$", part):
                            test_name = " ".join(parts[:i])
                            test_value = part
                            unit = parts[i+1] if i+1 < len(parts) else "N/A"
                            ref_range = " ".join(parts[i+2:]) if i+2 < len(parts) else "N/A"
                            if len(test_name) > 1:
                                metrics.append({
                                    "test_name": test_name,
                                    "test_value": test_value,
                                    "unit": unit,
                                    "reference_range": ref_range,
                                    "status": "Normal"
                                })
                            break

    return metrics
