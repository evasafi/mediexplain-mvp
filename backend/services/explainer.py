def generate_explanation_report(metrics: list[dict]) -> tuple[str, str]:
    """
    Analyzes extracted lab metrics and generates a compassionate, 
    plain-language summary and actionable recommendations.
    """
    if not metrics:
        return (
            "We successfully processed your document, but could not automatically detect individual structured lab values. "
            "Please consult a healthcare professional to review your report directly.",
            "Review the physical copy of your report with your primary care provider."
        )

    summary_lines = []
    recommendations_list = []
    
    summary_lines.append(f"MediExplain has analyzed your lab report containing {len(metrics)} tested parameters.")
    summary_lines.append("Here is an overview of your results in plain language:")

    abnormal_count = 0
    for m in metrics:
        name = m.get("test_name", "Unknown Test")
        val = m.get("test_value", "")
        unit = m.get("unit", "")
        ref = m.get("reference_range", "N/A")
        
        # Simple descriptive framing for the user
        line = f"• **{name}**: Measured at **{val} {unit}** (Standard reference range: {ref})."
        summary_lines.append(line)

    summary_lines.append("\n**General Note:** Lab results are best interpreted within the full context of your personal medical history, symptoms, and lifestyle. Always discuss these findings with your doctor.")
    
    summary = "\n".join(summary_lines)
    recommendations = "1. Schedule a follow-up appointment with your physician or healthcare provider to review these results in detail.\n2. Keep a digital or physical copy of this lab report handy for your next medical visit.\n3. Write down any questions or symptoms you've been experiencing to discuss during your consultation."

    return summary, recommendations
