"""Cross-platform PortAudio device enumeration, Host API ranking, and virtual microphone routing."""

from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass

try:
    import sounddevice as sd
except Exception:  # pragma: no cover - headless environments without PulseAudio/PortAudio
    sd = None  # type: ignore[assignment]

VIRTUAL_MIC_HINTS_WINDOWS = (
    "cable input",
    "vb-audio virtual cable",
    "vb-audio",
    "vb-cable",
    "voicemeeter",
    "virtual",
    "clearmic",
)

VIRTUAL_MIC_HINTS_MACOS = (
    "blackhole",
    "loopback",
    "soundflower",
    "vb-cable",
    "vb-audio",
    "virtual",
    "clearmic",
)

VIRTUAL_MIC_HINTS_LINUX = (
    "clearmic virtual",
    "clearmic_virtual",
    "clearmic",
    "null",
    "monitor",
    "virtual",
    "pipewire",
    "pulseaudio",
)

# Backwards-compatible union constant
VB_CABLE_OUTPUT_HINTS = (
    "cable input",
    "vb-audio virtual cable",
    "vb-audio",
    "vb-cable",
    "voicemeeter",
    "blackhole",
    "loopback",
    "soundflower",
    "clearmic virtual",
    "clearmic_virtual",
    "null sink",
    "virtual",
)


@dataclass(frozen=True)
class AudioDevice:
    index: int
    name: str
    hostapi_name: str
    max_input_channels: int
    max_output_channels: int
    default_samplerate: float
    is_virtual_cable: bool = False
    hostapi_index: int = 0

    @property
    def display_name(self) -> str:
        if self.is_virtual_cable:
            lower = self.name.lower()
            if "blackhole" in lower:
                tag = " [BlackHole]"
            elif "cable" in lower or "vb-audio" in lower:
                tag = " [VB-Cable]"
            elif "voicemeeter" in lower:
                tag = " [Voicemeeter]"
            else:
                tag = " [Virtual Mic]"
        else:
            tag = ""
        return f"{self.name}{tag} ({self.hostapi_name})"


@dataclass(frozen=True)
class VirtualMicSetupInfo:
    platform_name: str
    driver_name: str
    url: str
    install_command: str
    can_create_automatically: bool
    summary_en: str
    summary_tr: str


def hostapi_priority(hostapi_name: str, platform_name: str | None = None) -> int:
    """Rank PortAudio Host APIs from lowest latency / best stability to fallback per OS."""
    plat = (platform_name or sys.platform).lower()
    lower = hostapi_name.lower()

    if plat == "win32":
        if "wasapi" in lower:
            return 0
        if "wdm-ks" in lower:
            return 1
        if "directsound" in lower:
            return 2
        if "mme" in lower:
            return 3
        return 4

    if plat == "darwin":
        if "core audio" in lower:
            return 0
        return 1

    # Linux / BSD
    if "pipewire" in lower:
        return 0
    if "pulse" in lower:
        return 1
    if "jack" in lower:
        return 2
    if "alsa" in lower:
        return 3
    return 4


def _hostapi_priority(hostapi_name: str) -> int:
    return hostapi_priority(hostapi_name)


def is_virtual_mic_name(name: str, platform_name: str | None = None) -> bool:
    """Detect virtual audio cable / virtual microphone devices across Windows, macOS, and Linux."""
    plat = (platform_name or sys.platform).lower()
    lower = name.lower()

    if plat == "win32":
        return any(hint in lower for hint in VIRTUAL_MIC_HINTS_WINDOWS)
    if plat == "darwin":
        return any(hint in lower for hint in VIRTUAL_MIC_HINTS_MACOS)
    if plat.startswith("linux"):
        # Avoid falsely tagging generic "pipewire" or "pulse" system default cards unless
        # paired with a virtual/null/monitor/clearmic cue, while still recognizing explicit virtual devices.
        explicit = (
            "clearmic",
            "virtual",
            "null",
            "monitor",
            "loopback",
            "remap",
            "cable input",
            "vb-audio",
        )
        return any(hint in lower for hint in explicit)
    return any(hint in lower for hint in VB_CABLE_OUTPUT_HINTS)


def _is_virtual_cable(name: str) -> bool:
    return is_virtual_mic_name(name)


def list_audio_devices(
    platform_name: str | None = None,
) -> tuple[list[AudioDevice], list[AudioDevice]]:
    """Return (input_devices, output_devices), deduplicated by preferring the highest-ranked Host API."""
    plat = (platform_name or sys.platform).lower()
    try:
        hostapis = sd.query_hostapis()
        raw_devices = sd.query_devices()
    except Exception:
        return [], []

    inputs_by_name: dict[str, AudioDevice] = {}
    outputs_by_name: dict[str, AudioDevice] = {}

    for idx, dev in enumerate(raw_devices):
        hostapi_idx = int(dev["hostapi"])
        hostapi_name = (
            str(hostapis[hostapi_idx]["name"])
            if 0 <= hostapi_idx < len(hostapis)
            else "Unknown"
        )
        name = str(dev["name"]).strip()
        if not name:
            continue

        prio = hostapi_priority(hostapi_name, plat)
        audio_dev = AudioDevice(
            index=idx,
            name=name,
            hostapi_name=hostapi_name,
            max_input_channels=int(dev["max_input_channels"]),
            max_output_channels=int(dev["max_output_channels"]),
            default_samplerate=float(dev["default_samplerate"]),
            is_virtual_cable=is_virtual_mic_name(name, plat),
            hostapi_index=hostapi_idx,
        )

        if audio_dev.max_input_channels > 0:
            existing = inputs_by_name.get(name)
            if existing is None or prio < hostapi_priority(existing.hostapi_name, plat):
                inputs_by_name[name] = audio_dev

        if audio_dev.max_output_channels > 0:
            existing = outputs_by_name.get(name)
            if existing is None or prio < hostapi_priority(existing.hostapi_name, plat):
                outputs_by_name[name] = audio_dev

    inputs = sorted(
        inputs_by_name.values(),
        key=lambda d: (hostapi_priority(d.hostapi_name, plat), d.name.lower()),
    )
    outputs = sorted(
        outputs_by_name.values(),
        key=lambda d: (
            0 if d.is_virtual_cable else 1,
            hostapi_priority(d.hostapi_name, plat),
            d.name.lower(),
        ),
    )
    return inputs, outputs


def find_virtual_mic_output(outputs: list[AudioDevice]) -> AudioDevice | None:
    """Return the preferred virtual cable / virtual mic output sink across Windows, macOS, and Linux."""
    preferred_tokens = ("clearmic", "cable input", "blackhole", "voicemeeter input", "loopback")
    for token in preferred_tokens:
        for dev in outputs:
            if token in dev.name.lower():
                return dev
    for dev in outputs:
        if dev.is_virtual_cable:
            return dev
    return None


def find_vb_cable_output(outputs: list[AudioDevice]) -> AudioDevice | None:
    """Backwards-compatible alias for find_virtual_mic_output()."""
    return find_virtual_mic_output(outputs)


def get_default_input_device(inputs: list[AudioDevice]) -> AudioDevice | None:
    if not inputs:
        return None
    try:
        default_idx = sd.default.device[0]
        if default_idx is not None and default_idx >= 0:
            default_name = str(sd.query_devices(default_idx)["name"]).strip()
            for dev in inputs:
                if dev.name == default_name:
                    return dev
    except Exception:
        pass
    # Avoid picking a virtual loopback cable as the physical microphone input by default
    for dev in inputs:
        if not dev.is_virtual_cable and "cable output" not in dev.name.lower():
            return dev
    return inputs[0]


def get_default_output_device(outputs: list[AudioDevice]) -> AudioDevice | None:
    if not outputs:
        return None
    virt = find_virtual_mic_output(outputs)
    if virt is not None:
        return virt
    try:
        default_idx = sd.default.device[1]
        if default_idx is not None and default_idx >= 0:
            default_name = str(sd.query_devices(default_idx)["name"]).strip()
            for dev in outputs:
                if dev.name == default_name:
                    return dev
    except Exception:
        pass
    return outputs[0]


def _pactl_list_has_name(stdout: str, target_name: str) -> bool:
    for line in stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] == target_name:
            return True
        if target_name in parts:
            return True
    return False


def create_linux_virtual_mic(
    sink_name: str = "ClearMic_Virtual_Sink",
    source_name: str = "ClearMic_Virtual_Mic",
) -> tuple[bool, str]:
    """Create a PipeWire/PulseAudio virtual microphone pair using `pactl`.

    Verifies both sink and remapped source exist before reporting already active.
    Returns `(success, message)`.
    """
    pactl = shutil.which("pactl")
    if not pactl:
        return (
            False,
            "pactl was not found. Install pulseaudio-utils or pipewire-pulse to create a virtual mic.",
        )

    try:
        existing_sinks = subprocess.run(
            [pactl, "list", "short", "sinks"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        sink_exists = existing_sinks.returncode == 0 and _pactl_list_has_name(
            existing_sinks.stdout, sink_name
        )

        source_exists = False
        if sink_exists:
            existing_sources = subprocess.run(
                [pactl, "list", "short", "sources"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            source_exists = existing_sources.returncode == 0 and _pactl_list_has_name(
                existing_sources.stdout, source_name
            )

        if sink_exists and source_exists:
            return (True, f"Virtual mic '{source_name}' is already active.")

        if not sink_exists:
            sink_res = subprocess.run(
                [
                    pactl,
                    "load-module",
                    "module-null-sink",
                    f"sink_name={sink_name}",
                    'sink_properties=device.description="ClearMic_Virtual_Output"',
                ],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            if sink_res.returncode != 0:
                return (False, f"Failed to create null sink: {sink_res.stderr.strip()}")

        if not source_exists:
            src_res = subprocess.run(
                [
                    pactl,
                    "load-module",
                    "module-remap-source",
                    f"master={sink_name}.monitor",
                    f"source_name={source_name}",
                    'source_properties=device.description="ClearMic_Virtual_Mic"',
                ],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            if src_res.returncode != 0:
                return (
                    True,
                    f"Created null sink '{sink_name}' (select its Monitor as mic in Discord/OBS).",
                )
        return (True, f"Created PipeWire/PulseAudio virtual mic '{source_name}'.")
    except Exception as exc:
        return (False, f"pactl error: {exc}")


def get_virtual_mic_setup_info(platform_name: str | None = None) -> VirtualMicSetupInfo:
    """Return OS-aware virtual microphone driver instructions and download links."""
    plat = (platform_name or sys.platform).lower()
    if plat == "win32":
        return VirtualMicSetupInfo(
            platform_name="Windows",
            driver_name="VB-Audio Virtual Cable",
            url="https://vb-audio.com/Cable/",
            install_command="winget install VB-Audio.VB-Cable",
            can_create_automatically=False,
            summary_en=(
                "1. Install VB-Audio Virtual Cable and restart audio apps.\n"
                "2. Set ClearMic Output to 'CABLE Input (VB-Audio Virtual Cable)'.\n"
                "3. Select 'CABLE Output' as your microphone in Discord, Zoom, OBS, or Teams."
            ),
            summary_tr=(
                "1. VB-Audio Virtual Cable sürücüsünü kurun ve ses uygulamalarını yenileyin.\n"
                "2. ClearMic Çıkış cihazını 'CABLE Input (VB-Audio Virtual Cable)' seçin.\n"
                "3. Discord, Zoom, OBS veya Teams mikrofonunu 'CABLE Output' yapın."
            ),
        )
    if plat == "darwin":
        return VirtualMicSetupInfo(
            platform_name="macOS",
            driver_name="BlackHole 2ch",
            url="https://existential.audio/blackhole/",
            install_command="brew install blackhole-2ch",
            can_create_automatically=False,
            summary_en=(
                "1. Install BlackHole 2ch via Homebrew (`brew install blackhole-2ch`) or website.\n"
                "2. Set ClearMic Output to 'BlackHole 2ch'.\n"
                "3. Select 'BlackHole 2ch' as your microphone input in Discord, Zoom, Meet, or OBS."
            ),
            summary_tr=(
                "1. Homebrew (`brew install blackhole-2ch`) veya web sitesi ile BlackHole 2ch kurun.\n"
                "2. ClearMic Çıkış cihazını 'BlackHole 2ch' olarak seçin.\n"
                "3. Discord, Zoom, Meet veya OBS mikrofon girişini 'BlackHole 2ch' yapın."
            ),
        )
    return VirtualMicSetupInfo(
        platform_name="Linux",
        driver_name="PipeWire / PulseAudio Virtual Mic",
        url="https://gitlab.freedesktop.org/pipewire/pipewire/-/wikis/Virtual-Devices",
        install_command=(
            "pactl load-module module-null-sink sink_name=ClearMic_Virtual_Sink "
            'sink_properties=device.description="ClearMic_Virtual_Output"'
        ),
        can_create_automatically=True,
        summary_en=(
            "1. Click 'Create Virtual Mic' (uses PipeWire/PulseAudio `pactl`) — zero extra drivers needed.\n"
            "2. Set ClearMic Output to 'ClearMic_Virtual_Output'.\n"
            "3. Select 'ClearMic_Virtual_Mic' as your microphone in Discord, OBS, or Zoom."
        ),
        summary_tr=(
            "1. 'Sanal Mikrofon Oluştur'a tıklayın (PipeWire/PulseAudio `pactl`) — ek sürücü gerekmez.\n"
            "2. ClearMic Çıkış cihazını 'ClearMic_Virtual_Output' olarak seçin.\n"
            "3. Discord, OBS veya Zoom mikrofon girişini 'ClearMic_Virtual_Mic' yapın."
        ),
    )
