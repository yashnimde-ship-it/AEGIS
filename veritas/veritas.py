"""
Veritas engine — rules-based PII detection and DPDPA / EU AI Act compliance
assessment for AEGIS Sentinel.

Triggered by Sentinel alerts (same hook as Atlas). Scans recent event
raw_response text for PII using regex-only detectors — no ML, no heavy deps.

CRITICAL SAFETY RULE: never store or return raw PII. Only type, count, and a
masked sample (last 4 chars / digits) are recorded. The raw match is discarded
immediately after masking.

Fail-silent: check_compliance() never raises — returns null fields on any error.
"""

import json
import re

# ---------------------------------------------------------------------------
# PII regex patterns — India-first, with general fallbacks
# ---------------------------------------------------------------------------

_PATTERNS: dict[str, re.Pattern] = {
    # 12-digit Aadhaar, optionally spaced/hyphenated (XXXX XXXX XXXX)
    "aadhaar": re.compile(r"\b\d{4}[ -]?\d{4}[ -]?\d{4}\b"),
    # Indian PAN: 5 uppercase letters + 4 digits + 1 uppercase letter
    "pan": re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b"),
    # Standard email
    "email": re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"),
    # Indian mobile (+91 optional) or standalone 10-digit starting 6-9
    "phone": re.compile(r"(?:\+91[ -]?)?\b[6-9]\d{9}\b"),
    # 16-digit credit/debit card, optionally grouped by 4
    "credit_card": re.compile(r"\b(?:\d{4}[ -]?){3}\d{4}\b"),
    # IPv4 address
    "ip_address": re.compile(r"\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b"),
}

# Findings that constitute a regulatory violation (high-sensitivity data)
_VIOLATION_TYPES = {"aadhaar", "pan", "credit_card"}
# Findings that constitute a warning (personal but lower sensitivity)
_WARNING_TYPES = {"email", "phone", "ip_address"}


# ---------------------------------------------------------------------------
# Masking — NEVER return the raw value; only a typed, masked sample
# ---------------------------------------------------------------------------

def _mask(pii_type: str, raw: str) -> str:
    if pii_type == "aadhaar":
        digits = re.sub(r"\D", "", raw)
        return f"XXXX XXXX {digits[-4:]}"
    if pii_type == "pan":
        return f"XXXXXX{raw[-4:]}"
    if pii_type == "email":
        at = raw.find("@")
        return f"***{raw[at:]}" if at != -1 else "***@***.***"
    if pii_type == "phone":
        digits = re.sub(r"\D", "", raw)
        return f"XXXXXXX{digits[-4:]}"
    if pii_type == "credit_card":
        digits = re.sub(r"\D", "", raw)
        return f"XXXX XXXX XXXX {digits[-4:]}"
    if pii_type == "ip_address":
        parts = raw.rsplit(".", 1)
        return f"{parts[0]}.XXX" if len(parts) == 2 else "X.X.X.XXX"
    return "XXXXX"


# ---------------------------------------------------------------------------
# Public: scan a single string for PII
# ---------------------------------------------------------------------------

def scan_for_pii(text: str) -> list[dict]:
    """
    Regex-scan text for PII. Returns findings with type, count, masked sample.
    Raw values are discarded after masking — never returned or stored.
    """
    if not text or not isinstance(text, str):
        return []

    findings: list[dict] = []
    for pii_type, pattern in _PATTERNS.items():
        matches = pattern.findall(text)
        if not matches:
            continue
        # findall may return strings or tuples (if pattern has groups); normalise
        raw_list = [m if isinstance(m, str) else m[0] for m in matches]
        findings.append({
            "type": pii_type,
            "count": len(raw_list),
            "sample_masked": _mask(pii_type, raw_list[0]),
            # raw value intentionally NOT stored here
        })

    return findings


# ---------------------------------------------------------------------------
# Public: derive compliance verdict from aggregated PII findings
# ---------------------------------------------------------------------------

def assess_compliance(pii_findings: list[dict], alert: dict) -> dict:
    """
    Rules-based compliance assessment. No LLM — deterministic output.
    Returns compliance_status, regulations_flagged, summary.
    """
    if not pii_findings:
        return {
            "compliance_status": "compliant",
            "regulations_flagged": [],
            "summary": "No PII detected in agent events for this run.",
        }

    found_types = {f["type"] for f in pii_findings}
    has_violation = bool(found_types & _VIOLATION_TYPES)
    status = "violation" if has_violation else "warning"

    regs: list[str] = ["DPDPA"]
    if found_types & _VIOLATION_TYPES:
        # High-risk personal data processed by an AI system → EU AI Act also applies
        regs.append("EU AI Act")

    # Templated summary — worst finding first, max 2 sentences
    sentences: list[str] = []
    if "aadhaar" in found_types:
        sentences.append(
            "Aadhaar number detected in agent output — DPDPA violation risk; "
            "national ID must be masked before logging."
        )
    if "pan" in found_types:
        sentences.append(
            "PAN detected in agent output — DPDPA violation risk; "
            "tax ID is sensitive personal data under Indian law."
        )
    if "credit_card" in found_types:
        sentences.append(
            "Credit card number detected — DPDPA + EU AI Act violation risk; "
            "financial data must not appear in agent logs."
        )
    if not sentences:
        contact = {"email", "phone"} & found_types
        if contact:
            sentences.append(
                "Personal contact information detected in agent events — "
                "DPDPA compliance warning; review data minimisation practices."
            )
        elif "ip_address" in found_types:
            sentences.append(
                "IP address detected in agent events — "
                "review data minimisation and logging practices."
            )

    summary = " ".join(sentences[:2])

    return {
        "compliance_status": status,
        "regulations_flagged": regs,
        "summary": summary,
    }


# ---------------------------------------------------------------------------
# Public top-level entry point called by Sentinel
# ---------------------------------------------------------------------------

def check_compliance(event_texts: list[str], alert: dict) -> dict:
    """
    Scan event texts for PII, assess compliance, return enrichment fields.
    NEVER raises — returns null-field dict on any error so Sentinel is unaffected.
    """
    fallback = {
        "veritas_status": None,
        "veritas_regulations": None,
        "veritas_pii_summary": None,
        "veritas_pii_types": None,
    }

    try:
        # Aggregate findings across all event texts
        merged: dict[str, dict] = {}
        for text in event_texts:
            for finding in scan_for_pii(text):
                t = finding["type"]
                if t in merged:
                    merged[t]["count"] += finding["count"]
                else:
                    merged[t] = dict(finding)

        aggregated = list(merged.values())
        result = assess_compliance(aggregated, alert)

        return {
            "veritas_status": result["compliance_status"],
            "veritas_regulations": json.dumps(result["regulations_flagged"]),
            "veritas_pii_summary": result["summary"],
            "veritas_pii_types": json.dumps(aggregated) if aggregated else None,
        }
    except Exception:
        return fallback
