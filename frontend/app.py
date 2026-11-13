"""MediExplain Streamlit front end.

Run (backend must be running):
    streamlit run frontend/app.py

The backend URL comes from the MEDIEXPLAIN_API_URL environment variable
(default http://127.0.0.1:8000). Nothing is stored: the report goes to the
backend over HTTP and the result lives only in this browser session.
"""
import os

import pandas as pd
import requests
import streamlit as st

API_URL = os.environ.get("MEDIEXPLAIN_API_URL", "http://127.0.0.1:8000").rstrip("/")
MAX_BYTES = 10 * 1024 * 1024
# The backend gives the whole model chain 90 s (TOTAL_BUDGET_S). Wait a bit longer.
REQUEST_TIMEOUT_S = 120

DEFAULT_DISCLAIMER = (
    "This explanation is for education only and is not medical advice, a diagnosis, "
    "or a treatment plan. Always talk to a qualified healthcare professional about your results."
)

FRIENDLY_ERRORS = {
    400: (
        "We couldn't open this file. Please upload your lab report as a PDF, PNG or JPG. "
        "If it is one of those, the file may be damaged or the image too large."
    ),
    413: "This file is larger than 10 MB. Please upload a smaller file.",
    422: (
        "We couldn't find any readable text in this file. If it's a photo, try again with "
        "a sharp, well-lit, straight picture of the whole page. A digital PDF from your "
        "lab's website or app works best."
    ),
    501: (
        "Reading photos and scanned reports is not available right now. "
        "Please upload a digital PDF of your report instead."
    ),
    503: (
        "The explanation service is busy right now. Your report was not saved. "
        "Please wait a minute and try again."
    ),
}
MIME_TYPES = {"pdf": "application/pdf", "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg"}
OCR_NOTE = (
    "This report was read from an image, so some numbers may have been misread. "
    "Compare each result with your original report."
)
GENERIC_ERROR = "Something went wrong while explaining this report. Please try again."

STATUS_LABEL = {"low": "LOW", "high": "HIGH", "normal": "Normal", "unknown": "Unknown"}
STATUS_STYLE = {
    "LOW": "background-color: rgba(59, 130, 246, 0.18); font-weight: 600;",
    "HIGH": "background-color: rgba(239, 68, 68, 0.18); font-weight: 600;",
}


# ---- logic (no Streamlit calls; unit-tested) ---------------------------------

def friendly_error(status_code: int) -> str:
    return FRIENDLY_ERRORS.get(status_code, GENERIC_ERROR)


def explain_report(file_name: str, data: bytes) -> tuple[dict | None, str | None]:
    """POST the report to the backend. Returns (result, None) or (None, user message)."""
    if len(data) > MAX_BYTES:
        return None, FRIENDLY_ERRORS[413]
    try:
        r = requests.post(
            f"{API_URL}/reports/upload",
            # The backend checks the real type by file signature; this is only a hint.
            files={"file": (file_name, data, mime_type(file_name))},
            timeout=REQUEST_TIMEOUT_S,
        )
    except requests.exceptions.Timeout:
        return None, FRIENDLY_ERRORS[503]
    except requests.exceptions.ConnectionError:
        return None, (
            "The MediExplain service is not reachable. "
            "If you are running it yourself, start the backend first."
        )
    if r.status_code != 200:
        return None, friendly_error(r.status_code)
    try:
        return r.json(), None
    except ValueError:
        return None, GENERIC_ERROR


def mime_type(file_name: str) -> str:
    ext = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""
    return MIME_TYPES.get(ext, "application/octet-stream")


def marker_status(marker: dict) -> str:
    return STATUS_LABEL.get(marker.get("status", "unknown"), "Unknown")


def markers_table(markers: list[dict]) -> pd.DataFrame:
    rows = []
    for m in markers:
        verified = m.get("verified")
        rows.append({
            "Test": m.get("name", ""),
            "Result": m.get("value", ""),
            "Unit": m.get("unit", ""),
            "Reference range": m.get("reference_range", ""),
            "Status": marker_status(m),
            "Checked": "Yes" if verified else ("Please check" if verified is False else ""),
        })
    return pd.DataFrame(
        rows, columns=["Test", "Result", "Unit", "Reference range", "Status", "Checked"]
    )


def style_table(df: pd.DataFrame):
    """Highlight LOW and HIGH rows. Status is also written out, so colour is not the only cue."""
    def row_style(row):
        css = STATUS_STYLE.get(row["Status"], "")
        return [css] * len(row)
    return df.style.apply(row_style, axis=1)


def questions_text(questions: list[str]) -> str:
    lines = ["Questions to ask my doctor about my lab report", ""]
    lines += [f"{i}. {q}" for i, q in enumerate(questions, 1)]
    return "\n".join(lines) + "\n"


# ---- page --------------------------------------------------------------------

def render_result(result: dict) -> None:
    if result.get("emergency_notice"):
        st.error(result["emergency_notice"], icon="🚨")

    st.subheader(result.get("document_type") or "Your report")
    if result.get("ocr_used"):
        st.warning(OCR_NOTE, icon="📷")
    if result.get("summary"):
        st.write(result["summary"])

    warnings = result.get("warnings") or []
    if warnings:
        with st.container(border=True):
            st.markdown("**Please double-check these against your original report**")
            for w in warnings:
                st.warning(w, icon="⚠️")

    markers = result.get("markers") or []
    if markers:
        st.markdown("#### Your results")
        st.dataframe(style_table(markers_table(markers)), hide_index=True, width="stretch")
        st.caption("LOW and HIGH mean outside the reference range printed on your report.")

        st.markdown("#### What each result means")
        for m in markers:
            label = f"{m.get('name', 'Result')}: {m.get('value', '')} {m.get('unit', '')}".strip()
            status = marker_status(m)
            if status in ("LOW", "HIGH"):
                label += f" ({status})"
            with st.expander(label):
                st.write(m.get("explanation") or "No explanation available.")
                for note in m.get("verification_notes") or []:
                    st.caption(f"Check: {note}")
    else:
        st.info("No test results were found in this document.")

    questions = result.get("recommendations") or []
    if questions:
        st.markdown("#### Questions to ask your doctor")
        for i, q in enumerate(questions, 1):
            st.markdown(f"{i}. {q}")
        text = questions_text(questions)
        st.caption("Copy with the button in the corner of the box, or download them.")
        st.code(text, language=None)
        st.download_button(
            "Download questions (.txt)", text,
            file_name="questions_for_my_doctor.txt", mime="text/plain",
        )

    sources = result.get("glossary_sources") or []
    if sources:
        links = ", ".join(f"[{s['title']}]({s['url']})" for s in sources)
        credit = result.get("glossary_attribution") or "Source: MedlinePlus, National Library of Medicine"
        st.caption(f"Test definitions used: {links}. {credit}.")


def main() -> None:
    st.set_page_config(page_title="MediExplain", page_icon="🩺", layout="centered")
    result = st.session_state.get("result")
    disclaimer = (result or {}).get("disclaimer") or DEFAULT_DISCLAIMER

    st.title("MediExplain")
    st.write("Upload a lab report and get a plain-language explanation of your results.")
    st.info(disclaimer, icon="ℹ️")

    uploaded = st.file_uploader(
        "Lab report (PDF, PNG or JPG, up to 10 MB)", type=["pdf", "png", "jpg", "jpeg"],
        help="Your file is only used to create this explanation and is not stored.",
    )
    if uploaded is None and "file_id" in st.session_state:
        # The user removed their file: forget its explanation.
        st.session_state.pop("result", None)
        st.session_state.pop("error", None)
        st.session_state.pop("file_id", None)
    elif uploaded is not None and uploaded.file_id != st.session_state.get("file_id"):
        # A new file: forget the previous explanation.
        st.session_state["file_id"] = uploaded.file_id
        st.session_state.pop("result", None)
        st.session_state.pop("error", None)

    if uploaded is not None and st.button("Explain my report", type="primary"):
        with st.spinner("Reading and explaining your report. This usually takes a few seconds..."):
            result, error = explain_report(uploaded.name, uploaded.getvalue())
        st.session_state["result"] = result
        st.session_state["error"] = error
        st.rerun()  # redraw so the top disclaimer uses the backend's text

    if st.session_state.get("error"):
        st.error(st.session_state["error"])
    if st.session_state.get("result"):
        render_result(st.session_state["result"])

    st.divider()
    st.caption(f"**Disclaimer:** {disclaimer}")


if __name__ == "__main__":
    main()
