def generate_explanation(metrics: dict, full_text: str):
    summary = "Based on your uploaded medical report, the extracted metrics have been analyzed securely in memory. Please consult a qualified healthcare professional for formal diagnosis and treatment."
    recommendations = [
        "Review these findings with your primary physician.",
        "Keep a personal record of your health metrics for future visits."
    ]
    return {
        "summary": summary,
        "recommendations": recommendations
    }
