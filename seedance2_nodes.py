import hashlib
import io
import mimetypes
import os
import sys
import time
import urllib.request
import uuid
import numpy as np
import base64
import cv2
from typing import List, Tuple, Optional, Any

try:
    from comfy.video import VideoEncode
    COMFY_VIDEO_AVAILABLE = True
except ImportError:
    COMFY_VIDEO_AVAILABLE = False

try:
    import folder_paths
    FOLDER_PATHS_AVAILABLE = True
except ImportError:
    FOLDER_PATHS_AVAILABLE = False

try:
    from volcenginesdkarkruntime import Ark
    ARK_SDK_AVAILABLE = True
except ImportError:
    ARK_SDK_AVAILABLE = False


ARK_API_URL = "https://ark.cn-beijing.volces.com/api/v3"


def get_ark_client():
    global ARK_SDK_AVAILABLE
    global Ark

    api_key = os.environ.get("ARK_API_KEY", "")

    if not api_key:
        return None

    if not ARK_SDK_AVAILABLE:
        print("Error: 请手动安装 SDK: pip install 'volcengine-python-sdk[ark]'")
        return None

    return Ark(
        base_url=ARK_API_URL,
        api_key=api_key.strip()
    )


def tensor_to_base64(tensor) -> str:
    if hasattr(tensor, 'cpu'):
        tensor = tensor.cpu().numpy()

    if len(tensor.shape) == 4:
        tensor = tensor[0]

    if tensor.dtype != np.uint8:
        if tensor.max() <= 1.0:
            tensor = (tensor * 255).astype(np.uint8)
        else:
            tensor = tensor.astype(np.uint8)

    if len(tensor.shape) == 3:
        if tensor.shape[0] == 3:
            tensor = np.transpose(tensor, (1, 2, 0))
        if tensor.shape[2] == 3:
            tensor = cv2.cvtColor(tensor, cv2.COLOR_RGB2BGR)
    elif len(tensor.shape) == 2:
        tensor = cv2.cvtColor(tensor, cv2.COLOR_GRAY2BGR)

    _, buffer = cv2.imencode(".jpg", tensor)
    return base64.b64encode(buffer).decode("utf-8")


def download_video(video_url: str, save_path: str) -> bool:
    try:
        req = urllib.request.Request(video_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=120) as response:
            with open(save_path, "wb") as f:
                f.write(response.read())
        return True
    except Exception as e:
        print(f"Download failed: {e}")
        return False


class DoubaoImageAggregator:
    """图片聚合节点 - 聚合0-9张图片，输出给视频生成节点使用"""

    @classmethod
    def INPUT_TYPES(cls):
        inputs = {
            "required": {},
            "optional": {}
        }
        for i in range(1, 10):
            inputs["optional"][f"image_{i}"] = ("IMAGE",)
        return inputs

    RETURN_TYPES = ("DOUBAO_IMAGE_LIST",)
    RETURN_NAMES = ("image_list",)
    FUNCTION = "aggregate_images"
    CATEGORY = "Doubao/Seedance"

    def aggregate_images(self, **kwargs) -> tuple:
        image_list = []
        for i in range(1, 10):
            key = f"image_{i}"
            if key in kwargs and kwargs[key] is not None:
                image_list.append(kwargs[key])

        if len(image_list) == 0:
            print("警告: 没有输入任何图片")

        print(f"图片聚合节点: 收集了 {len(image_list)} 张图片")
        return (image_list,)


class DoubaoAudioAggregator:
    """音频聚合节点 - 聚合0-3个音频，输出给视频生成节点使用"""

    @classmethod
    def INPUT_TYPES(cls):
        inputs = {
            "required": {},
            "optional": {}
        }
        for i in range(1, 4):
            inputs["optional"][f"audio_{i}"] = ("AUDIO",)
        return inputs

    RETURN_TYPES = ("DOUBAO_AUDIO_LIST",)
    RETURN_NAMES = ("audio_list",)
    FUNCTION = "aggregate_audios"
    CATEGORY = "Doubao/Seedance"

    def aggregate_audios(self, **kwargs) -> tuple:
        audio_list = []
        for i in range(1, 4):
            key = f"audio_{i}"
            if key in kwargs and kwargs[key] is not None:
                audio_list.append(kwargs[key])

        print(f"音频聚合节点: 收集了 {len(audio_list)} 个音频")
        return (audio_list,)


class DoubaoVideoAggregator:
    """视频聚合节点 - 聚合0-3个视频，上传到火山TOS后输出给视频生成节点使用"""

    @classmethod
    def INPUT_TYPES(cls):
        inputs = {
            "required": {
                "bucket": ("STRING", {
                    "default": "",
                    "placeholder": "your-bucket-name",
                    "tooltip": "TOS 桶名称"
                }),
                "endpoint": ("STRING", {
                    "default": "tos-cn-beijing.volces.com",
                    "tooltip": "TOS Endpoint，例如 tos-cn-beijing.volces.com"
                }),
                "region": ("STRING", {
                    "default": "cn-beijing",
                    "tooltip": "桶所在地域，例如 cn-beijing"
                }),
                "expires_seconds": ("INT", {
                    "default": 3600,
                    "min": 60,
                    "max": 2592000,
                    "step": 60,
                    "tooltip": "预签名 URL 时效，单位秒，范围 60-2592000（30天）"
                }),
                "reuse_existing": ("BOOLEAN", {
                    "default": False,
                    "tooltip": "是否按文件内容哈希复用已上传对象。关闭时每次都会重新上传"
                }),
                "object_prefix": ("STRING", {
                    "default": "seedance/",
                    "tooltip": "上传到桶内的对象前缀"
                }),
            },
            "optional": {}
        }
        # 添加3个视频输入口
        for i in range(1, 4):
            inputs["optional"][f"video_{i}"] = ("VIDEO", {"tooltip": f"视频输入 {i}"})
        return inputs

    RETURN_TYPES = ("DOUBAO_VIDEO_LIST",)
    RETURN_NAMES = ("video_url_list",)
    FUNCTION = "aggregate_and_upload_videos"
    CATEGORY = "Doubao/Seedance"

    def __init__(self):
        self.tos_client = None

    def _import_tos(self):
        """导入TOS SDK"""
        try:
            import tos
            return tos
        except ImportError as e:
            raise ImportError(
                "未安装 TOS Python SDK。请先执行 `pip install tos`，或安装更新后的 requirements.txt 依赖。"
            ) from e

    def _initialize_tos_client(self, endpoint, region):
        """初始化TOS客户端"""
        tos = self._import_tos()
        access_key = os.environ.get("TOS_ACCESS_KEY")
        secret_key = os.environ.get("TOS_SECRET_KEY")

        if not access_key or not secret_key:
            raise ValueError("请先设置环境变量 TOS_ACCESS_KEY 和 TOS_SECRET_KEY")

        return tos.TosClientV2(access_key.strip(), secret_key.strip(), endpoint.strip(), region.strip())

    def _validate_video_filename(self, filename):
        """验证视频文件名"""
        ext = os.path.splitext(filename)[1].lower()
        if ext not in (".mp4", ".mov"):
            raise ValueError(f"当前仅支持上传 .mp4 或 .mov，检测到: {ext or '无扩展名'}")
        return ext

    def _build_object_key(self, object_prefix, filename, content_hash=None):
        """构建对象键"""
        prefix = (object_prefix or "").strip().strip("/")
        name, ext = os.path.splitext(os.path.basename(filename))
        safe_name = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in name).strip("_") or "video"
        if content_hash:
            object_name = f"{safe_name}_{content_hash[:16]}{ext.lower()}"
        else:
            object_name = f"{safe_name}_{uuid.uuid4().hex[:12]}{ext.lower()}"
        return f"{prefix}/{object_name}" if prefix else object_name

    def _hash_bytes(self, data):
        """计算数据哈希"""
        return hashlib.sha256(data).hexdigest()

    def _object_exists(self, client, bucket, object_key):
        """检查对象是否已存在"""
        attempts = [
            lambda: client.head_object(bucket=bucket, key=object_key),
            lambda: client.head_object(bucket, object_key),
        ]

        for attempt in attempts:
            try:
                attempt()
                return True
            except Exception as e:
                error_name = e.__class__.__name__
                if error_name in ("TosServerError", "TosClientError"):
                    status_code = getattr(e, "status_code", None)
                    if status_code == 404:
                        return False
                    code = getattr(e, "code", None)
                    if code in ("NoSuchKey", "NotFound"):
                        return False
                continue

        return False

    def _put_object_with_fallbacks(self, client, bucket, object_key, data, content_type):
        """上传对象（带兼容性回退）"""
        attempts = [
            lambda: client.put_object(bucket=bucket, key=object_key, content=data, content_type=content_type),
            lambda: client.put_object(bucket, object_key, content=data, content_type=content_type),
            lambda: client.put_object(bucket, object_key, data),
        ]

        last_error = None
        for attempt in attempts:
            try:
                return attempt()
            except TypeError as e:
                last_error = e

        if last_error is not None:
            raise last_error

    def _generate_presigned_url(self, client, bucket, object_key, expires_seconds):
        """生成预签名URL"""
        tos = self._import_tos()
        http_method = getattr(getattr(tos, "HttpMethodType", None), "Http_Method_Get", None)

        attempts = [
            lambda: client.pre_signed_url(http_method=http_method, bucket=bucket, key=object_key, expires=expires_seconds) if http_method is not None else (_ for _ in ()).throw(TypeError("HttpMethodType unavailable")),
            lambda: client.pre_signed_url(http_method, bucket, object_key, expires_seconds) if http_method is not None else (_ for _ in ()).throw(TypeError("HttpMethodType unavailable")),
            lambda: client.pre_signed_url(http_method="GET", bucket=bucket, key=object_key, expires=expires_seconds),
            lambda: client.pre_signed_url("GET", bucket, object_key, expires_seconds),
        ]

        result = None
        last_error = None
        for attempt in attempts:
            try:
                result = attempt()
                break
            except TypeError as e:
                last_error = e

        if result is None and last_error is not None:
            raise last_error

        for attr in ("signed_url", "sign_url", "url"):
            value = getattr(result, attr, None)
            if value:
                return value

        if isinstance(result, str):
            return result

        return str(result)

    def _upload_video_to_tos(self, video_path, bucket, endpoint, region, expires_seconds, reuse_existing, object_prefix) -> str:
        """上传视频到TOS并返回预签名URL"""
        import requests

        # 验证视频路径
        if not video_path or not os.path.exists(video_path):
            print(f"[TOSVideoAggregator] ❌ 视频文件不存在: {video_path}")
            return ""

        # 验证文件名
        filename = os.path.basename(video_path)
        try:
            ext = self._validate_video_filename(filename)
        except ValueError as e:
            print(f"[TOSVideoAggregator] ❌ {e}")
            return ""

        # 检测MIME类型
        content_type = mimetypes.guess_type(filename)[0] or ("video/mp4" if ext == ".mp4" else "video/quicktime")

        # 读取文件数据
        file_size_bytes = os.path.getsize(video_path)
        file_size_mb = file_size_bytes / (1024 * 1024)

        # 检查大小限制（参考视频50MB限制）
        if file_size_mb > 50:
            print(f"[TOSVideoAggregator] ❌ 视频大小 {file_size_mb:.2f} MB 超过 50 MB 限制")
            return ""

        with open(video_path, "rb") as f:
            data = f.read()

        content_hash = self._hash_bytes(data)

        # 初始化客户端（如果还没初始化）
        if self.tos_client is None:
            self.tos_client = self._initialize_tos_client(endpoint, region)

        # 构建对象键
        if reuse_existing:
            object_key = self._build_object_key(object_prefix, filename, content_hash=content_hash)
            reused_existing = self._object_exists(self.tos_client, bucket.strip(), object_key)
        else:
            object_key = self._build_object_key(object_prefix, filename)
            reused_existing = False

        # 上传文件（如果不复用）
        if not reused_existing:
            print(f"[TOSVideoAggregator] 📤 上传 {filename} ({file_size_mb:.2f} MB)...")
            self._put_object_with_fallbacks(self.tos_client, bucket.strip(), object_key, data, content_type)
            print(f"[TOSVideoAggregator] ✅ 上传成功: {object_key}")
        else:
            print(f"[TOSVideoAggregator] ♻️ 复用已有对象: {object_key}")

        # 生成预签名URL
        signed_url = self._generate_presigned_url(self.tos_client, bucket.strip(), object_key, expires_seconds)
        return signed_url

    def _extract_path_from_video(self, video):
        """从 VIDEO 对象中提取文件路径"""
        if video is None:
            return None
        if hasattr(video, "get_stream_source"):
            stream_source = video.get_stream_source()
            if isinstance(stream_source, str) and os.path.isfile(stream_source):
                return stream_source
        # 如果是字符串路径
        if isinstance(video, str) and os.path.isfile(video):
            return video
        return None

    def aggregate_and_upload_videos(self, bucket, endpoint, region, expires_seconds, reuse_existing, object_prefix, video_1=None, video_2=None, video_3=None) -> tuple:
        """聚合视频并上传到TOS，返回URL列表"""
        # 收集3个视频输入
        video_list = []
        for video in [video_1, video_2, video_3]:
            path = self._extract_path_from_video(video)
            if path:
                video_list.append(path)

        if len(video_list) == 0:
            print("[TOSVideoAggregator] 警告: 没有输入任何视频")
            return ([],)

        print(f"[TOSVideoAggregator] 收集了 {len(video_list)} 个视频，开始上传到TOS...")

        # 上传每个视频并收集URL
        uploaded_urls = []
        for i, video_path in enumerate(video_list):
            try:
                if video_path and os.path.exists(video_path):
                    url = self._upload_video_to_tos(
                        video_path, bucket, endpoint, region,
                        expires_seconds, reuse_existing, object_prefix
                    )
                    if url:
                        uploaded_urls.append(url)
                        print(f"[TOSVideoAggregator] 视频 {i+1}/{len(video_list)} 上传成功")
                    else:
                        print(f"[TOSVideoAggregator] 视频 {i+1}/{len(video_list)} 上传失败")
                else:
                    print(f"[TOSVideoAggregator] 视频 {i+1}/{len(video_list)} 路径无效")
            except Exception as e:
                print(f"[TOSVideoAggregator] 处理视频 {i+1} 失败: {e}")

        print(f"[TOSVideoAggregator] 完成: {len(uploaded_urls)}/{len(video_list)} 个视频上传成功")
        return (uploaded_urls,)


class DoubaoSeedanceVideoGenerator:
    """Seedance 2.0 视频生成节点 - 支持多模态输入（图片+音频）"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "prompt": ("STRING", {
                    "multiline": True,
                    "default": ""
                }),
                "model": (["doubao-seedance-2-0-260128", "doubao-seedance-2-0-fast-260128"], {
                    "default": "doubao-seedance-2-0-fast-260128"
                }),
                "resolution": (["480p", "720p"], {
                    "default": "720p"
                }),
                "ratio": (["16:9", "9:16", "1:1", "4:3", "3:4", "21:9"], {
                    "default": "16:9"
                }),
                "duration": ("INT", {
                    "default": 11,
                    "min": 4,
                    "max": 15,
                    "step": 1
                }),
                "generate_audio": ("BOOLEAN", {
                    "default": True
                }),
                "poll_interval": ("INT", {
                    "default": 30,
                    "min": 1,
                    "max": 30,
                    "step": 1,
                    "tooltip": "任务状态轮询间隔（秒）"
                }),
                "max_wait_time": ("INT", {
                    "default": 3600,
                    "min": 60,
                    "max": 3600,
                    "step": 30,
                    "tooltip": "最大等待时间（秒），超时后任务将被放弃"
                }),
            },
            "optional": {
                "image_list": ("DOUBAO_IMAGE_LIST",),
                "audio_list": ("DOUBAO_AUDIO_LIST",),
                "video_url_list": ("DOUBAO_VIDEO_LIST",),
                "seed": ("INT", {
                    "default": -1,
                    "min": -1,
                    "max": 2147483647,
                    "step": 1
                }),
            }
        }

    RETURN_TYPES = ("STRING", "VIDEO", "STRING", "STRING")
    RETURN_NAMES = ("text", "video", "video_url", "save_path")
    FUNCTION = "generate_video"
    CATEGORY = "Doubao/Seedance"

    def __init__(self):
        self.fps = 24
        self.output_dir = "seedance"

    def _tensor_to_base64(self, tensor) -> str:
        """将tensor转换为base64编码的图片"""
        if hasattr(tensor, 'cpu'):
            tensor = tensor.cpu().numpy()

        if len(tensor.shape) == 4:
            tensor = tensor[0]

        if tensor.dtype != np.uint8:
            if tensor.max() <= 1.0:
                tensor = (tensor * 255).astype(np.uint8)
            else:
                tensor = tensor.astype(np.uint8)

        if len(tensor.shape) == 3:
            if tensor.shape[0] == 3:
                tensor = np.transpose(tensor, (1, 2, 0))
            if tensor.shape[2] == 3:
                tensor = cv2.cvtColor(tensor, cv2.COLOR_RGB2BGR)
        elif len(tensor.shape) == 2:
            tensor = cv2.cvtColor(tensor, cv2.COLOR_GRAY2BGR)

        _, buffer = cv2.imencode(".jpg", tensor)
        return base64.b64encode(buffer).decode("utf-8")

    def _process_audio_to_base64(self, audio) -> Optional[str]:
        """处理音频数据为base64"""
        try:
            if isinstance(audio, dict):
                if 'waveform' in audio:
                    waveform = audio['waveform']
                    if hasattr(waveform, 'cpu'):
                        waveform = waveform.cpu().numpy()
                    audio_bytes = waveform.tobytes()
                    return base64.b64encode(audio_bytes).decode('utf-8')
                elif 'bytes' in audio:
                    return base64.b64encode(audio['bytes']).decode('utf-8')
            elif isinstance(audio, (bytes, bytearray)):
                return base64.b64encode(audio).decode('utf-8')
            elif hasattr(audio, 'numpy'):
                audio_bytes = audio.numpy().tobytes()
                return base64.b64encode(audio_bytes).decode('utf-8')
        except Exception as e:
            print(f"音频处理失败: {e}")
        return None

    def generate_video(
        self,
        prompt: str,
        model: str,
        resolution: str,
        ratio: str,
        duration: int,
        generate_audio: bool,
        poll_interval: int,
        max_wait_time: int,
        image_list: Optional[List] = None,
        audio_list: Optional[List] = None,
        video_url_list: Optional[List] = None,
        seed: int = -1
    ) -> tuple:
        """生成视频"""
        client = get_ark_client()

        if client is None:
            if not ARK_SDK_AVAILABLE:
                error_msg = "Error: Please install SDK: pip install 'volcengine-python-sdk[ark]'"
            else:
                error_msg = "Error: API Key is required. Please set ARK_API_KEY environment variable."
            print(error_msg)
            return (error_msg, None, "", "")

        # 处理图片
        image_base64_list = []
        if image_list and len(image_list) > 0:
            for i, img in enumerate(image_list):
                try:
                    img_base64 = self._tensor_to_base64(img)
                    image_base64_list.append(img_base64)
                    print(f"处理图片 {i+1}/{len(image_list)} 成功")
                except Exception as e:
                    print(f"处理图片 {i+1} 失败: {e}")

        # 处理音频
        audio_base64_list = []
        if audio_list and len(audio_list) > 0:
            for i, audio in enumerate(audio_list):
                try:
                    audio_base64 = self._process_audio_to_base64(audio)
                    if audio_base64:
                        audio_base64_list.append(audio_base64)
                        print(f"处理音频 {i+1}/{len(audio_list)} 成功")
                except Exception as e:
                    print(f"处理音频 {i+1} 失败: {e}")

        # 构建content
        content = []

        # 添加文本提示词
        content.append({
            "type": "text",
            "text": prompt
        })

        # 添加图片
        for img_base64 in image_base64_list:
            content.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64,{img_base64}"
                },
                "role": "reference_image"
            })

        # 添加音频
        for audio_base64 in audio_base64_list:
            content.append({
                "type": "audio_url",
                "audio_url": {
                    "url": f"data:audio/wav;base64,{audio_base64}"
                },
                "role": "reference_audio"
            })

        # 添加视频（来自视频聚合节点上传后的URL）
        if video_url_list and len(video_url_list) > 0:
            for i, video_url in enumerate(video_url_list):
                if video_url:
                    content.append({
                        "type": "video_url",
                        "video_url": {
                            "url": video_url
                        },
                        "role": "reference_video"
                    })
                    print(f"添加参考视频 {i+1}/{len(video_url_list)}: {video_url}")

        # 构建请求参数
        create_kwargs = {
            "model": model,
            "content": content,
            "ratio": ratio,
            "duration": duration,
            "watermark": False,
        }

        if resolution:
            create_kwargs["resolution"] = resolution

        if generate_audio:
            create_kwargs["generate_audio"] = True

        if seed != -1:
            create_kwargs["seed"] = seed

        try:
            print("----- Creating Seedance video generation task -----")
            print(f"Model: {model}")
            print(f"Resolution: {resolution}")
            print(f"Ratio: {ratio}")
            print(f"Duration: {duration}s")
            print(f"Generate Audio: {generate_audio}")
            print(f"Images: {len(image_base64_list)}")
            print(f"Audios: {len(audio_base64_list)}")
            video_count = len(video_url_list) if video_url_list else 0
            print(f"Videos: {video_count}")

            create_result = client.content_generation.tasks.create(**create_kwargs)
            task_id = create_result.id
            print(f"Task created successfully. Task ID: {task_id}")

        except Exception as e:
            error_msg = f"Failed to create task: {str(e)}"
            print(error_msg)
            return (error_msg, None, "", "")

        # 轮询任务状态
        video_url = None
        elapsed = 0

        print(f"----- Polling task status (interval: {poll_interval}s, max wait: {max_wait_time}s) -----")
        while elapsed < max_wait_time:
            try:
                get_result = client.content_generation.tasks.get(task_id=task_id)
                status = get_result.status

                if status == "succeeded":
                    print(f"----- Task succeeded -----")
                    video_url = get_result.content.video_url
                    print(f"Video URL: {video_url}")
                    break
                elif status == "failed":
                    error_msg = f"Task failed"
                    if hasattr(get_result, 'error') and get_result.error:
                        error_msg += f": {get_result.error}"
                    print(error_msg)
                    return (error_msg, None, "", "")
                else:
                    print(f"Current status: {status}, Retrying after {poll_interval} seconds... (elapsed: {elapsed}s)")
            except Exception as e:
                print(f"Query failed: {e}, Retrying...")

            time.sleep(poll_interval)
            elapsed += poll_interval

        if not video_url:
            error_msg = f"Timeout: Video generation did not complete within {max_wait_time} seconds"
            print(error_msg)
            return (error_msg, None, "", "")

        # 下载视频
        current_dir = os.path.dirname(os.path.abspath(__file__))
        comfyui_root = os.path.dirname(os.path.dirname(current_dir))
        output_dir = os.path.join(comfyui_root, "output", self.output_dir)
        os.makedirs(output_dir, exist_ok=True)

        video_filename = f"seedance_{int(time.time())}.mp4"
        video_path = os.path.join(output_dir, video_filename)

        if not download_video(video_url, video_path):
            error_msg = f"Failed to download video from: {video_url}"
            print(error_msg)
            return (error_msg, None, "", "")

        # 构建返回信息
        task_info = ""
        if hasattr(get_result, 'model'):
            task_info += f"模型: {get_result.model}\n"
        if hasattr(get_result, 'seed'):
            task_info += f"种子: {get_result.seed}\n"
        if hasattr(get_result, 'resolution'):
            task_info += f"分辨率: {get_result.resolution}\n"
        if hasattr(get_result, 'ratio'):
            task_info += f"比例: {get_result.ratio}\n"
        if hasattr(get_result, 'duration'):
            task_info += f"时长: {get_result.duration}秒\n"

        text_output = f"""Seedance 视频生成成功
任务ID: {task_id}
视频URL: {video_url}
本地保存路径: {video_path}

参数信息:
{task_info}
提示词: {prompt[:100]}{'...' if len(prompt) > 100 else ''}"""

        # 加载视频为ComfyUI VIDEO类型
        video_output = None
        if COMFY_VIDEO_AVAILABLE and os.path.exists(video_path):
            try:
                video_output = VideoEncode(video_path, fps=self.fps, video_codec='libx264', audio_codec='aac')
                video_output = video_output.load()
            except Exception as e:
                print(f"Failed to load video for ComfyUI: {e}")

        if video_output is None:
            print("Video saved to disk but could not be loaded as ComfyUI VIDEO type")

        return (text_output, video_output, video_url, video_path)


class DoubaoVideoUpload:
    """视频上传节点 - 带上传按钮，点击选择本地视频文件"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "video_path": ("STRING", {
                    "default": "",
                    "placeholder": "点击按钮上传视频...",
                    "tooltip": "视频文件路径（通过上传按钮选择）"
                }),
            }
        }

    RETURN_TYPES = ("VIDEO", "STRING")
    RETURN_NAMES = ("video", "video_path")
    FUNCTION = "load_video"
    CATEGORY = "Doubao/Seedance"

    def load_video(self, video_path: str) -> tuple:
        """加载视频文件"""
        if not video_path:
            raise ValueError("请先点击按钮上传视频文件")

        # 使用 folder_paths 获取完整路径（与 VideoHelperSuite 一致）
        if FOLDER_PATHS_AVAILABLE:
            full_path = folder_paths.get_annotated_filepath(video_path)
        else:
            full_path = os.path.join(os.getcwd(), "input", video_path)

        if not os.path.isfile(full_path):
            raise ValueError(f"视频文件不存在: {full_path}")

        print(f"[VideoUpload] 加载视频: {full_path}")

        # 创建 VIDEO 对象
        video_obj = VideoPathWrapper(full_path)

        return (video_obj, full_path)


class VideoPathWrapper:
    """简单的视频路径包装器，兼容 ComfyUI VIDEO 类型"""

    def __init__(self, path: str):
        self.path = path

    def get_stream_source(self):
        """返回视频文件路径"""
        return self.path

    def __repr__(self):
        return f"VideoPathWrapper({self.path})"


NODE_CLASS_MAPPINGS = {
    "Seedance Image Aggregator": DoubaoImageAggregator,
    "Seedance Audio Aggregator": DoubaoAudioAggregator,
    "Seedance Video Aggregator": DoubaoVideoAggregator,
    "Seedance Video Generator": DoubaoSeedanceVideoGenerator,
    "Seedance Video Upload": DoubaoVideoUpload,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "Seedance Image Aggregator": "Seedance2 图片聚合",
    "Seedance Audio Aggregator": "Seedance2 音频聚合",
    "Seedance Video Aggregator": "Seedance2 视频聚合",
    "Seedance Video Generator": "Seedance2 视频生成",
    "Seedance Video Upload": "Seedance2 视频上传",
}
