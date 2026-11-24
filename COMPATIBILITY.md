# Platform, Virtual Mic & App Compatibility Matrix

**ClearMic v1.0.0** routes ultra-low-latency, AI-cleaned voice audio into any desktop communication, streaming, gaming, or recording application through OS-native virtual microphones.

> 💡 **Tested a microphone, audio interface, or communication app not listed here?** Open a **Compatibility Report** issue or submit a Pull Request updating the tables below!

## Operating Systems & Host APIs

| Operating System | Architecture | Preferred Host API Ranking | Virtual Microphone Driver | Autostart Integration | Status |
| :--- | :---: | :--- | :--- | :--- | :---: |
| **Windows 10 (2004+) & Windows 11** | `x64` | `WASAPI` → `WDM-KS` → `DirectSound` → `MME` | **VB-Audio Virtual Cable** / Voicemeeter | Registry (`HKCU\...\Run`) | ✅ Full Support |
| **macOS 12 Monterey – macOS 15+** | `Apple Silicon (arm64)` | `Core Audio` | **BlackHole 2ch** / Loopback | LaunchAgent (`~/Library/LaunchAgents`) | ✅ Full Support |
| **Linux (Ubuntu, Fedora, Arch, SteamOS)** | `x86_64` | `PipeWire` → `PulseAudio` → `JACK` → `ALSA` | **Built-in PipeWire / PulseAudio** (1-click `pactl`) | XDG Autostart (`~/.config/autostart`) | ✅ Full Support |

## Communication, Streaming & Recording Applications

| Application | Recommended Preset | Virtual Mic Input Setting | Notes | Status |
| :--- | :--- | :--- | :--- | :---: |
| **Discord** | `Gaming & Discord` or `Keyboard Killer` | `CABLE Output` (Win) / `BlackHole 2ch` (macOS) / `ClearMic_Virtual_Mic` (Linux) | Disable Discord's built-in Krisp & Echo Cancellation to avoid double processing. | ✅ Verified |
| **OBS Studio / Streamlabs** | `Broadcast Radio` | Same virtual mic input | Pair with ClearMic's 3-Band EQ, De-Esser & Studio Compressor for radio-ready streams with **0 MB VRAM**. | ✅ Verified |
| **Zoom** | `Meeting & Calls` | Same virtual mic input | Enable *"Original sound for musicians"* or set Zoom background suppression to *Low* for maximum clarity. | ✅ Verified |
| **Microsoft Teams** | `Meeting & Calls` | Same virtual mic input | Set Teams Noise Suppression to *Off* so ClearMic handles the entire vocal chain locally. | ✅ Verified |
| **Google Meet (Chrome / Edge / Firefox)** | `Meeting & Calls` | Same virtual mic input | Disable browser noise cancellation in Meet Audio settings for natural studio air. | ✅ Verified |
| **Audacity / Reaper / GarageBand / Logic** | `Studio Natural` or `Broadcast Radio` | Virtual mic input or **Offline `.wav` Cleaner** | Use ClearMic's built-in **Batch `.wav` Cleaner** to denoise existing raw recordings offline. | ✅ Verified |
| **In-Game Voice Chat (Valorant, CS2, Apex, CoD)** | `Gaming & Discord` or `Keyboard Killer` | Set virtual mic as OS default input | Uses **0 MB GPU VRAM** and `< 1 ms` CPU per 16 ms block — zero FPS impact. | ✅ Verified |

## Sample Rates & Audio Interfaces

| Hardware Category | Supported Sample Rates | Channel Negotiation | Notes |
| :--- | :---: | :---: | :--- |
| **USB Condenser & Dynamic Mics** *(HyperX, Blue Yeti, Elgato Wave, Shure MV7, Fifine)* | `48 kHz`, `44.1 kHz`, `32 kHz`, `16 kHz` | Mono In → Stereo Dual-Mono Out (`2ch`) | Auto-negotiates sample rate with stateful Butterworth anti-aliased resampling. |
| **XLR Audio Interfaces** *(Focusrite Scarlett, Audient, GoXLR, Motu)* | `48 kHz`, `44.1 kHz` | Mono In → Stereo Out | Cross-HostAPI dual-stream bridge automatically handles mismatched Host APIs. |
| **Bluetooth / Gaming Headsets** *(AirPods, Sony WH, SteelSeries, Logitech)* | `16 kHz` (HFP) / `48 kHz` (USB dongle) | Adaptive (`16 kHz` native GTCRN bypass) | Automatically disables >7.2 kHz split-band air on 16 kHz HFP links to prevent aliasing. |
| **Laptop Built-In Microphones** *(MacBook, ThinkPad, Gaming Laptops)* | `48 kHz`, `44.1 kHz` | Mono In → Stereo Out | Run **3s Auto-Calibrate** to auto-tune HPF & Noise Gate for loud GPU/CPU laptop fans. |
