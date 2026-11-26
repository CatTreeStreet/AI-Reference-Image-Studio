# 16oz Tumbler Wrap AI Studio

Windows desktop application for creating 16oz tumbler wrap artwork with a configurable OpenAI-compatible image API.

## Features
- Canvas ratio presets: 21:9 (default), 16:9, 3:2, 4:3, 2:1, 1:1, 3:4, 9:16, plus custom dimensions.
- Optional reference image and image-edit endpoint.
- Batch generation (1–8), style strength, and subject-retention prompt control.
- API Base URL, API key, model, endpoint paths and timeout are configurable.
- API key is stored locally under the current Windows user's AppData folder.

## API compatibility
The default request formats follow common OpenAI-style image endpoints:
- Generate: POST /v1/images/generations (JSON: model, prompt, n, size)
- Edit: POST /v1/images/edits (multipart: image, model, prompt, n, size, strength)

Providers vary. Some use different field names, image input names, response formats, or do not support editing/batch/size. Configure endpoint paths as needed; the request schema may require provider-specific adaptation. The app currently reads `data[].b64_json` or `data[].url`.

## Build
Python 3.11 recommended:
```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

## Windows EXE
Push to `main` or run the **Build Windows EXE** workflow manually in GitHub Actions. Download the generated artifact named `16oz-Tumbler-Wrap-AI-Studio-Windows`.
