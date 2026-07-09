# ReForge – Modular Reverse Engineering Toolkit

ReForge is a cross‑platform, modular reverse‑engineering framework built with Python and PyQt6.  
It provides a modern GUI, a plugin system for dynamic tool loading, and built‑in modules for  
APK license removal, binary patching, and dynamic instrumentation.

## Features

- **Modular Plugin System** – All RE capabilities are loaded as independent plugins at runtime.  
- **Docking GUI** – Dark‑themed, fully dockable interface (like IDA Pro or Ghidra).  
- **Non‑blocking Analysis** – Heavy tasks run in `QThread` workers, keeping the UI responsive.  
- **Bulletproof Error Handling** – Global exception hook logs crashes and shows a user‑friendly dialog.  
- **APK Patcher** (built‑in plugin)  
  - Google LVL / Pairip bypass  
  - Pro/Premium feature flag forcing  
  - SSL pinning removal  
  - Signature check killing  
  - INTERNET permission removal  
- **EXE Patcher** (stub, ready for extension)  
- **Frida Tools** (stub, ready for extension)  
- **Central Event Bus** – Plugins can communicate without direct coupling.

## Installation

### Prerequisites

- Python 3.10+
- Java JDK/JRE
- [apktool](https://apktool.org/)
- [jadx](https://github.com/skylot/jadx)
- [apksigner](https://developer.android.com/studio/command-line/apksigner)
- `zipalign` (from Android SDK)
- `keytool` (bundled with Java)
- (optional) `uber-apk-signer` for fallback signing

### Setup

1. Clone the repository or copy the `reforge/` folder to your machine.
2. Install Python dependencies:
   ```bash
   pip install -r requirements.txt