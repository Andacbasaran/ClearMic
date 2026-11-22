"""PortAudio device enumeration and VB-Cable virtual microphone detection."""

from __future__ import annotations

from dataclasses import dataclass
import sounddevice as sd


VB_CABLE_OUTPUT_HINTS = (
    "cable input",
    "vb-audio virtual cable",
    "vb-audio",
    "voicemeeter input",
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

    @property
    def display_name(self) -> str:
        tag = " [VB-Cable]" if self.is_virtual_cable else ""
        return f"{self.name}{tag} ({self.hostapi_name})"


def _hostapi_priority(hostapi_name: str) -> int:
    lower = hostapi_name.lower()
    if "wasapi" in lower:
        return 0
    if "wdm-ks" in lower:
        return 1
    if "directsound" in lower:
        return 2
    if "mme" in lower:
        return 3
    return 4


def _is_virtual_cable(name: str) -> bool:
    lower = name.lower()
    return any(hint in lower for hint in VB_CABLE_OUTPUT_HINTS)


def list_audio_devices() -> tuple[list[AudioDevice], list[AudioDevice]]:
    """Return (input_devices, output_devices), deduplicated by preferring WASAPI."""
    hostapis = sd.query_hostapis()
    raw_devices = sd.query_devices()

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

        prio = _hostapi_priority(hostapi_name)
        audio_dev = AudioDevice(
            index=idx,
            name=name,
            hostapi_name=hostapi_name,
            max_input_channels=int(dev["max_input_channels"]),
            max_output_channels=int(dev["max_output_channels"]),
            default_samplerate=float(dev["default_samplerate"]),
            is_virtual_cable=_is_virtual_cable(name),
        )

        if audio_dev.max_input_channels > 0:
            existing = inputs_by_name.get(name)
            if existing is None or prio < _hostapi_priority(existing.hostapi_name):
                inputs_by_name[name] = audio_dev

        if audio_dev.max_output_channels > 0:
            existing = outputs_by_name.get(name)
            if existing is None or prio < _hostapi_priority(existing.hostapi_name):
                outputs_by_name[name] = audio_dev

    inputs = sorted(
        inputs_by_name.values(),
        key=lambda d: (_hostapi_priority(d.hostapi_name), d.name.lower()),
    )
    outputs = sorted(
        outputs_by_name.values(),
        key=lambda d: (
            0 if d.is_virtual_cable else 1,
            _hostapi_priority(d.hostapi_name),
            d.name.lower(),
        ),
    )
    return inputs, outputs


def find_vb_cable_output(outputs: list[AudioDevice]) -> AudioDevice | None:
    """Return the preferred VB-Cable output device (where ClearMic sends clean audio)."""
    for dev in outputs:
        if "cable input" in dev.name.lower():
            return dev
    for dev in outputs:
        if dev.is_virtual_cable:
            return dev
    return None


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
    # Avoid picking VB-Cable Output as the microphone input by default
    for dev in inputs:
        if not dev.is_virtual_cable and "cable output" not in dev.name.lower():
            return dev
    return inputs[0]


def get_default_output_device(outputs: list[AudioDevice]) -> AudioDevice | None:
    if not outputs:
        return None
    vb = find_vb_cable_output(outputs)
    if vb is not None:
        return vb
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
