# 16oz Tumbler Wrap AI Studio

Windows desktop application for creating 16oz tumbler wrap artwork with a configurable OpenAI-compatible image API.

## Features
- Canvas ratio presets: 21:9 (default), 16:9, 3:2, 4:3, 2:1, 1:1, 3:4, 9:16, plus custom dimensions.
- Optional reference image and image-edit endpoint.
- Batch generation (1–8), style strength, and subject-retention prompt control.
- Works with official APIs and third-party OpenAI-compatible relay services; configure Base URL, API key, model, generation/edit paths, image multipart field, timeout and extra JSON parameters.
- Accepts common image responses including `data[].b64_json`, `data[].url`, `images`, `output`, Base64 strings and `data:image/...` URLs.
- API key is stored locally under the current Windows user's AppData folder.

## API compatibility
The default request formats follow common OpenAI-style image endpoints:
- Generate: POST /v1/images/generations (JSON: model, prompt, n, size)
- Edit: POST /v1/images/edits (multipart: image, model, prompt, n, size, strength)

Providers vary. Configure endpoint paths, reference-image field name and extra JSON parameters to match your relay provider. Some providers do not support image editing, batch count, custom sizes or particular optional parameters; consult the provider's API documentation.

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
