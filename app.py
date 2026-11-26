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

class Worker(QThread):
    done = Signal(list)
    failed = Signal(str)
    progress = Signal(str)
    def __init__(self, cfg, prompt, image_path, count, strength):
        super().__init__(); self.cfg=cfg; self.prompt=prompt; self.image_path=image_path
        self.count=count; self.strength=strength
    def run(self):
        try:
            base=self.cfg["base_url"].rstrip("/")+"/"
            headers={"Authorization":"Bearer "+self.cfg["api_key"]}
            model=self.cfg["image_model"]
            endpoint=self.cfg["edit_path"] if self.image_path else self.cfg["generate_path"]
            url=urljoin(base, endpoint.lstrip("/"))
            self.progress.emit("正在请求图像服务…")
            if self.image_path:
                with open(self.image_path,"rb") as f:
                    files={"image":(Path(self.image_path).name,f,"application/octet-stream")}
                    data={"model":model,"prompt":self.prompt,"n":str(self.count),
                          "size":self.cfg["size"],"strength":str(self.strength)}
                    r=requests.post(url,headers=headers,files=files,data=data,timeout=self.cfg["timeout"])
            else:
                payload={"model":model,"prompt":self.prompt,"n":self.count,"size":self.cfg["size"]}
                r=requests.post(url,headers={**headers,"Content-Type":"application/json"},
                                json=payload,timeout=self.cfg["timeout"])
            if not r.ok: raise RuntimeError(f"HTTP {r.status_code}: {r.text[:1200]}")
            body=r.json(); items=body.get("data",[])
            if not items: raise RuntimeError("接口返回成功，但响应中没有 data 图片列表。请检查服务商的响应格式。")
            out=[]
            for i,item in enumerate(items):
                raw=item.get("b64_json")
                if raw: blob=base64.b64decode(raw)
                elif item.get("url"):
                    q=requests.get(item["url"],timeout=self.cfg["timeout"]); q.raise_for_status(); blob=q.content
                else: continue
                ext="png"
                if blob[:3]==b"\\xff\\xd8\\xff": ext="jpg"
                elif blob[:4]==b"RIFF": ext="webp"
                out.append((blob,ext))
            if not out: raise RuntimeError("没有识别到 b64_json 或 url 图片数据。")
            self.done.emit(out)
        except Exception as e: self.failed.emit(str(e))

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
        self.timeout=QSpinBox(); self.timeout.setRange(30,900); self.timeout.setValue(int(self.cfg.get("timeout",300)))
        for label,w in [("API Base URL",self.base),("API Key",self.key),("图像模型",self.model),
                        ("文生图 Endpoint",self.genpath),("图生图 Endpoint",self.editpath),("超时（秒）",self.timeout)]:
            form.addRow(label,w)
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
          generate_path=self.genpath.text().strip(),edit_path=self.editpath.text().strip(),timeout=self.timeout.value())
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
          generate_path=self.genpath.text().strip(),edit_path=self.editpath.text().strip(),timeout=self.timeout.value())
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
