import sys, os, base64, json, re
from pathlib import Path
from urllib.parse import urljoin
import requests
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QTextEdit, QFileDialog, QComboBox, QSpinBox,
    QDoubleSpinBox, QGroupBox, QFormLayout, QMessageBox, QProgressBar, QSplitter,
    QCheckBox, QScrollArea)

APP_NAME = "16oz Tumbler Wrap AI Studio"
RATIOS = {"21:9": (21, 9), "16:9": (16, 9), "3:2": (3, 2), "4:3": (4, 3),
          "2:1": (2, 1), "1:1": (1, 1), "3:4": (3, 4), "9:16": (9, 16), "Custom": None}

def settings_path():
    p = Path(os.getenv("APPDATA", str(Path.home()))) / "TumblerWrapAI"
    p.mkdir(parents=True, exist_ok=True)
    return p / "settings.json"

def load_settings():
    try: return json.loads(settings_path().read_text(encoding="utf-8"))
    except Exception: return {}

def save_settings(data):
    settings_path().write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def build_endpoint(base_url, endpoint):
    """Join a provider base URL and endpoint without duplicating /v1."""
    base = base_url.strip().rstrip("/")
    path = endpoint.strip()
    if not base or not path:
        raise ValueError("请填写 API Base URL 和接口路径。")
    if path.startswith("http://") or path.startswith("https://"):
        return path
    # Treat Base URL as the prefix; endpoint may be /v1/... or images/...
    from urllib.parse import urlsplit, urlunsplit
    b = urlsplit(base)
    base_path = b.path.rstrip("/")
    endpoint_path = "/" + path.lstrip("/")
    if base_path and endpoint_path.startswith(base_path + "/"):
        final_path = endpoint_path
    elif base_path.endswith("/v1") and endpoint_path.startswith("/v1/"):
        final_path = base_path + endpoint_path[3:]
    else:
        final_path = base_path + endpoint_path
    return urlunsplit((b.scheme, b.netloc, final_path, "", ""))


def extract_images(body):
    """Accept common OpenAI-compatible and relay-provider image response shapes."""
    if isinstance(body, list):
        candidates = body
    elif isinstance(body, dict):
        candidates = body.get("data") or body.get("images") or body.get("output") or []
        if isinstance(candidates, dict):
            candidates = candidates.get("images") or candidates.get("data") or [candidates]
        if not candidates and any(k in body for k in ("b64_json", "url", "image", "image_url")):
            candidates = [body]
    else:
        candidates = []
    if isinstance(candidates, str):
        candidates = [candidates]
    out = []
    for item in candidates:
        if isinstance(item, str):
            value = item
        elif isinstance(item, dict):
            value = (item.get("b64_json") or item.get("base64") or item.get("image")
                     or item.get("url") or item.get("image_url") or item.get("data"))
        else:
            value = None
        if not value:
            continue
        if isinstance(value, dict):
            value = value.get("url") or value.get("b64_json") or value.get("data")
        if not isinstance(value, str):
            continue
        if value.startswith("data:") and "," in value:
            header, value = value.split(",", 1)
            mime = header.split(";")[0].lower()
            ext = "jpg" if "jpeg" in mime else ("webp" if "webp" in mime else "png")
            try:
                out.append((base64.b64decode(value), ext))
            except Exception:
                continue
        elif value.startswith(("http://", "https://")):
            out.append((value, "url"))
        else:
            try:
                out.append((base64.b64decode(value), "png"))
            except Exception:
                continue
    return out


class Worker(QThread):
    done = Signal(list)
    failed = Signal(str)
    progress = Signal(str)
    def __init__(self, cfg, prompt, image_path, count, strength):
        super().__init__(); self.cfg=cfg; self.prompt=prompt; self.image_path=image_path
        self.count=count; self.strength=strength
    def run(self):
        try:
            headers={"Authorization":"Bearer "+self.cfg["api_key"]}
            model=self.cfg["image_model"]
            endpoint=self.cfg["edit_path"] if self.image_path else self.cfg["generate_path"]
            url=build_endpoint(self.cfg["base_url"], endpoint)
            try:
                extra=json.loads(self.cfg.get("extra_params","{}") or "{}")
                if not isinstance(extra, dict):
                    raise ValueError('额外请求参数必须是 JSON 对象，例如 {"quality": "high"}')
            except json.JSONDecodeError as e:
                raise ValueError(f"额外请求参数 JSON 格式错误：{e}")
            self.progress.emit("正在请求图像服务…")
            if self.image_path:
                field=(self.cfg.get("image_field","image").strip() or "image")
                with open(self.image_path,"rb") as f:
                    files={field:(Path(self.image_path).name,f,"application/octet-stream")}
                    data={"model":model,"prompt":self.prompt,"n":str(self.count),"size":self.cfg["size"]}
                    data.update({k: str(v) if not isinstance(v,(dict,list)) else json.dumps(v,ensure_ascii=False)
                                 for k,v in extra.items()})
                    r=requests.post(url,headers=headers,files=files,data=data,timeout=self.cfg["timeout"])
            else:
                payload={"model":model,"prompt":self.prompt,"n":self.count,"size":self.cfg["size"]}
                payload.update(extra)
                r=requests.post(url,headers={**headers,"Content-Type":"application/json"},
                                json=payload,timeout=self.cfg["timeout"])
            if not r.ok:
                detail=r.text[:2000]
                raise RuntimeError(f"HTTP {r.status_code}：{detail}\n\n请检查中转站地址、模型名、接口路径及额外参数。")
            try:
                body=r.json()
            except Exception:
                raise RuntimeError("接口返回的不是 JSON。响应开头：\n"+r.text[:1000])
            items=extract_images(body)
            out=[]
            for value,ext in items:
                if ext=="url":
                    q=requests.get(value,timeout=self.cfg["timeout"]); q.raise_for_status()
                    blob=q.content
                    if blob[:3]==b"\xff\xd8\xff": ext="jpg"
                    elif blob[:4]==b"RIFF": ext="webp"
                    else: ext="png"
                else:
                    blob=value
                    if blob[:3]==b"\xff\xd8\xff": ext="jpg"
                    elif blob[:4]==b"RIFF": ext="webp"
                if blob:
                    out.append((blob,ext))
            if not out:
                preview=json.dumps(body,ensure_ascii=False)[:1600]
                raise RuntimeError("接口请求成功，但未识别到图片。支持 data[].b64_json、data[].url、images、output、Base64 和 data:image/... 返回。\n响应内容：\n"+preview)
            self.done.emit(out)
        except Exception as e:
            self.failed.emit(str(e))

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__(); self.setWindowTitle(APP_NAME); self.resize(1120,820)
        self.cfg=load_settings(); self.source_image=""; self.results=[]
        root=QWidget(); self.setCentralWidget(root); outer=QVBoxLayout(root)
        title=QLabel("16oz TUMBLER WRAP AI STUDIO"); title.setStyleSheet("font-size:22px;font-weight:700;padding:8px")
        outer.addWidget(title)
        split=QSplitter(Qt.Horizontal); outer.addWidget(split,1)
        left=QWidget(); lv=QVBoxLayout(left); split.addWidget(left)
        api=QGroupBox("01 · API 服务设置"); form=QFormLayout(api)
        self.base=QLineEdit(self.cfg.get("base_url","https://api.openai.com"))
        self.key=QLineEdit(self.cfg.get("api_key","")); self.key.setEchoMode(QLineEdit.Password)
        self.model=QLineEdit(self.cfg.get("image_model","gpt-image-1"))
        self.genpath=QLineEdit(self.cfg.get("generate_path","/v1/images/generations"))
        self.editpath=QLineEdit(self.cfg.get("edit_path","/v1/images/edits"))
        self.imagefield=QLineEdit(self.cfg.get("image_field","image"))
        self.extra=QLineEdit(self.cfg.get("extra_params","{}"))
        self.timeout=QSpinBox(); self.timeout.setRange(30,900); self.timeout.setValue(int(self.cfg.get("timeout",300)))
        for label,w in [("API Base URL（支持中转站）",self.base),("API Key",self.key),("生图模型名称",self.model),
                        ("文生图接口路径",self.genpath),("图生图接口路径",self.editpath),
                        ("参考图字段名",self.imagefield),("额外请求参数 JSON",self.extra),("超时（秒）",self.timeout)]:
            form.addRow(label,w)
        hint=QLabel("中转站示例：Base URL 填 https://域名/v1；接口路径填 images/generations。可按服务商要求填写额外参数。")
        hint.setWordWrap(True); hint.setStyleSheet("color:#777")
        form.addRow(hint)
        save=QPushButton("保存 API 设置"); save.clicked.connect(self.save_api); form.addRow(save); lv.addWidget(api)
        opt=QGroupBox("02 · 画布与生成参数"); of=QFormLayout(opt)
        self.ratio=QComboBox(); self.ratio.addItems(list(RATIOS)); self.ratio.setCurrentText("21:9")
        self.width=QSpinBox(); self.width.setRange(256,4096); self.width.setValue(2100)
        self.height=QSpinBox(); self.height.setRange(256,4096); self.height.setValue(900)
        self.ratio.currentTextChanged.connect(self.ratio_changed)
        dims=QHBoxLayout(); dims.addWidget(self.width); dims.addWidget(QLabel("×")); dims.addWidget(self.height)
        self.count=QSpinBox(); self.count.setRange(1,8); self.count.setValue(1)
        self.strength=QDoubleSpinBox(); self.strength.setRange(0,1); self.strength.setSingleStep(.05); self.strength.setValue(.75)
        self.keep=QComboBox(); self.keep.addItems(["高（尽量保留原图主体）","中","低（允许较大改动）"])
        of.addRow("输出比例（默认 21:9）",self.ratio); of.addRow("像素宽 × 高",dims)
        of.addRow("生成张数",self.count); of.addRow("风格强度（0–1）",self.strength); of.addRow("原图内容保留",self.keep); lv.addWidget(opt)
        src=QGroupBox("03 · 参考图片"); sv=QVBoxLayout(src)
        self.src_label=QLabel("尚未选择图片（可选；选择后使用图生图）"); self.src_label.setAlignment(Qt.AlignCenter); self.src_label.setMinimumHeight(110)
        pick=QPushButton("选择参考图片"); pick.clicked.connect(self.pick_image)
        sv.addWidget(self.src_label); sv.addWidget(pick); lv.addWidget(src)
        promptbox=QGroupBox("04 · 贴花主题提示词"); pv=QVBoxLayout(promptbox)
        self.prompt=QTextEdit(); self.prompt.setPlaceholderText("描述主题、色彩、构图、文字元素…"); self.prompt.setMinimumHeight(130)
        self.prompt.setPlainText("Create a premium full-bleed sublimation tumbler wrap design for a 16oz tumbler. Preserve the uploaded subject identity. Build a cohesive story-driven composition with rich details, clean edges, print-ready artwork, no mockup, no cup, no hands, no watermark.")
        pv.addWidget(self.prompt); lv.addWidget(promptbox,1)
        go=QPushButton("生成贴花图片"); go.setMinimumHeight(44); go.clicked.connect(self.generate); lv.addWidget(go)
        self.status=QLabel("就绪"); lv.addWidget(self.status)
        self.bar=QProgressBar(); self.bar.setRange(0,0); self.bar.hide(); lv.addWidget(self.bar)
        right=QWidget(); rv=QVBoxLayout(right); split.addWidget(right)
        rv.addWidget(QLabel("生成结果预览"))
        self.preview=QLabel("生成的图片将在这里显示"); self.preview.setAlignment(Qt.AlignCenter); self.preview.setMinimumSize(420,360); self.preview.setStyleSheet("background:#20242b;color:#ddd;border-radius:8px")
        rv.addWidget(self.preview,1)
        self.export=QPushButton("导出全部图片"); self.export.clicked.connect(self.export_all); self.export.setEnabled(False); rv.addWidget(self.export)
        split.setSizes([480,620])
        self.ratio_changed("21:9")
    def ratio_changed(self, key):
        ratio=RATIOS.get(key)
        if ratio:
            w,h=2100,round(2100*ratio[1]/ratio[0]); self.width.setValue(w); self.height.setValue(h)
    def save_api(self):
        self.cfg.update(base_url=self.base.text().strip(),api_key=self.key.text().strip(),image_model=self.model.text().strip(),
          generate_path=self.genpath.text().strip(),edit_path=self.editpath.text().strip(),
          image_field=self.imagefield.text().strip() or "image",extra_params=self.extra.text().strip() or "{}",
          timeout=self.timeout.value())
        save_settings(self.cfg); QMessageBox.information(self,"已保存","API 设置已保存在本机用户目录，不会上传到 GitHub。")
    def pick_image(self):
        p,_=QFileDialog.getOpenFileName(self,"选择参考图片","","Images (*.png *.jpg *.jpeg *.webp)")
        if p:
            self.source_image=p; pix=QPixmap(p); self.src_label.setPixmap(pix.scaled(400,150,Qt.KeepAspectRatio,Qt.SmoothTransformation))
    def generate(self):
        self.save_api_silent()
        if not self.cfg.get("base_url") or not self.cfg.get("api_key") or not self.cfg.get("image_model"):
            QMessageBox.warning(self,"缺少 API 设置","请填写 API Base URL、API Key 和图像模型名称。"); return
        prompt=self.prompt.toPlainText().strip()
        if not prompt: QMessageBox.warning(self,"提示","请先填写生成提示词。"); return
        retain=self.keep.currentIndex()
        prompt += f"\\nCanvas aspect ratio {self.width.value()}:{self.height.value()}, target size {self.width.value()}x{self.height.value()} pixels. "
        prompt += ["Keep the original subject highly faithful; do not replace or redesign the main subject.","Preserve the main subject while adapting composition and style.","Creative reinterpretation is allowed while retaining the core theme."][retain]
        self.cfg["size"]=f"{self.width.value()}x{self.height.value()}"
        self.bar.show(); self.status.setText("正在生成…")
        self.worker=Worker(self.cfg,prompt,self.source_image,self.count.value(),self.strength.value())
        self.worker.progress.connect(self.status.setText); self.worker.done.connect(self.got_results); self.worker.failed.connect(self.failed); self.worker.start()
    def save_api_silent(self):
        self.cfg.update(base_url=self.base.text().strip(),api_key=self.key.text().strip(),image_model=self.model.text().strip(),
          generate_path=self.genpath.text().strip(),edit_path=self.editpath.text().strip(),
          image_field=self.imagefield.text().strip() or "image",extra_params=self.extra.text().strip() or "{}",
          timeout=self.timeout.value())
        save_settings(self.cfg)
    def got_results(self, items):
        self.bar.hide(); self.results=items; self.status.setText(f"完成：{len(items)} 张图片")
        self.export.setEnabled(True); self.show_result(0)
    def failed(self, msg):
        self.bar.hide(); self.status.setText("生成失败"); QMessageBox.critical(self,"生成失败",msg)
    def show_result(self, i):
        blob,ext=self.results[i]; path=Path(os.getenv("TEMP",str(Path.home()))) / f"tumbler_preview_{i}.{ext}"
        path.write_bytes(blob); pix=QPixmap(str(path)); self.preview.setPixmap(pix.scaled(self.preview.size(),Qt.KeepAspectRatio,Qt.SmoothTransformation))
    def resizeEvent(self,e):
        super().resizeEvent(e)
        if self.results: self.show_result(0)
    def export_all(self):
        if not self.results: return
        folder=QFileDialog.getExistingDirectory(self,"选择导出文件夹")
        if not folder: return
        for i,(blob,ext) in enumerate(self.results,1): (Path(folder)/f"16oz_wrap_{i}.{ext}").write_bytes(blob)
        QMessageBox.information(self,"导出完成",f"已导出 {len(self.results)} 张图片。")

if __name__ == "__main__":
    app=QApplication(sys.argv); app.setStyle("Fusion")
    w=MainWindow(); w.show(); sys.exit(app.exec())
