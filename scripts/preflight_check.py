#!/usr/bin/env python3
"""Preflight capability probe for a Gemini 3.8 Live migration.

Answers three separate questions before any migration work begins:

  1. Which surface does the CODEBASE target?   (Vertex / Agent Platform vs AI Studio)
  2. Which surface is CREDENTIALED here?       (ADC / service account vs API key)
  3. Is the TARGET MODEL reachable?            (listed, and optionally session-verified)

Emits a capability tier that tells the migration workflow what it may claim:

  LIVE_VERIFIED  - a Live session reached setupComplete. Live smoke tests are valid.
  MODEL_VISIBLE  - auth works and the model is listed. No session was opened.
  AUTH_ONLY      - auth works but the model is not visible here. Availability gap.
  NO_AUTH        - no usable credentials. Static analysis only.

Cost and safety:
  * All default operations are read-only metadata GETs. They do not bill.
  * The Live WebSocket probe opens a real session and is OPT-IN via --probe-live.
  * Secrets are never printed. Keys and tokens are redacted.
  * Every network and subprocess call is bounded by a timeout.
  * Nothing is written, deployed, or modified in the target project.

Stdlib only. The optional Live probe needs `websockets`; it degrades if absent.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

# --- Constants ---------------------------------------------------------------

TARGET_MODELS = [
    "gemini-3.8-live",
    "gemini-3.8-live-extended-thinking",
]
LEGACY_MODELS = [
    "gemini-3.1-flash-live-preview",
    "gemini-2.5-flash-native-audio-preview-12-2025",
    "gemini-live-2.5-flash-preview",
    "gemini-2.0-flash-live-001",
]

# Used only if the live location list cannot be fetched.
FALLBACK_REGIONS = [
    "global",
    "us-central1",
    "us-east4",
    "europe-west4",
    "asia-northeast1",
]

AISTUDIO_HOST = "generativelanguage.googleapis.com"
VERTEX_HOST_TMPL = "{location}-aiplatform.googleapis.com"
VERTEX_GLOBAL_HOST = "aiplatform.googleapis.com"

HTTP_TIMEOUT = 15
GCLOUD_TIMEOUT = 20
METADATA_TIMEOUT = 2

Tier = Literal["LIVE_VERIFIED", "MODEL_VISIBLE", "AUTH_ONLY", "NO_AUTH"]


# --- Result containers -------------------------------------------------------


@dataclass
class CredentialState:
    api_key_present: bool = False
    api_key_source: str | None = None
    api_key_hint: str | None = None  # redacted
    api_key_valid: bool | None = None
    adc_present: bool = False
    adc_source: str | None = None
    project: str | None = None
    project_source: str | None = None
    location: str | None = None
    location_source: str | None = None
    notes: list[str] = field(default_factory=list)


@dataclass
class ModelProbe:
    model: str
    surface: str
    visible: bool
    detail: str
    checked_location: str | None = None
    available_in: list[str] = field(default_factory=list)
    swept_count: int = 0


@dataclass
class LiveProbe:
    attempted: bool = False
    succeeded: bool = False
    model: str | None = None
    detail: str = "not attempted (use --probe-live to enable; opens a billable session)"


@dataclass
class PreflightReport:
    tier: Tier = "NO_AUTH"
    codebase_surface: str = "unknown"
    codebase_evidence: list[str] = field(default_factory=list)
    credentialed_surface: str = "none"
    surface_mismatch: bool = False
    credentials: CredentialState = field(default_factory=CredentialState)
    model_probes: list[ModelProbe] = field(default_factory=list)
    legacy_probes: list[ModelProbe] = field(default_factory=list)
    live_probe: LiveProbe = field(default_factory=LiveProbe)
    blockers: list[str] = field(default_factory=list)
    testing_allowed: list[str] = field(default_factory=list)
    testing_blocked: list[str] = field(default_factory=list)


# --- Helpers -----------------------------------------------------------------


def _redact(secret: str) -> str:
    if len(secret) <= 8:
        return "****"
    return f"****{secret[-4:]} (len={len(secret)})"


def _run(cmd: list[str], timeout: int) -> tuple[bool, str]:
    try:
        out = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, check=False
        )
        if out.returncode != 0:
            return False, (out.stderr or out.stdout).strip()
        return True, out.stdout.strip()
    except FileNotFoundError:
        return False, f"{cmd[0]} not installed"
    except subprocess.TimeoutExpired:
        return False, f"{cmd[0]} timed out after {timeout}s"
    except Exception as e:  # noqa: BLE001 - surface any launcher failure verbatim
        return False, str(e)


def _http_get(url: str, headers: dict[str, str]) -> tuple[int, str]:
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as e:
        return 0, f"network error: {e.reason}"
    except Exception as e:  # noqa: BLE001
        return 0, f"error: {e}"


# --- 1. Codebase surface detection -------------------------------------------


def detect_codebase_surface(root: Path) -> tuple[str, list[str]]:
    """Infer which API surface the source tree targets."""
    evidence: list[str] = []
    vertex_hits = 0
    aistudio_hits = 0

    signals = {
        "vertex": [
            (
                re.compile(r"aiplatform\.googleapis\.com"),
                "aiplatform.googleapis.com endpoint",
            ),
            (
                re.compile(r"GOOGLE_GENAI_USE_VERTEXAI"),
                "GOOGLE_GENAI_USE_VERTEXAI env var",
            ),
            (
                re.compile(r"vertexai\s*=\s*True", re.IGNORECASE),
                "genai.Client(vertexai=True)",
            ),
            (re.compile(r"publishers/google/models"), "publisher model path"),
            (re.compile(r"LlmBidiService"), "Vertex LlmBidiService WSS path"),
        ],
        "aistudio": [
            (
                re.compile(r"generativelanguage\.googleapis\.com"),
                "generativelanguage endpoint",
            ),
            (re.compile(r"GEMINI_API_KEY|GOOGLE_API_KEY"), "API key env var"),
            (
                re.compile(r"GenerativeService\.BidiGenerateContent"),
                "AI Studio WSS path",
            ),
        ],
    }

    exts = {
        ".py",
        ".ts",
        ".js",
        ".tsx",
        ".jsx",
        ".json",
        ".yaml",
        ".yml",
        ".env",
        ".tf",
        ".sh",
    }
    skip_dirs = {
        "node_modules",
        "venv",
        ".venv",
        "dist",
        "build",
        "__pycache__",
        ".git",
    }

    files: list[Path] = []
    if root.is_file():
        files = [root]
    else:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [
                d for d in dirnames if d not in skip_dirs and not d.startswith(".")
            ]
            for fn in filenames:
                p = Path(dirpath) / fn
                if p.suffix.lower() in exts or p.name.startswith(".env"):
                    files.append(p)

    for p in files[:4000]:  # bound the walk on very large repos
        try:
            content = p.read_text(encoding="utf-8", errors="ignore")
        except (OSError, UnicodeDecodeError):
            continue
        for surface, pats in signals.items():
            for pat, label in pats:
                if pat.search(content):
                    evidence.append(f"{surface}: {label} ({p})")
                    if surface == "vertex":
                        vertex_hits += 1
                    else:
                        aistudio_hits += 1
                    break

    if vertex_hits and not aistudio_hits:
        return "vertex", evidence
    if aistudio_hits and not vertex_hits:
        return "aistudio", evidence
    if vertex_hits and aistudio_hits:
        return "both", evidence
    return "unknown", evidence


# --- 2. Credential discovery -------------------------------------------------


def discover_credentials() -> CredentialState:
    cs = CredentialState()

    # API key (AI Studio surface)
    for var in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        val = os.environ.get(var)
        if val:
            cs.api_key_present = True
            cs.api_key_source = f"env:{var}"
            cs.api_key_hint = _redact(val)
            break

    # ADC (Vertex surface)
    gac = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if gac and Path(gac).is_file():
        cs.adc_present = True
        cs.adc_source = f"env:GOOGLE_APPLICATION_CREDENTIALS ({gac})"
    else:
        adc_path = (
            Path.home() / ".config" / "gcloud" / "application_default_credentials.json"
        )
        if adc_path.is_file():
            cs.adc_present = True
            cs.adc_source = f"file:{adc_path}"

    if not cs.adc_present:
        # GCE/Cloud Run metadata server. Short timeout: absence is the common case.
        try:
            req = urllib.request.Request(
                "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token",
                headers={"Metadata-Flavor": "Google"},
            )
            with urllib.request.urlopen(req, timeout=METADATA_TIMEOUT) as resp:
                if resp.status == 200:
                    cs.adc_present = True
                    cs.adc_source = "gce-metadata-server"
        except (urllib.error.URLError, TimeoutError, OSError):
            pass

    # Project
    for var in ("GOOGLE_CLOUD_PROJECT", "GCLOUD_PROJECT", "GCP_PROJECT"):
        if os.environ.get(var):
            cs.project = os.environ[var]
            cs.project_source = f"env:{var}"
            break
    if not cs.project:
        ok, out = _run(["gcloud", "config", "get-value", "project"], GCLOUD_TIMEOUT)
        if ok and out and out != "(unset)":
            cs.project = out
            cs.project_source = "gcloud config"
        else:
            cs.notes.append(f"project lookup via gcloud failed: {out or 'unset'}")

    # Location
    for var in ("GOOGLE_CLOUD_LOCATION", "GOOGLE_CLOUD_REGION", "VERTEX_LOCATION"):
        if os.environ.get(var):
            cs.location = os.environ[var]
            cs.location_source = f"env:{var}"
            break
    if not cs.location:
        cs.location = "us-central1"
        cs.location_source = "default assumption"

    return cs


def get_access_token() -> tuple[str | None, str]:
    ok, out = _run(
        ["gcloud", "auth", "application-default", "print-access-token"], GCLOUD_TIMEOUT
    )
    if ok and out:
        return out, "gcloud ADC"
    ok2, out2 = _run(["gcloud", "auth", "print-access-token"], GCLOUD_TIMEOUT)
    if ok2 and out2:
        return out2, "gcloud user credentials"
    return None, out or out2 or "no token obtainable"


# --- 3. Model availability ---------------------------------------------------


def probe_aistudio_model(api_key: str, model: str) -> ModelProbe:
    url = f"https://{AISTUDIO_HOST}/v1beta/models/{model}?key={api_key}"
    status, body = _http_get(url, {})
    if status == 200:
        return ModelProbe(model, "aistudio", True, "listed via v1beta/models")
    if status == 404:
        return ModelProbe(model, "aistudio", False, "404 not found for this API key")
    if status in (401, 403):
        return ModelProbe(model, "aistudio", False, f"{status} auth/permission denied")
    if status == 429:
        return ModelProbe(model, "aistudio", False, "429 rate limited - inconclusive")
    snippet = " ".join(body.split())[:110]
    return ModelProbe(model, "aistudio", False, f"status {status}: {snippet}")


def list_vertex_locations(token: str, project: str) -> tuple[list[str], str]:
    """Ask Vertex which locations this project actually supports.

    Beats a hardcoded region list, which goes stale every time a region launches.
    """
    url = f"https://{VERTEX_GLOBAL_HOST}/v1beta1/projects/{project}/locations"
    status, body = _http_get(url, {"Authorization": f"Bearer {token}"})
    if status == 200:
        try:
            data = json.loads(body)
            locs = [
                loc["locationId"]
                for loc in data.get("locations", [])
                if loc.get("locationId")
            ]
            if locs:
                if "global" not in locs:
                    locs.insert(0, "global")
                return sorted(
                    set(locs)
                ), f"discovered {len(locs)} locations from Vertex"
        except json.JSONDecodeError:
            pass
    return (
        FALLBACK_REGIONS,
        f"location discovery failed (status {status}); using fallback list",
    )


def validate_api_key(api_key: str) -> tuple[bool, str]:
    """One cheap call to prove the key is accepted, before probing each model."""
    status, _body = _http_get(
        f"https://{AISTUDIO_HOST}/v1beta/models?pageSize=1&key={api_key}", {}
    )
    if status == 200:
        return True, "accepted"
    if status in (400, 401, 403):
        return (
            False,
            f"rejected ({status}): key present but not valid for this endpoint",
        )
    return False, f"inconclusive (status {status})"


def probe_vertex_model(
    token: str,
    project: str,
    location: str,
    model: str,
    sweep_locations: list[str] | None,
) -> ModelProbe:
    def _check(loc: str) -> tuple[bool, str]:
        host = (
            VERTEX_GLOBAL_HOST
            if loc == "global"
            else VERTEX_HOST_TMPL.format(location=loc)
        )
        url = f"https://{host}/v1beta1/publishers/google/models/{model}"
        status, body = _http_get(
            url,
            {
                "Authorization": f"Bearer {token}",
                "x-goog-user-project": project,
            },
        )
        if status == 200:
            return True, "publisher model reachable"
        if status == 404:
            return False, "404 not published in this location"
        if status == 403:
            return False, "403 permission denied or not entitled"
        if status == 401:
            return False, "401 credentials rejected"
        return False, f"status {status}: " + " ".join(body.split())[:110]

    visible, detail = _check(location)
    probe = ModelProbe(model, "vertex", visible, detail, checked_location=location)
    if visible:
        probe.available_in = [location]

    if sweep_locations:
        swept = [l for l in sweep_locations if l != location]
        if swept:
            with ThreadPoolExecutor(max_workers=8) as pool:
                results = list(pool.map(lambda l: (l, _check(l)[0]), swept))
            probe.available_in.extend(l for l, ok in results if ok)
            probe.swept_count = len(swept)
    return probe


# --- 4. Optional Live session probe ------------------------------------------


def probe_live_session(
    surface: str,
    model: str,
    api_key: str | None,
    token: str | None,
    project: str | None,
    location: str | None,
) -> LiveProbe:
    """Open a real Live session and wait for setupComplete, then close.

    OPT-IN ONLY. This opens a billable session on the target project.
    """
    lp = LiveProbe(attempted=True, model=model)
    try:
        import asyncio

        import websockets  # type: ignore[import-not-found]
    except ImportError:
        lp.detail = "skipped: `websockets` package not installed"
        return lp

    if surface == "vertex":
        host = (
            VERTEX_GLOBAL_HOST
            if location == "global"
            else VERTEX_HOST_TMPL.format(location=location)
        )
        url = f"wss://{host}/ws/google.cloud.aiplatform.v1beta1.LlmBidiService/BidiGenerateContent"
        headers = {"Authorization": f"Bearer {token}"}
        model_field = (
            f"projects/{project}/locations/{location}/publishers/google/models/{model}"
        )
    else:
        url = (
            f"wss://{AISTUDIO_HOST}/ws/"
            f"google.ai.generativelanguage.v1alpha.GenerativeService.BidiGenerateContent"
            f"?key={api_key}"
        )
        headers = {}
        model_field = f"models/{model}"

    setup: dict[str, Any] = {
        "setup": {
            "model": model_field,
            "generationConfig": {"responseModalities": ["AUDIO"]},
        }
    }

    async def _go() -> tuple[bool, str]:
        try:
            async with websockets.connect(
                url, additional_headers=headers, open_timeout=20, close_timeout=5
            ) as ws:
                await ws.send(json.dumps(setup))
                raw = await asyncio.wait_for(ws.recv(), timeout=20)
                text = raw.decode() if isinstance(raw, bytes) else raw
                if "setupComplete" in text:
                    return True, "setupComplete received; session closed immediately"
                return False, f"unexpected first frame: {text[:200]}"
        except Exception as e:  # noqa: BLE001 - report the handshake failure verbatim
            return False, f"{type(e).__name__}: {e}"

    ok, detail = asyncio.run(_go())
    lp.succeeded = ok
    lp.detail = detail
    return lp


# --- Orchestration -----------------------------------------------------------


def run_preflight(
    root: Path, sweep: bool, do_live: bool, live_model: str
) -> PreflightReport:
    rep = PreflightReport()

    rep.codebase_surface, rep.codebase_evidence = detect_codebase_surface(root)
    rep.credentials = cs = discover_credentials()

    token: str | None = None
    if cs.adc_present or cs.project:
        token, token_note = get_access_token()
        if not token:
            cs.notes.append(f"access token unavailable: {token_note}")

    # Held locally only. Never stored on the report, which is serialised to JSON.
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")

    if api_key:
        cs.api_key_valid, key_detail = validate_api_key(api_key)
        if not cs.api_key_valid:
            cs.notes.append(f"API key {key_detail}")

    has_vertex = bool(token and cs.project)
    has_aistudio = bool(api_key) and cs.api_key_valid is True

    if has_vertex and has_aistudio:
        rep.credentialed_surface = "both"
    elif has_vertex:
        rep.credentialed_surface = "vertex"
    elif has_aistudio:
        rep.credentialed_surface = "aistudio"
    else:
        rep.credentialed_surface = "none"

    if (
        rep.codebase_surface in ("vertex", "aistudio")
        and rep.credentialed_surface not in ("both", "none")
        and rep.codebase_surface != rep.credentialed_surface
    ):
        rep.surface_mismatch = True
        rep.blockers.append(
            f"Surface mismatch: code targets {rep.codebase_surface}, "
            f"but only {rep.credentialed_surface} credentials are present."
        )

    # Discover every location this project supports, once, then sweep them all.
    sweep_locations: list[str] | None = None
    if has_vertex and sweep:
        sweep_locations, loc_note = list_vertex_locations(token, cs.project)  # type: ignore[arg-type]
        cs.notes.append(loc_note)

    # Probe models on whichever surfaces are credentialed.
    for model in TARGET_MODELS:
        if has_vertex:
            rep.model_probes.append(
                probe_vertex_model(
                    token, cs.project, cs.location, model, sweep_locations
                )  # type: ignore[arg-type]
            )
        if has_aistudio:
            rep.model_probes.append(probe_aistudio_model(api_key, model))  # type: ignore[arg-type]

    for model in LEGACY_MODELS[:1]:  # only the immediate predecessor matters
        if has_vertex:
            rep.legacy_probes.append(
                probe_vertex_model(token, cs.project, cs.location, model, None)  # type: ignore[arg-type]
            )
        if has_aistudio:
            rep.legacy_probes.append(probe_aistudio_model(api_key, model))  # type: ignore[arg-type]

    if cs.api_key_present and cs.api_key_valid is False:
        rep.blockers.append(
            "An API key is set in the environment but the Gemini API rejected it. "
            "Either remove the stale key or replace it before relying on the AI Studio surface."
        )

    any_visible = any(p.visible for p in rep.model_probes)

    # Optional live probe, only when a target model is actually visible.
    if do_live:
        if not any_visible:
            rep.live_probe.detail = "skipped: no target model visible to probe"
        else:
            surface = "vertex" if has_vertex else "aistudio"
            rep.live_probe = probe_live_session(
                surface,
                live_model,
                api_key,
                token,
                cs.project,
                cs.location,
            )

    # Tier assignment.
    if rep.live_probe.succeeded:
        rep.tier = "LIVE_VERIFIED"
    elif any_visible:
        rep.tier = "MODEL_VISIBLE"
    elif rep.credentialed_surface != "none":
        rep.tier = "AUTH_ONLY"
    else:
        rep.tier = "NO_AUTH"

    # What the migration report may and may not claim.
    if rep.tier == "LIVE_VERIFIED":
        rep.testing_allowed = [
            "static analysis",
            "config validation",
            "mock event-loop tests",
            "live smoke test",
            "measured latency comparison",
        ]
        rep.testing_blocked = ["human voice-quality review (needs a person)"]
    elif rep.tier == "MODEL_VISIBLE":
        rep.testing_allowed = [
            "static analysis",
            "config validation",
            "mock event-loop tests",
        ]
        rep.testing_blocked = [
            "live smoke test (re-run with --probe-live)",
            "latency measurement",
            "human voice-quality review",
        ]
    elif rep.tier == "AUTH_ONLY":
        rep.testing_allowed = [
            "static analysis",
            "config validation",
            "mock event-loop tests",
        ]
        rep.testing_blocked = [
            "live smoke test",
            "latency measurement",
            "human voice-quality review",
        ]
        rep.blockers.append(
            "Target model not visible to these credentials. Check region, project "
            "entitlement, and whether the model has reached GA on this surface."
        )
    else:
        rep.testing_allowed = [
            "static analysis",
            "config validation",
            "mock event-loop tests",
        ]
        rep.testing_blocked = [
            "live smoke test",
            "latency measurement",
            "human voice-quality review",
        ]
        rep.blockers.append(
            "No usable credentials found. The migration report MUST state that no "
            "runtime verification was performed."
        )

    return rep


# --- Rendering ---------------------------------------------------------------


def render(rep: PreflightReport) -> str:
    L: list[str] = []
    L.append("=" * 66)
    L.append("Gemini 3.8 Live - Migration Preflight")
    L.append("=" * 66)
    L.append(f"CAPABILITY TIER: {rep.tier}")
    L.append("")

    L.append("Surfaces")
    L.append(f"  codebase targets : {rep.codebase_surface}")
    L.append(f"  credentialed     : {rep.credentialed_surface}")
    if rep.surface_mismatch:
        L.append("  MISMATCH         : yes")
    L.append("")

    cs = rep.credentials
    L.append("Credentials")
    if cs.api_key_present:
        verdict = {True: "accepted", False: "REJECTED", None: "unchecked"}[
            cs.api_key_valid
        ]
        L.append(
            f"  API key : yes [{cs.api_key_source}] {cs.api_key_hint} -> {verdict}"
        )
    else:
        L.append("  API key : no")
    L.append(
        f"  ADC     : {'yes' if cs.adc_present else 'no'}"
        + (f" [{cs.adc_source}]" if cs.adc_present else "")
    )
    L.append(f"  project : {cs.project or '-'} [{cs.project_source or '-'}]")
    L.append(f"  location: {cs.location or '-'} [{cs.location_source or '-'}]")
    for n in cs.notes:
        L.append(f"  note    : {n}")
    L.append("")

    if rep.model_probes:
        L.append("Target model availability")
        for p in rep.model_probes:
            mark = "OK  " if p.visible else "MISS"
            loc = f" @{p.checked_location}" if p.checked_location else ""
            L.append(f"  [{mark}] {p.model} ({p.surface}{loc}) - {p.detail}")
            if p.swept_count:
                if p.available_in:
                    L.append(
                        f"         available in {len(p.available_in)}/{p.swept_count + 1} "
                        f"locations: {', '.join(sorted(p.available_in))}"
                    )
                else:
                    L.append(
                        f"         swept all {p.swept_count + 1} supported locations: "
                        f"available in none"
                    )
        L.append("")

    if rep.legacy_probes:
        L.append("Current model still reachable")
        for p in rep.legacy_probes:
            mark = "OK  " if p.visible else "MISS"
            L.append(f"  [{mark}] {p.model} ({p.surface}) - {p.detail}")
        L.append("")

    L.append("Live session probe")
    L.append(
        f"  attempted: {rep.live_probe.attempted}  succeeded: {rep.live_probe.succeeded}"
    )
    L.append(f"  detail   : {rep.live_probe.detail}")
    L.append("")

    L.append("Verification this migration MAY perform")
    for t in rep.testing_allowed:
        L.append(f"  + {t}")
    L.append("Verification this migration MAY NOT claim")
    for t in rep.testing_blocked:
        L.append(f"  - {t}")
    L.append("")

    if rep.blockers:
        L.append("Blockers and warnings")
        for b in rep.blockers:
            L.append(f"  ! {b}")
        L.append("")

    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Preflight capability probe for a Gemini 3.8 Live migration."
    )
    ap.add_argument(
        "path",
        type=Path,
        nargs="?",
        default=Path("."),
        help="codebase root to inspect for surface signals",
    )
    ap.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    ap.add_argument(
        "--no-sweep",
        action="store_true",
        help="skip the all-location availability sweep (sweep is on by default)",
    )
    ap.add_argument(
        "--probe-live",
        action="store_true",
        help="OPT-IN: open a real Live session to verify the handshake. This bills. "
        "Requires interactive confirmation, or --yes.",
    )
    ap.add_argument(
        "--yes",
        action="store_true",
        help="confirm --probe-live without an interactive prompt",
    )
    ap.add_argument(
        "--live-model",
        default="gemini-3.8-live",
        help="model to use for the live probe",
    )
    ap.add_argument(
        "--require-live",
        action="store_true",
        help="exit non-zero unless tier is LIVE_VERIFIED (for CI gates)",
    )
    args = ap.parse_args()

    if args.probe_live and not args.yes:
        prompt = (
            "\n--probe-live opens a REAL Live session on "
            f"model '{args.live_model}'. This is a billable request against the "
            "target project.\nContinue? [y/N] "
        )
        if not sys.stdin.isatty():
            print(
                "Refusing --probe-live in a non-interactive shell without --yes.",
                file=sys.stderr,
            )
            return 3
        if input(prompt).strip().lower() not in ("y", "yes"):
            print("Aborted. Re-run without --probe-live for a read-only preflight.")
            return 0

    rep = run_preflight(args.path, not args.no_sweep, args.probe_live, args.live_model)

    if args.json:
        print(json.dumps(asdict(rep), indent=2))
    else:
        print(render(rep))

    if args.require_live and rep.tier != "LIVE_VERIFIED":
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
