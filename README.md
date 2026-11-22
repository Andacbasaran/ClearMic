# ClearMic

%100 offline, 0 MB VRAM, ultra düşük gecikmeli yapay zeka mikrofon gürültü engelleyici — açık kaynaklı Krisp / NVIDIA Broadcast alternatifi.

## Özellikler (MVP)
- **CPU üzerinde ONNX ile gerçek zamanlı ses temizleme:** Streaming `GTCRN` ONNX modeli (~520 KB, blok başına ~1.1 ms CPU işlem süresi, 0 MB VRAM) + anında çalışan Spectral DSP yedek motoru
- **Sanal mikrofon köprüsü (VB-Cable):** VB-Cable otomatik algılama ile Discord, Zoom, Teams ve oyunlarda doğrudan kullanım
- **Canlı Ses Monitörü & A/B Karşılaştırma:** Ham ve temizlenmiş ses dalgasını üst üste gösteren canlı monitör, giriş/çıkış dB metreleri ve tek tıkla A/B (Temiz / Ham Ses) geçişi
- **DSP Ses Zinciri:** 80 Hz Yüksek Geçiren Filtre (HPF), Attack/Hold/Release destekli Gürültü Kapısı (Noise Gate), konuşma odaklı Otomatik Kazanç Kontrolü (AGC) ve Soft Limiter
- **Sistem Tepsisi (System Tray):** Pencere kapatıldığında arka planda sessiz çalışma, tepsi menüsünden hızlı Başlat/Durdur ve A/B Bypass kontrolü

## Kurulum ve Çalıştırma

```powershell
python -m venv .venv
.\.venv\Scripts\pip.exe install -r requirements.txt
.\.venv\Scripts\python.exe run.py
```

> **Not:** `GTCRN` ONNX modeli (`models/gtcrn_simple.onnx`) kurulu değilse arayüzdeki **"ONNX Modelini İndir (~520 KB)"** butonuyla tek tıkla indirilebilir; indirilmeden önce de Spectral DSP motoruyla anında çalışır.

### Discord / Zoom / Teams ile Kullanım (VB-Cable)
1. [VB-Audio Virtual Cable](https://vb-audio.com/Cable/) sürücüsünü kurun.
2. ClearMic içinde **Çıkış (Sanal Kablo)** olarak `CABLE Input (VB-Audio Virtual Cable)` seçin ve **Başlat**'a basın.
3. Discord / Zoom / Teams mikrofon ayarlarında giriş cihazı olarak `CABLE Output (VB-Audio Virtual Cable)` seçin.

## Testler

```powershell
.\.venv\Scripts\python.exe -m pytest -v
```
