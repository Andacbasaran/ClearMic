# ClearMic

%100 offline, 0 MB VRAM, ultra düşük gecikmeli yapay zeka mikrofon gürültü engelleyici ve yayın ses stüdyosu — açık kaynaklı Krisp / NVIDIA Broadcast alternatifi.

## Özellikler (v0.2.0 Pro Studio)
- **CPU üzerinde ONNX ile gerçek zamanlı ses temizleme:** Streaming `GTCRN` ONNX modeli (~520 KB, 16 ms blok başına ~1.1 ms CPU işlem süresi, **0 MB VRAM**) + anında çalışan `Spectral DSP` yedek motoru
- **Pro Yayın Ses Zinciri (Broadcast DSP):**
  - 85 Hz Yüksek Geçiren Filtre (HPF) — masa ve fan dip uğultusu kesici
  - Attack / Hold / Release destekli akıllı **Gürültü Kapısı (Noise Gate)**
  - **De-Esser** — 5.2–9.5 kHz sert "S/Ş" ıslıklarını yumuşatma
  - **3-Bant Yayın Ekolayzeri (Voice EQ)** — Bas/Sıcaklık (120 Hz), Vokal Netlik (2.8 kHz), Parlaklık/Hava (8 kHz)
  - **Yayın Kompresörü** (soft-knee) + konuşma odaklı **Otomatik Kazanç Kontrolü (AGC)** + Soft Limiter
- **Hazır Profiller:** Tek tıkla `Oyun & Discord`, `Podcast & Yayın`, `Toplantı (Zoom / Teams)` ve `Doğal / Hafif` profilleri
- **Canlı Ses Monitörü & 32-Bant FFT Spektrum Analizörü:** Ham vs temizlenmiş ses spektrumunu ve dalga formunu canlı karşılaştırma, anlık AI gürültü azaltma (dB) göstergesi ve tek tıkla **A/B Bypass (`B`)** / **Sustur (`M`)**
- **Dahili 6 sn A/B Mikrofon Test Stüdyosu:** VB-Cable olmadan bile hem ham hem temiz sesi eşzamanlı kaydedip anında kulaklıktan dinleyerek karşılaştırma
- **Sanal Mikrofon Köprüsü (VB-Cable) & Sistem Entegrasyonu:** VB-Cable otomatik algılama, Sistem Tepsisi (yeşil/sarı/kırmızı durum simgeleri), Windows başlangıcında tepside otomatik açılma (`--minimized`) ve PyInstaller `.exe` paketleme betiği

## Kurulum ve Çalıştırma

```powershell
python -m venv .venv
.\.venv\Scripts\pip.exe install -r requirements.txt
.\.venv\Scripts\python.exe run.py
```

### Tek Dosya / Taşınabilir Windows Derlemesi (`.exe`)
```powershell
.\scripts\build_exe.ps1
```

### Discord / Zoom / Teams ile Kullanım (VB-Cable)
1. [VB-Audio Virtual Cable](https://vb-audio.com/Cable/) sürücüsünü kurun.
2. ClearMic → **Cihazlar & Test Stüdyosu** sekmesinde çıkış olarak `CABLE Input (VB-Audio Virtual Cable)` seçin ve **Başlat**'a basın.
3. Discord / Zoom / Teams mikrofon ayarlarında giriş cihazı olarak `CABLE Output (VB-Audio Virtual Cable)` seçin.

## Testler

```powershell
.\.venv\Scripts\python.exe -m pytest -v
```
