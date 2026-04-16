import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

// 辅助函数：链式回调
function chainCallback(object, property, callback) {
    if (object == undefined) {
        console.error("Tried to add callback to non-existant object");
        return;
    }
    if (property in object && object[property]) {
        const callback_orig = object[property];
        object[property] = function () {
            const r = callback_orig.apply(this, arguments);
            return callback.apply(this, arguments) ?? r;
        };
    } else {
        object[property] = callback;
    }
}

// 上传文件函数（使用 ComfyUI 内置路由）
async function uploadFile(file) {
    try {
        const body = new FormData();
        body.append("image", file);
        const resp = await api.fetchApi("/upload/image", {
            method: "POST",
            body,
        });

        if (resp.status === 200) {
            return resp;
        } else {
            alert(resp.status + " - " + resp.statusText);
        }
    } catch (error) {
        alert(error);
    }
    return null;
}

// 添加视频预览
function addVideoPreview(nodeType) {
    chainCallback(nodeType.prototype, "onNodeCreated", function () {
        const node = this;
        const element = document.createElement("div");
        
        const previewWidget = this.addDOMWidget("videopreview", "preview", element, {
            serialize: false,
            hideOnZoom: false,
        });
        
        previewWidget.computeSize = function (width) {
            if (this.aspectRatio && !this.parentEl.hidden) {
                const height = (node.size[0] - 20) / this.aspectRatio + 10;
                if (height > 0) {
                    return [width, height];
                }
            }
            return [width, 0];
        };
        
        previewWidget.parentEl = document.createElement("div");
        previewWidget.parentEl.style.width = "100%";
        previewWidget.parentEl.hidden = true;
        element.appendChild(previewWidget.parentEl);
        
        previewWidget.videoEl = document.createElement("video");
        previewWidget.videoEl.controls = true;
        previewWidget.videoEl.loop = true;
        previewWidget.videoEl.muted = true;
        previewWidget.videoEl.style.width = "100%";
        previewWidget.videoEl.autoplay = true;
        
        previewWidget.videoEl.addEventListener("loadedmetadata", () => {
            previewWidget.aspectRatio = previewWidget.videoEl.videoWidth / previewWidget.videoEl.videoHeight;
            node.setSize([node.size[0], node.computeSize()[1]]);
            node.setDirtyCanvas(true, true);
        });
        
        previewWidget.videoEl.addEventListener("error", () => {
            previewWidget.parentEl.hidden = true;
            node.setSize([node.size[0], node.computeSize()[1]]);
            node.setDirtyCanvas(true, true);
        });
        
        previewWidget.parentEl.appendChild(previewWidget.videoEl);
        
        // 更新视频源的方法
        this.updateVideoSource = (filename) => {
            if (!filename) return;
            
            const params = {
                filename: filename,
                type: "input",
                format: "video/mp4",
                timestamp: Date.now()
            };
            
            previewWidget.videoEl.src = api.apiURL('/view?' + new URLSearchParams(params));
            previewWidget.parentEl.hidden = false;
        };
    });
}

app.registerExtension({
    name: "Seedance2.VideoUpload",
    async beforeRegisterNodeDef(nodeType, nodeData, app) {
        if (nodeData.name === "Seedance Video Upload") {
            addVideoPreview(nodeType);
            
            chainCallback(nodeType.prototype, "onNodeCreated", function () {
                const node = this;
                const pathWidget = this.widgets.find((w) => w.name === "video_path");
                
                // 创建文件输入元素
                const fileInput = document.createElement("input");
                Object.assign(fileInput, {
                    type: "file",
                    accept: "video/webm,video/mp4,video/x-matroska",
                    style: "display: none",
                    onchange: async () => {
                        if (fileInput.files.length) {
                            const resp = await uploadFile(fileInput.files[0]);
                            if (resp && resp.status === 200) {
                                const data = await resp.json();
                                const filename = data.name;
                                
                                // 更新 widget 值
                                pathWidget.value = filename;
                                if (pathWidget.callback) {
                                    pathWidget.callback(filename);
                                }
                                
                                // 更新视频预览
                                node.updateVideoSource(filename);
                                
                                node.setDirtyCanvas(true, true);
                            }
                        }
                    },
                });
                document.body.append(fileInput);
                
                // 清理
                chainCallback(this, "onRemoved", () => {
                    fileInput?.remove();
                });
                
                // 添加 "choose video to upload" 按钮
                const uploadWidget = this.addWidget("button", "choose video to upload", null, () => {
                    fileInput.click();
                });
                uploadWidget.serialize = false;
                
                // 监听路径变化
                chainCallback(pathWidget, "callback", (value) => {
                    if (value) {
                        node.updateVideoSource(value);
                    }
                });
            });
        }
    },
});
