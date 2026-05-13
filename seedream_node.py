import os
import mimetypes
import wave
import uuid
import hashlib
import re
from urllib.parse import urlparse
import requests
import torch
import numpy as np
from PIL import Image
import io
import time
import folder_paths
from volcenginesdkarkruntime import Ark
from volcenginesdkarkruntime.types.images.images import SequentialImageGenerationOptions
from volcenginesdkarkruntime.types.images.images import ContentGenerationTool

class SeedreamImageGenerate:
    """
    A ComfyUI node for generating images using Volcengine Seedream API
    """
    
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "prompt": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "placeholder": "Enter your image generation prompt here..."
                }),
                "model": (["doubao-seedream-4-0-250828", "doubao-seedream-4-5-251128", "doubao-seedream-5-0-260128"], {
                    "default": "doubao-seedream-4-0-250828"
                }),
                "aspect_ratio": (["1:1", "2:3", "3:2", "4:3", "3:4", "16:9", "9:16", "10:16", "16:10", "21:9", "2K", "3K", "3.5K", "4K"], {
                    "default": "1:1"
                }),
                "sequential_image_generation": (["auto", "enabled", "disabled"], {
                    "default": "auto",
                    "tooltip": "顺序生成模式：auto=自动，enabled=启用，disabled=禁用"
                }),
                "max_images": ("INT", {
                    "default": 1,
                    "min": 1,
                    "max": 10,
                    "step": 1,
                    "tooltip": "sequential_image_generation_options.max_images - 最大生成图片数量（用于顺序生成）"
                }),
                "response_format": (["url", "b64_json"], {
                    "default": "url"
                }),
                "watermark": ("BOOLEAN", {
                    "default": False
                }),
                "stream": ("BOOLEAN", {
                    "default": False,
                    "tooltip": "流式传输模式 - 启用后与max_images配合可生成多张图片"
                }),
                "base_url": ("STRING", {
                    "default": "https://ark.cn-beijing.volces.com/api/v3"
                }),
                "use_local_images": ("BOOLEAN", {
                    "default": True,
                    "tooltip": "使用本地图像（Base64格式，官方支持）"
                }),
                "seed": ("INT", {
                    "default": 0,
                    "min": 0,
                    "max": 18446744073709551615,  # 支持64位整数
                    "step": 1
                }),
                "enable_auto_retry": ("BOOLEAN", {
                    "default": True,
                    "tooltip": "启用自动重试机制，处理云端工作流的异步执行问题"
                }),
            },
            "optional": {
                "image1": ("IMAGE",),
                "image2": ("IMAGE",),
                "image3": ("IMAGE",),
                "image4": ("IMAGE",),
                "image5": ("IMAGE",)
            }
        }
    
    RETURN_TYPES = ("IMAGE", "STRING")
    RETURN_NAMES = ("images", "text")
    OUTPUT_IS_LIST = (True, False)
    FUNCTION = "generate_images"
    CATEGORY = "image/generation"
    
    def __init__(self):
        self.client = None
        self.max_retries = 3
        self.retry_delay = 1.0  # 秒
    
    def tensor_to_pil(self, tensor):
        """Convert ComfyUI tensor to PIL Image"""
        # Convert tensor to numpy array
        i = 255. * tensor.cpu().numpy()
        img = Image.fromarray(np.clip(i, 0, 255).astype(np.uint8))
        return img
    
    def pil_to_tensor(self, pil_image):
        """Convert PIL Image to ComfyUI tensor"""
        img = np.array(pil_image).astype(np.float32) / 255.0
        return torch.from_numpy(img)[None,]
    
    def validate_input_data(self, image1, retry_count=0):
        """
        验证输入数据的完整性，支持重试机制处理云端工作流的异步特性
        """
        max_retries = 3
        
        # 基本验证
        if image1 is None:
            if retry_count < max_retries:
                print(f"输入验证失败 (尝试 {retry_count + 1}/{max_retries + 1}): image1 为 None，等待 {self.retry_delay} 秒后重试...")
                time.sleep(self.retry_delay)
                return False, "image1_none"
            else:
                raise ValueError("image1 参数是必需的，请确保上游节点已正确连接并执行完成")
        
        # 检查tensor类型
        if not isinstance(image1, torch.Tensor):
            if retry_count < max_retries:
                print(f"输入验证失败 (尝试 {retry_count + 1}/{max_retries + 1}): image1 类型错误 {type(image1)}，等待 {self.retry_delay} 秒后重试...")
                time.sleep(self.retry_delay)
                return False, "image1_type"
            else:
                raise ValueError(f"image1 必须是torch.Tensor类型，当前类型: {type(image1)}")
        
        # 检查tensor形状
        if len(image1.shape) < 3:
            if retry_count < max_retries:
                print(f"输入验证失败 (尝试 {retry_count + 1}/{max_retries + 1}): image1 形状无效 {image1.shape}，等待 {self.retry_delay} 秒后重试...")
                time.sleep(self.retry_delay)
                return False, "image1_shape"
            else:
                raise ValueError(f"image1 tensor形状无效: {image1.shape}，期望至少3维")
        
        # 检查tensor数据质量 - 避免全零或无效数据
        if torch.all(image1 == 0) or torch.isnan(image1).any():
            if retry_count < max_retries:
                print(f"输入验证失败 (尝试 {retry_count + 1}/{max_retries + 1}): image1 数据质量问题（全零或包含NaN），等待 {self.retry_delay} 秒后重试...")
                time.sleep(self.retry_delay)
                return False, "image1_quality"
            else:
                print("警告: image1 包含异常数据，但将继续执行...")
        
        print(f"✅ 输入验证通过: image1 形状 {image1.shape}, 数据类型 {image1.dtype}")
        return True, "success"
    
    def convert_image_to_supported_format(self, pil_image, use_local_images=False):
        """
        将本地图像转换为API支持的格式
        根据官方文档：支持Base64编码格式 data:image/<图片格式>;base64,<Base64编码>
        """
        try:
            if use_local_images:
                # 使用官方支持的Base64格式
                try:
                    import base64
                    
                    # 确保图像是RGB格式
                    if pil_image.mode != 'RGB':
                        pil_image = pil_image.convert('RGB')
                    
                    # 保存为PNG格式到内存
                    buffered = io.BytesIO()
                    pil_image.save(buffered, format="PNG")
                    img_bytes = buffered.getvalue()
                    
                    # 编码为Base64
                    img_base64 = base64.b64encode(img_bytes).decode('utf-8')
                    
                    # 按照官方文档格式：data:image/png;base64,<base64_image>
                    data_url = f"data:image/png;base64,{img_base64}"
                    
                    return data_url
                    
                except Exception as e:
                    # 转换失败时回退到示例图像
                    return self._get_example_image_url()
            
            # 默认模式：使用官方示例图像URL
            return self._get_example_image_url()
            
        except Exception as e:
            return self._get_example_image_url()
    
    def _get_example_image_url(self):
        """获取示例图像URL"""
        example_urls = [
            "https://ark-project.tos-cn-beijing.volces.com/doc_image/seedream4_imagesToimages_1.png",
            "https://ark-project.tos-cn-beijing.volces.com/doc_image/seedream4_imagesToimages_2.png"
        ]
        
        import random
        return random.choice(example_urls)
    
    def _get_additional_generate_params(self):
        """Hook for subclasses to inject extra parameters into the API call"""
        return {}
    
    def aspect_ratio_to_size(self, aspect_ratio):
        """Convert aspect ratio to size parameter"""
        ratio_map = {
            "1:1": "2048x2048",
            "4:3": "2304x1728", 
            "3:4": "1728x2304",
            "16:9": "2560x1440",
            "9:16": "1440x2560",
            "10:16": "2000x3200",
            "16:10": "3200x2000",
            "3:2": "2496x1664",
            "2:3": "1664x2496",
            #"2:3": "1040x1560",
            "21:9": "3024x1296",
            "2K": "2K",
            "3K": "2133x3200",
            "3.5K": "2933x4400",
            "4K": "4K"
        }
        return ratio_map.get(aspect_ratio, "2048x2048")
    
    def _resolve_size(self, size_input):
        """Resolve node size input into API size parameter"""
        return self.aspect_ratio_to_size(size_input)
    
    def _size_result_label(self):
        return "宽高比"
    
    def _raise_when_no_output_tensor(self):
        return False
    
    def download_image_from_url(self, url):
        """Download image from URL and convert to tensor"""
        try:
            response = requests.get(url)
            response.raise_for_status()
            image = Image.open(io.BytesIO(response.content))
            if image.mode != 'RGB':
                image = image.convert('RGB')
            return self.pil_to_tensor(image)
        except Exception as e:
            # Return a black placeholder image
            placeholder = Image.new('RGB', (512, 512), color='black')
            return self.pil_to_tensor(placeholder)
    
    def initialize_client(self, base_url):
        """Initialize the Ark client"""
        api_key = os.environ.get("ARK_API_KEY")
        
        if not api_key:
            raise ValueError("API Key is required. Please set ARK_API_KEY environment variable.")
        
        self.client = Ark(
            base_url=base_url,
            api_key=api_key.strip()
        )
    
    def generate_images(self, prompt, model, aspect_ratio, sequential_image_generation, 
                       max_images, response_format, watermark, stream, base_url, use_local_images, seed, enable_auto_retry,
                       image1=None, image2=None, image3=None, image4=None, image5=None):
        
        # 根据用户设置决定是否使用重试机制
        max_attempts = self.max_retries + 1 if enable_auto_retry else 1
        
        for retry_count in range(max_attempts):
            try:
                # 使用智能验证机制验证输入数据（如果image1存在的话）
                if image1 is not None:
                    is_valid, error_type = self.validate_input_data(image1, retry_count)
                    
                    if not is_valid:
                        if enable_auto_retry and retry_count < self.max_retries:
                            # 如果启用重试且还有重试机会，继续下一次循环
                            continue
                        else:
                            # 最终失败，让validate_input_data抛出异常
                            self.validate_input_data(image1, retry_count)
                
                # 验证通过，继续执行
                if retry_count > 0 and enable_auto_retry:
                    print(f"✅ 重试成功！开始执行图像生成 (尝试 {retry_count + 1}/{max_attempts})")
                    print("💡 提示：如果经常需要重试，建议在工作流中添加适当的延迟或确保上游节点完全执行后再触发此节点")
                else:
                    print(f"🚀 开始执行图像生成")
                    
                return self._execute_generation(prompt, model, aspect_ratio, sequential_image_generation, 
                                              max_images, response_format, watermark, stream, base_url, use_local_images, seed, enable_auto_retry,
                                              image1, image2, image3, image4, image5)
                
            except Exception as e:
                if enable_auto_retry and retry_count < self.max_retries:
                    print(f"执行失败 (尝试 {retry_count + 1}/{max_attempts}): {str(e)}")
                    print(f"等待 {self.retry_delay} 秒后重试...")
                    time.sleep(self.retry_delay)
                    continue
                else:
                    # 最后一次重试也失败了，或者没有启用重试，抛出异常
                    raise e
    
    def _execute_generation(self, prompt, model, aspect_ratio, sequential_image_generation, 
                           max_images, response_format, watermark, stream, base_url, use_local_images, seed, enable_auto_retry,
                           image1=None, image2=None, image3=None, image4=None, image5=None):
        """
        实际执行图像生成的核心逻辑
        """
        try:
            
            # 标准化seed参数 - 将大的seed值映射到有效范围内
            normalized_seed = seed
            if seed > 2147483647:
                # 使用模运算将大seed值映射到有效范围
                normalized_seed = seed % 2147483647
                print(f"原始seed值 {seed} 被标准化为 {normalized_seed}")
            
            # Initialize client
            self.initialize_client(base_url)
            
            # Note: normalized_seed parameter is available for workflow tracking but not sent to the API
            # The Volcengine Seedream API doesn't currently support seed parameter
            
            # Collect input images - 现在所有图片都是可选的，可以不提供图片
            input_images = []
            if image1 is not None:
                input_images.append(image1)
            if image2 is not None:
                input_images.append(image2)
            if image3 is not None:
                input_images.append(image3)
            if image4 is not None:
                input_images.append(image4)
            if image5 is not None:
                input_images.append(image5)
            
            # Convert input images to URLs
            image_urls = []
            
            for i, img_tensor in enumerate(input_images):
                # Convert tensor to PIL
                pil_img = self.tensor_to_pil(img_tensor.squeeze(0))
                # 转换为API支持的格式
                url = self.convert_image_to_supported_format(pil_img, use_local_images)
                image_urls.append(url)
                
            # Convert size input to API size parameter
            size = self._resolve_size(aspect_ratio)
            
            # Prepare generation options
            # 使用SDK的SequentialImageGenerationOptions类
            # 对应官方API: {"max_images": int}
            generation_options = SequentialImageGenerationOptions(max_images=max_images)
            print(f"🔄 顺序生成选项: max_images={max_images}")
            
            # Generate images - 根据是否有图片输入来决定参数
            generate_params = {
                "model": model,
                "prompt": prompt,
                "size": size,
                "sequential_image_generation": sequential_image_generation,
                "sequential_image_generation_options": generation_options,
                "response_format": response_format,
                "watermark": watermark,
                "stream": stream
            }
            
            # 只有在有图片输入时才添加image参数
            if image_urls:
                generate_params["image"] = image_urls
                print(f"📸 使用 {len(image_urls)} 张输入图片进行生成")
            else:
                print(f"🎨 文生图模式：仅使用提示词生成图片（无输入图片）")
            
            print(f"📤 发送API请求")
            print(f"   模型: {model}")
            print(f"   顺序生成: {sequential_image_generation}")
            print(f"   顺序生成选项: max_images={max_images}")
            print(f"   stream: {stream}")
            print(f"   图片输入数: {len(image_urls) if image_urls else 0}")
            
            # 打印API参数摘要（不打印完整参数，避免序列化问题）
            print(f"📋 API参数摘要:")
            print(f"   - model: {model}")
            print(f"   - size: {size}")
            print(f"   - response_format: {response_format}")
            print(f"   - watermark: {watermark}")
            print(f"   - stream: {stream}")
            print(f"   - 有图片输入: {len(image_urls) > 0 if image_urls else False}")
            
            extra_params = self._get_additional_generate_params()
            if extra_params:
                generate_params.update(extra_params)
                print(f"   - 额外参数: {list(extra_params.keys())}")
            
            images_response = self.client.images.generate(**generate_params)
            
            # 处理流式响应
            all_image_data = []
            event_count = 0  # 在外部初始化，用于错误报告
            if stream:
                print(f"🌊 流式响应模式，正在收集所有图片...")
                try:
                    # 根据官方示例，流式响应返回的是event对象迭代器
                    # event有type属性来区分不同的事件类型
                    for event in images_response:
                        event_count += 1
                        
                        # 跳过None事件
                        if event is None:
                            print(f"   📦 收到空event，跳过")
                            continue
                        
                        print(f"   📦 收到第 {event_count} 个event, 类型: {type(event)}, event.type: {getattr(event, 'type', 'N/A')}")
                        
                        # 检查event类型
                        if hasattr(event, 'type'):
                            if event.type == "image_generation.partial_failed":
                                # 部分生成失败
                                error_msg = getattr(event, 'error', 'Unknown error')
                                print(f"   ❌ 图片生成部分失败: {error_msg}")
                                if hasattr(event, 'error') and event.error is not None:
                                    if hasattr(event.error, 'code') and hasattr(event.error.code, 'equal'):
                                        if event.error.code.equal("InternalServiceError"):
                                            print(f"   🛑 内部服务错误，停止处理")
                                            break
                            
                            elif event.type == "image_generation.partial_succeeded":
                                # 部分生成成功 - 这是每张图片生成后的事件
                                if hasattr(event, 'error') and event.error is None:
                                    if hasattr(event, 'url') and event.url:
                                        # 收集图片URL
                                        all_image_data.append(event)
                                        size_info = getattr(event, 'size', 'unknown')
                                        url_preview = event.url[:60] + '...' if len(event.url) > 60 else event.url
                                        print(f"   ✅ 收到第 {len(all_image_data)} 张图片成功: Size={size_info}, URL={url_preview}")
                                    elif hasattr(event, 'b64_json') and event.b64_json:
                                        # Base64格式
                                        all_image_data.append(event)
                                        print(f"   ✅ 收到第 {len(all_image_data)} 张图片成功 (Base64格式)")
                            
                            elif event.type == "image_generation.completed":
                                # 所有图片生成完成
                                print(f"   🎉 所有图片生成完成!")
                                if hasattr(event, 'usage'):
                                    print(f"   📊 使用统计: {event.usage}")
                        else:
                            print(f"   ⚠️ Event没有type属性，尝试作为图片数据处理")
                            # 兼容旧格式：可能是直接的图片数据
                            if hasattr(event, 'url') and event.url:
                                all_image_data.append(event)
                                print(f"   ✅ 直接收集event为图片: {len(all_image_data)}")
                    
                    print(f"📊 流式响应完成，共收到 {event_count} 个event，收集 {len(all_image_data)} 张有效图片")
                except Exception as e:
                    print(f"❌ 处理流式响应时出错: {type(e).__name__}: {e}")
                    import traceback
                    traceback.print_exc()
                    raise
            else:
                # 非流式响应，直接使用data
                print(f"📦 非流式响应模式")
                print(f"   响应类型: {type(images_response)}")
                
                if hasattr(images_response, 'data'):
                    # 过滤有效图片数据
                    for img_data in images_response.data:
                        has_url = hasattr(img_data, 'url') and img_data.url is not None
                        has_b64 = hasattr(img_data, 'b64_json') and img_data.b64_json is not None
                        if has_url or has_b64:
                            all_image_data.append(img_data)
                    print(f"📊 非流式响应，返回 {len(all_image_data)} 张有效图片")
                else:
                    print(f"⚠️ 响应没有data属性")
            
            if not all_image_data:
                error_detail = f"API未返回任何图片数据\n"
                error_detail += f"  - stream模式: {stream}\n"
                if stream:
                    error_detail += f"  - 收到event数: {event_count}\n"
                error_detail += f"  - 响应类型: {type(images_response)}\n"
                error_detail += f"\n💡 可能的原因:\n"
                error_detail += f"  1. API返回格式与预期不符\n"
                error_detail += f"  2. 流式响应处理方式需要调整\n"
                error_detail += f"  3. API参数配置问题\n"
                error_detail += f"\n请查看上方的详细调试日志以确定具体原因"
                raise ValueError(error_detail)
            
            # Process generated images and collect information
            output_tensors = []
            result_info = []
            
            # Collect basic generation info
            result_info.append(f"🎨 生成信息:")
            result_info.append(f"📝 提示词: {prompt}")
            result_info.append(f"🔧 模型: {model}")
            result_info.append(f"📐 {self._size_result_label()}: {aspect_ratio}")
            result_info.append(f"🔄 顺序生成: {sequential_image_generation}")
            result_info.append(f"   └─ max_images: {max_images} (sequential_image_generation_options)")
            result_info.append(f"🖼️ 生成数量: {len(all_image_data)}")
            input_image_count = len([img for img in [image1, image2, image3, image4, image5] if img is not None])
            result_info.append(f"📊 输入图像: {input_image_count}张" + (" (文生图模式)" if input_image_count == 0 else " (图生图模式)"))
            result_info.append(f"🔄 本地图像模式: {'Base64编码' if use_local_images else '示例图像'}")
            result_info.append(f"🎲 种子值: {normalized_seed}" + (f" (原始: {seed})" if seed != normalized_seed else ""))
            result_info.append(f"⚡ 执行状态: 成功 (自动重试: {'启用' if enable_auto_retry else '禁用'})")
            result_info.append("")
            
            for i, image_data in enumerate(all_image_data):
                result_info.append(f"📷 图像 {i+1}:")
                
                # 安全获取URL和尺寸
                url = getattr(image_data, 'url', None)
                size = getattr(image_data, 'size', None)
                
                result_info.append(f"   🔗 URL: {url if url else 'N/A'}")
                result_info.append(f"   📏 尺寸: {size if size else 'N/A'}")
                
                # Add any additional metadata if available
                if hasattr(image_data, 'revised_prompt') and image_data.revised_prompt:
                    result_info.append(f"   ✏️ 修订提示词: {image_data.revised_prompt}")
                
                if hasattr(image_data, 'finish_reason') and image_data.finish_reason:
                    result_info.append(f"   ✅ 完成原因: {image_data.finish_reason}")
                
                if response_format == "url":
                    # Download image from URL
                    if url and url != 'N/A':
                        tensor = self.download_image_from_url(url)
                        output_tensors.append(tensor)
                    else:
                        print(f"⚠️ 图像 {i+1} 没有有效URL，跳过下载")
                else:  # b64_json
                    # Handle base64 encoded image
                    if hasattr(image_data, 'b64_json') and image_data.b64_json:
                        import base64
                        image_data_b64 = image_data.b64_json
                        image_bytes = base64.b64decode(image_data_b64)
                        image = Image.open(io.BytesIO(image_bytes))
                        if image.mode != 'RGB':
                            image = image.convert('RGB')
                        tensor = self.pil_to_tensor(image)
                        output_tensors.append(tensor)
                    else:
                        print(f"⚠️ 图像 {i+1} 没有有效的b64_json数据，跳过处理")
                
                result_info.append("")
            
            # Add generation parameters info
            result_info.append("⚙️ 生成参数:")
            result_info.append(f"   🎯 响应格式: {response_format}")
            result_info.append(f"   💧 水印: {'是' if watermark else '否'}")
            result_info.append(f"   🌊 流式传输: {'是' if stream else '否'}")
            result_info.append(f"   🌐 API地址: {base_url}")
            
            if not output_tensors:
                if self._raise_when_no_output_tensor():
                    raise ValueError("图片生成失败：API 返回了图片数据，但未能解析或下载出有效图像")
                # Return a placeholder if no images generated
                placeholder = Image.new('RGB', (512, 512), color='black')
                output_tensors = [self.pil_to_tensor(placeholder)]
                result_info.append("⚠️ 未生成图像，返回占位符")
            
            # Join all info into a single text output
            text_output = "\n".join(result_info)
            
            return (output_tensors, text_output)
            
        except Exception as e:
            error_msg = str(e)
            
            # 确保normalized_seed在错误处理时也可用
            normalized_seed = seed
            if seed > 2147483647:
                normalized_seed = seed % 2147483647
            
            # Return a placeholder error image with error text
            error_img = Image.new('RGB', (512, 512), color='red')
            
            # Create detailed error text output with specific troubleshooting
            error_text_parts = [
                "❌ 图像生成失败",
                "",
                f"🔍 错误信息: {error_msg}",
                ""
            ]
            
            # 根据错误类型提供具体的解决建议
            if "image1 参数是必需的" in error_msg or "至少需要提供一张输入图片" in error_msg:
                error_text_parts.extend([
                    "🚨 输入图像问题:",
                    "   • image1 输入未连接或上游节点未执行完成",
                    "   • 请确保LoadImage或其他图像生成节点已正确连接",
                    "   • 建议等待上游节点完全执行后再运行此节点",
                    "   • 如果使用API调用，请确保所有依赖节点按正确顺序执行",
                    ""
                ])
            elif "torch.Tensor" in error_msg:
                error_text_parts.extend([
                    "🚨 数据类型问题:",
                    "   • 输入的image1不是有效的图像tensor",
                    "   • 请检查上游节点是否正确输出图像数据",
                    "   • 确保连接的是图像输出端口，而不是其他类型的输出",
                    ""
                ])
            elif "Invalid image file" in error_msg:
                error_text_parts.extend([
                    "🚨 图像文件问题:",
                    "   • 上游LoadImage节点的图像文件无效或不存在",
                    "   • 常见原因:",
                    "     - 文件路径格式错误（如：client:syai-prod/...）",
                    "     - 临时文件还未生成完成",
                    "     - 文件权限或网络问题",
                    "     - 工作流执行顺序问题",
                    "   • 解决方案:",
                    "     1. 检查LoadImage节点的输入路径是否正确",
                    "     2. 确保使用本地文件路径而非URL格式",
                    "     3. 等待上游节点完全执行后再运行",
                    "     4. 检查文件是否存在且可读",
                    ""
                ])
            elif "API Key" in error_msg:
                error_text_parts.extend([
                    "🚨 API配置问题:",
                    "   • ARK_API_KEY 环境变量未设置或无效",
                    "   • 请设置环境变量: export ARK_API_KEY='your_api_key'",
                    "   • 确保API Key有效且有足够的配额",
                    ""
                ])
            elif "bigger than max" in error_msg and "seed" in error_msg:
                error_text_parts.extend([
                    "🚨 Seed值溢出问题:",
                    f"   • 原始seed值 {seed} 超过了系统支持的最大值",
                    f"   • 已自动标准化为: {normalized_seed}",
                    "   • 这不会影响图像生成质量，只是用于工作流跟踪",
                    "   • 建议使用较小的seed值以避免此警告",
                    ""
                ])
            
            error_text_parts.extend([
                f"📝 提示词: {prompt}",
                f"🔧 模型: {model}",
                f"📐 {self._size_result_label()}: {aspect_ratio}",
                f"🔄 顺序生成: {sequential_image_generation}",
                f"🖼️ 最大图像数: {max_images}",
                f"🌐 API地址: {base_url}",
                f"🧪 使用本地图像: {'是' if use_local_images else '否'}",
                f"🎲 种子值: {normalized_seed}" + (f" (原始: {seed})" if seed != normalized_seed else ""),
                "",
                "💡 故障排除步骤:",
                "   1. 检查所有节点连接是否正确",
                "   2. 确保上游节点已完全执行",
                "   3. 验证API Key和网络连接",
                "   4. 查看ComfyUI控制台获取详细日志"
            ])
            
            error_text = "\n".join(error_text_parts)
            
            # 打印详细错误信息到控制台以便调试
            print(f"SeedreamImageGenerate 错误详情:")
            print(f"  错误类型: {type(e).__name__}")
            print(f"  错误信息: {error_msg}")
            print(f"  image1 类型: {type(image1) if 'image1' in locals() else 'undefined'}")
            if 'image1' in locals() and image1 is not None:
                print(f"  image1 形状: {getattr(image1, 'shape', 'N/A')}")
            
            # 抛出异常让ComfyUI显示报错弹窗，不输出红图
            raise RuntimeError(error_text)

class SeedreamImageGenerateV2(SeedreamImageGenerate):
    """
    Seedream image generation node using direct resolution input.
    """
    
    MIN_TOTAL_PIXELS = 2560 * 1440
    MAX_TOTAL_PIXELS = 4096 * 4096
    MIN_ASPECT_RATIO = 1 / 16
    MAX_ASPECT_RATIO = 16
    
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "prompt": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "placeholder": "Enter your image generation prompt here..."
                }),
                "model": (["doubao-seedream-4-0-250828", "doubao-seedream-4-5-251128", "doubao-seedream-5-0-260128"], {
                    "default": "doubao-seedream-4-0-250828"
                }),
                "width": ("INT", {
                    "default": 2048,
                    "min": 1,
                    "max": 4096,
                    "step": 1,
                    "tooltip": "生成图片宽度。最终会与height组合成 widthxheight 传给API"
                }),
                "height": ("INT", {
                    "default": 2048,
                    "min": 1,
                    "max": 4096,
                    "step": 1,
                    "tooltip": "生成图片高度。总像素需在2560x1440到4096x4096之间，宽高比需在1/16到16之间"
                }),
                "sequential_image_generation": (["auto", "enabled", "disabled"], {
                    "default": "auto",
                    "tooltip": "顺序生成模式：auto=自动，enabled=启用，disabled=禁用"
                }),
                "max_images": ("INT", {
                    "default": 1,
                    "min": 1,
                    "max": 10,
                    "step": 1,
                    "tooltip": "sequential_image_generation_options.max_images - 最大生成图片数量（用于顺序生成）"
                }),
                "response_format": (["url", "b64_json"], {
                    "default": "url"
                }),
                "watermark": ("BOOLEAN", {
                    "default": False
                }),
                "stream": ("BOOLEAN", {
                    "default": False,
                    "tooltip": "流式传输模式 - 启用后与max_images配合可生成多张图片"
                }),
                "base_url": ("STRING", {
                    "default": "https://ark.cn-beijing.volces.com/api/v3"
                }),
                "use_local_images": ("BOOLEAN", {
                    "default": True,
                    "tooltip": "使用本地图像（Base64格式，官方支持）"
                }),
                "seed": ("INT", {
                    "default": 0,
                    "min": 0,
                    "max": 18446744073709551615,
                    "step": 1
                }),
                "enable_auto_retry": ("BOOLEAN", {
                    "default": True,
                    "tooltip": "启用自动重试机制，处理云端工作流的异步执行问题"
                }),
            },
            "optional": {
                "image1": ("IMAGE",),
                "image2": ("IMAGE",),
                "image3": ("IMAGE",),
                "image4": ("IMAGE",),
                "image5": ("IMAGE",)
            }
        }
    
    FUNCTION = "generate_images_v2"
    
    def _size_result_label(self):
        return "分辨率"
    
    def _raise_when_no_output_tensor(self):
        return True
    
    def _resolve_size(self, resolution):
        normalized = str(resolution).strip()
        match = re.fullmatch(r"(\d+)\s*[xX×]\s*(\d+)", normalized)
        if not match:
            raise ValueError("resolution格式无效，内部组合值应为 2560x1440 这样的 宽x高 格式")
        
        width = int(match.group(1))
        height = int(match.group(2))
        if width <= 0 or height <= 0:
            raise ValueError(f"resolution尺寸必须为正整数，当前为 {width}x{height}")
        
        total_pixels = width * height
        if total_pixels < self.MIN_TOTAL_PIXELS or total_pixels > self.MAX_TOTAL_PIXELS:
            raise ValueError(
                f"resolution总像素需在 {self.MIN_TOTAL_PIXELS} 到 {self.MAX_TOTAL_PIXELS} 之间，"
                f"当前 {width}x{height}={total_pixels}"
            )
        
        aspect_ratio = width / height
        if aspect_ratio < self.MIN_ASPECT_RATIO or aspect_ratio > self.MAX_ASPECT_RATIO:
            raise ValueError(
                f"resolution宽高比需在 1/16 到 16 之间，当前 {width}:{height}={aspect_ratio:.4f}"
            )
        
        return f"{width}x{height}"
    
    def download_image_from_url(self, url):
        try:
            response = requests.get(url)
            response.raise_for_status()
            image = Image.open(io.BytesIO(response.content))
            if image.mode != 'RGB':
                image = image.convert('RGB')
            return self.pil_to_tensor(image)
        except Exception as e:
            raise ValueError(f"图片生成失败：无法下载或解析生成图片 {url}: {e}") from e
    
    def generate_images_v2(self, prompt, model, width, height,
                           sequential_image_generation, max_images, response_format,
                           watermark, stream, base_url, use_local_images, seed,
                           enable_auto_retry,
                           image1=None, image2=None, image3=None, image4=None, image5=None):
        resolution = f"{width}x{height}"
        return super().generate_images(
            prompt, model, resolution,
            sequential_image_generation, max_images, response_format,
            watermark, stream, base_url, use_local_images, seed, enable_auto_retry,
            image1, image2, image3, image4, image5
        )

class SeedreamImageGenerateWithWebSearch(SeedreamImageGenerate):
    """
    A ComfyUI node for generating images using Volcengine Seedream API with optional web search.
    Model is fixed to doubao-seedream-5-0-260128 which supports web search tool.
    """
    
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "prompt": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "placeholder": "Enter your image generation prompt here..."
                }),
                "enable_web_search": ("BOOLEAN", {
                    "default": True,
                    "tooltip": "启用网络搜索 - 开启后联网搜索实时信息辅助图像生成"
                }),
                "aspect_ratio": (["1:1", "2:3", "3:2", "4:3", "3:4", "16:9", "9:16", "10:16", "16:10", "21:9", "2K", "3K", "3.5K", "4K"], {
                    "default": "1:1"
                }),
                "sequential_image_generation": (["auto", "enabled", "disabled"], {
                    "default": "auto",
                    "tooltip": "顺序生成模式：auto=自动，enabled=启用，disabled=禁用"
                }),
                "max_images": ("INT", {
                    "default": 1,
                    "min": 1,
                    "max": 10,
                    "step": 1,
                    "tooltip": "sequential_image_generation_options.max_images - 最大生成图片数量（用于顺序生成）"
                }),
                "response_format": (["url", "b64_json"], {
                    "default": "url"
                }),
                "watermark": ("BOOLEAN", {
                    "default": False
                }),
                "stream": ("BOOLEAN", {
                    "default": False,
                    "tooltip": "流式传输模式 - 启用后与max_images配合可生成多张图片"
                }),
                "base_url": ("STRING", {
                    "default": "https://ark.cn-beijing.volces.com/api/v3"
                }),
                "use_local_images": ("BOOLEAN", {
                    "default": True,
                    "tooltip": "使用本地图像（Base64格式，官方支持）"
                }),
                "seed": ("INT", {
                    "default": 0,
                    "min": 0,
                    "max": 18446744073709551615,
                    "step": 1
                }),
                "enable_auto_retry": ("BOOLEAN", {
                    "default": True,
                    "tooltip": "启用自动重试机制，处理云端工作流的异步执行问题"
                }),
            },
            "optional": {
                "image1": ("IMAGE",),
                "image2": ("IMAGE",),
                "image3": ("IMAGE",),
                "image4": ("IMAGE",),
                "image5": ("IMAGE",)
            }
        }
    
    FUNCTION = "generate_images_with_web_search"
    
    def generate_images_with_web_search(self, prompt, enable_web_search, aspect_ratio,
                                        sequential_image_generation, max_images, response_format,
                                        watermark, stream, base_url, use_local_images, seed,
                                        enable_auto_retry,
                                        image1=None, image2=None, image3=None, image4=None, image5=None):
        self._enable_web_search = enable_web_search
        return super().generate_images(
            prompt, "doubao-seedream-5-0-260128", aspect_ratio,
            sequential_image_generation, max_images, response_format,
            watermark, stream, base_url, use_local_images, seed, enable_auto_retry,
            image1, image2, image3, image4, image5
        )
    
    def _get_additional_generate_params(self):
        if getattr(self, '_enable_web_search', False):
            return {"tools": [ContentGenerationTool(type="web_search")]}
        return {}


class SeedanceVideoGenerate:
    """
    A ComfyUI node for generating videos using Volcengine Seedance API.
    Uses async task creation + polling workflow.
    """
    
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "prompt": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "placeholder": "描述要生成的视频内容..."
                }),
                "model": (["doubao-seedance-2-0-260128"], {
                    "default": "doubao-seedance-2-0-260128"
                }),
                "duration": ("INT", {
                    "default": 5,
                    "min": 1,
                    "max": 10,
                    "step": 1,
                    "tooltip": "视频时长（秒），对应 --dur 参数"
                }),
                "watermark": ("BOOLEAN", {
                    "default": False,
                    "tooltip": "是否添加水印，对应 --wm 参数"
                }),
                "base_url": ("STRING", {
                    "default": "https://ark.cn-beijing.volces.com/api/v3"
                }),
                "poll_interval": ("INT", {
                    "default": 3,
                    "min": 1,
                    "max": 30,
                    "step": 1,
                    "tooltip": "任务状态轮询间隔（秒）"
                }),
                "max_wait_time": ("INT", {
                    "default": 600,
                    "min": 60,
                    "max": 3600,
                    "step": 30,
                    "tooltip": "最大等待时间（秒），超时后任务将被放弃"
                }),
            },
            "optional": {
                "image": ("IMAGE", {"tooltip": "可选图片输入，用于图生视频"}),
                "video": ("VIDEO", {"tooltip": "保留输入口。当前 Seedance 参考视频要求公网 URL，本地 VIDEO 输入不会直接上传，请优先使用 video_url"}),
                "video_url": ("STRING", {
                    "default": "",
                    "placeholder": "https://example.com/reference.mp4",
                    "tooltip": "参考视频公网 URL。当前按官方要求仅建议使用 .mp4 / .mov 的可访问 web url"
                }),
                "audio": ("AUDIO", {"tooltip": "可选音频输入，用于为视频添加音频驱动；可连接 ComfyUI 的 LoadAudio / GetVideoComponents 等节点输出"}),
            }
        }
    
    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("video_url", "text")
    FUNCTION = "generate_video"
    CATEGORY = "video/generation"
    
    def __init__(self):
        self.client = None
    
    def initialize_client(self, base_url):
        api_key = os.environ.get("ARK_API_KEY")
        if not api_key:
            raise ValueError("API Key is required. Please set ARK_API_KEY environment variable.")
        self.client = Ark(base_url=base_url, api_key=api_key.strip())
    
    def tensor_to_pil(self, tensor):
        i = 255. * tensor.cpu().numpy()
        img = Image.fromarray(np.clip(i, 0, 255).astype(np.uint8))
        return img
    
    def image_to_base64_url(self, pil_image):
        import base64
        if pil_image.mode != 'RGB':
            pil_image = pil_image.convert('RGB')
        buffered = io.BytesIO()
        pil_image.save(buffered, format="PNG")
        img_base64 = base64.b64encode(buffered.getvalue()).decode('utf-8')
        return f"data:image/png;base64,{img_base64}"
    
    def file_to_base64_url(self, file_path, media_type):
        """Convert a local file to a base64 data URL. media_type example: 'video/mp4', 'audio/wav'"""
        import base64
        with open(file_path, 'rb') as f:
            data = f.read()
        b64 = base64.b64encode(data).decode('utf-8')
        return f"data:{media_type};base64,{b64}"

    def bytes_to_base64_url(self, data, media_type):
        import base64
        b64 = base64.b64encode(data).decode('utf-8')
        return f"data:{media_type};base64,{b64}"
    
    def _detect_mime_type(self, file_path, category):
        """Detect MIME type from file extension"""
        guessed_type, _ = mimetypes.guess_type(file_path)
        if guessed_type and guessed_type.startswith(f"{category}/"):
            return guessed_type

        ext = os.path.splitext(file_path)[1].lower()
        mime_maps = {
            "video": {
                '.mp4': 'video/mp4', '.webm': 'video/webm', '.avi': 'video/x-msvideo',
                '.mov': 'video/quicktime', '.mkv': 'video/x-matroska', '.flv': 'video/x-flv',
            },
            "audio": {
                '.mp3': 'audio/mpeg', '.wav': 'audio/wav', '.ogg': 'audio/ogg',
                '.flac': 'audio/flac', '.aac': 'audio/aac', '.m4a': 'audio/mp4',
            },
        }
        return mime_maps.get(category, {}).get(ext, f'{category}/mp4' if category == 'video' else f'{category}/mpeg')

    def _video_input_to_media_url(self, video):
        if video is None:
            return None

        raise ValueError(
            "Seedance 当前要求 reference_video 必须是公网可访问的 http(s) URL，"
            "不能直接使用 ComfyUI 本地 VIDEO 输入。请改用 video_url 参数填写公开视频地址。"
        )

    def _resolve_reference_video_url(self, video_url):
        if video_url is None:
            return None

        normalized = str(video_url).strip()
        if not normalized:
            return None

        if normalized.startswith(("http://", "https://")):
            parsed = urlparse(normalized)
            path = parsed.path.lower()
            if not path.endswith((".mp4", ".mov")):
                raise ValueError("video_url 当前仅支持 .mp4 或 .mov 的公网地址")
            return normalized

        raise ValueError("video_url 必须是公网可访问的 http(s) 地址，例如 https://example.com/reference.mp4")

    def _validate_audio_constraints(self, waveform, sample_rate):
        channels = waveform.shape[0]
        num_samples = waveform.shape[1]
        duration_seconds = num_samples / float(sample_rate)

        if duration_seconds < 2 or duration_seconds > 15:
            raise ValueError(
                f"AUDIO 单段时长需在 2-15 秒之间，当前约为 {duration_seconds:.2f} 秒"
            )

        estimated_wav_bytes = num_samples * channels * 2 + 44
        estimated_wav_mb = estimated_wav_bytes / (1024 * 1024)
        if estimated_wav_mb > 15:
            raise ValueError(
                f"AUDIO 估算大小约 {estimated_wav_mb:.2f} MB，超过单段 15 MB 限制"
            )

        return duration_seconds, estimated_wav_mb

    def _audio_input_to_media_url(self, audio):
        if audio is None:
            return None

        if not isinstance(audio, dict):
            raise ValueError("audio 输入无法解析，请确认连接的是有效的 ComfyUI AUDIO 类型输出")

        waveform = audio.get("waveform")
        sample_rate = audio.get("sample_rate")
        if waveform is None or sample_rate is None:
            raise ValueError("AUDIO 输入缺少 waveform 或 sample_rate")

        if not isinstance(waveform, torch.Tensor):
            waveform = torch.tensor(waveform)

        waveform = waveform.detach().cpu()
        if waveform.ndim == 3:
            waveform = waveform[0]
        elif waveform.ndim == 1:
            waveform = waveform.unsqueeze(0)

        if waveform.ndim != 2:
            raise ValueError(f"AUDIO waveform 维度不正确: {tuple(waveform.shape)}")

        waveform = waveform.clamp(-1.0, 1.0)
        duration_seconds, estimated_wav_mb = self._validate_audio_constraints(waveform, sample_rate)
        pcm16 = (waveform.numpy().T * 32767.0).astype(np.int16)

        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav_file:
            wav_file.setnchannels(pcm16.shape[1] if pcm16.ndim == 2 else 1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(int(sample_rate))
            wav_file.writeframes(pcm16.tobytes())

        print(f"   🔊 读取AUDIO输入: {pcm16.shape[0]} samples @ {sample_rate}Hz, 时长约 {duration_seconds:.2f} 秒, 估算 {estimated_wav_mb:.2f} MB")
        return self.bytes_to_base64_url(buffer.getvalue(), "audio/wav")
    
    def _extract_video_url(self, result):
        """Extract video URL from task result based on actual API response format:
        {"content": {"video_url": "https://..."}, ...}
        """
        if hasattr(result, 'content') and result.content:
            content = result.content
            # content is an object with video_url attribute
            if hasattr(content, 'video_url') and content.video_url:
                return content.video_url
            # content is a dict with video_url key
            if isinstance(content, dict) and content.get('video_url'):
                return content['video_url']
        
        # Fallback: direct video_url on result
        if hasattr(result, 'video_url') and result.video_url:
            return result.video_url
        
        return ""
    
    def _extract_result_metadata(self, result):
        """Extract additional metadata from task result"""
        meta = {}
        for field in ('seed', 'resolution', 'ratio', 'duration', 'framespersecond'):
            val = getattr(result, field, None)
            if val is not None:
                meta[field] = val
        if hasattr(result, 'usage') and result.usage:
            usage = result.usage
            meta['total_tokens'] = getattr(usage, 'total_tokens', None)
        return meta
    
    def _download_video(self, video_url, task_id):
        """Download video from URL to ComfyUI temp directory for pipeline passthrough"""
        temp_dir = folder_paths.get_temp_directory()
        filename = f"seedance_{task_id}_{int(time.time())}.mp4"
        file_path = os.path.join(temp_dir, filename)
        
        print(f"📥 正在下载视频: {video_url[:80]}...")
        response = requests.get(video_url, stream=True)
        response.raise_for_status()
        
        total_size = int(response.headers.get('content-length', 0))
        downloaded = 0
        
        with open(file_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
                downloaded += len(chunk)
                if total_size > 0 and (downloaded * 100 // total_size) % 20 == 0:
                    print(f"   下载进度: {downloaded * 100 // total_size}%")
        
        file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
        print(f"✅ 视频已下载到临时目录: {file_path} ({file_size_mb:.1f} MB)")
        return file_path
    
    def generate_video(self, prompt, model, duration, watermark, base_url,
                       poll_interval, max_wait_time, image=None, video=None, video_url="", audio=None):
        self.initialize_client(base_url)
        
        wm_str = "true" if watermark else "false"
        full_prompt = f"{prompt} --wm {wm_str} --dur {duration}"
        
        content = []
        input_modes = []
        reference_video_url = self._resolve_reference_video_url(video_url)
        use_reference_mode = (reference_video_url is not None) or (video is not None) or (audio is not None)
        
        if image is not None:
            pil_img = self.tensor_to_pil(image.squeeze(0))
            img_url = self.image_to_base64_url(pil_img)
            image_item = {"type": "image_url", "image_url": {"url": img_url}}
            if use_reference_mode:
                image_item["role"] = "reference_image"
            content.append(image_item)
            input_modes.append("图片")
            print(f"📸 使用输入图片")
        
        video_media_url = reference_video_url
        if not video_media_url and video is not None:
            video_media_url = self._video_input_to_media_url(video)
        if video_media_url:
            content.append({
                "type": "video_url",
                "video_url": {"url": video_media_url},
                "role": "reference_video"
            })
            input_modes.append("视频")
            print(f"🎥 使用输入视频")
        
        audio_media_url = self._audio_input_to_media_url(audio)
        if audio_media_url:
            content.append({
                "type": "audio_url",
                "audio_url": {"url": audio_media_url},
                "role": "reference_audio"
            })
            input_modes.append("音频")
            print(f"🔊 使用输入音频")
        
        content.append({"type": "text", "text": full_prompt})
        input_modes.append("文字")
        
        mode_desc = "纯文生视频" if len(input_modes) == 1 else f"多模态生成({'+'.join(input_modes)})"
        
        print(f"🎬 创建视频生成任务")
        print(f"   模式: {mode_desc}")
        print(f"   模型: {model}")
        print(f"   提示词: {prompt}")
        print(f"   完整提示: {full_prompt}")
        print(f"   时长: {duration}秒")
        print(f"   水印: {'是' if watermark else '否'}")
        
        create_result = self.client.content_generation.tasks.create(
            model=model,
            content=content
        )
        
        task_id = create_result.id
        print(f"   任务ID: {task_id}")
        print(f"🔄 开始轮询任务状态 (间隔 {poll_interval}秒, 最大等待 {max_wait_time}秒)")
        
        elapsed = 0
        while elapsed < max_wait_time:
            get_result = self.client.content_generation.tasks.get(task_id=task_id)
            status = get_result.status
            
            if status == "succeeded":
                print(f"✅ 视频生成成功! (耗时约 {elapsed}秒)")
                print(f"   完整响应: {get_result}")
                
                video_url = self._extract_video_url(get_result)
                if not video_url:
                    raise RuntimeError(f"视频生成成功但未能提取视频URL，任务ID: {task_id}，请查看控制台完整响应")
                
                meta = self._extract_result_metadata(get_result)
                # video_file_path = self._download_video(video_url, task_id)
                
                result_info = [
                    f"🎬 视频生成信息:",
                    f"📝 提示词: {prompt}",
                    f"🔧 模型: {model}",
                    f"🎯 模式: {mode_desc}",
                    f"⏱️ 时长: {meta.get('duration', duration)}秒",
                    f"💧 水印: {'是' if watermark else '否'}",
                    f"🆔 任务ID: {task_id}",
                    f"⏳ 耗时: 约{elapsed}秒",
                ]
                if meta.get('resolution'):
                    result_info.append(f"📺 分辨率: {meta['resolution']}")
                if meta.get('ratio'):
                    result_info.append(f"📐 宽高比: {meta['ratio']}")
                if meta.get('framespersecond'):
                    result_info.append(f"🎞️ 帧率: {meta['framespersecond']}fps")
                if meta.get('seed') is not None:
                    result_info.append(f"🎲 种子值: {meta['seed']}")
                if meta.get('total_tokens') is not None:
                    result_info.append(f"📊 Token消耗: {meta['total_tokens']}")
                result_info.append(f"🔗 视频URL: {video_url}")
                result_info.append(f"⚡ 状态: 成功")
                
                return (video_url, "\n".join(result_info))
            
            elif status == "failed":
                error_msg = getattr(get_result, 'error', 'Unknown error')
                raise RuntimeError(f"视频生成失败 (任务ID: {task_id}): {error_msg}")
            
            else:
                print(f"   当前状态: {status}，{poll_interval}秒后重试... (已等待 {elapsed}秒)")
                time.sleep(poll_interval)
                elapsed += poll_interval
        
        raise TimeoutError(f"视频生成超时 (任务ID: {task_id})，已等待 {max_wait_time}秒，可增大 max_wait_time 参数后重试")


class TOSUploadVideoURL:
    """
    Upload a local ComfyUI VIDEO or file path to Volcengine TOS and output a pre-signed URL.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
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
            "optional": {
                "video": ("VIDEO", {
                    "tooltip": "可连接 LoadVideo / CreateVideo 等节点输出"
                }),
                "file_path": ("STRING", {
                    "default": "",
                    "placeholder": "/path/to/local/video.mp4",
                    "tooltip": "本地视频路径。若同时提供 video 与 file_path，则优先使用 file_path"
                }),
            }
        }

    RETURN_TYPES = ("STRING", "STRING", "BOOLEAN", "STRING")
    RETURN_NAMES = ("url", "object_key", "is_reused", "text")
    FUNCTION = "upload_video"
    CATEGORY = "video/upload"

    def _import_tos(self):
        try:
            import tos
            return tos
        except ImportError as e:
            raise ImportError(
                "未安装 TOS Python SDK。请先执行 `pip install tos`，或安装更新后的 requirements.txt 依赖。"
            ) from e

    def _initialize_tos_client(self, endpoint, region):
        tos = self._import_tos()
        access_key = os.environ.get("TOS_ACCESS_KEY")
        secret_key = os.environ.get("TOS_SECRET_KEY")

        if not access_key or not secret_key:
            raise ValueError("请先设置环境变量 TOS_ACCESS_KEY 和 TOS_SECRET_KEY")

        return tos.TosClientV2(access_key.strip(), secret_key.strip(), endpoint.strip(), region.strip())

    def _normalize_file_path(self, file_path):
        if file_path is None:
            return ""
        return os.path.expanduser(str(file_path).strip().strip('"').strip("'"))

    def _resolve_video_source(self, video=None, file_path=""):
        normalized_path = self._normalize_file_path(file_path)
        if normalized_path:
            if not os.path.isfile(normalized_path):
                raise ValueError(f"file_path 不存在: {normalized_path}")
            return {
                "kind": "path",
                "path": normalized_path,
                "filename": os.path.basename(normalized_path),
            }

        if video is None:
            raise ValueError("请至少提供一个输入来源：video 或 file_path")

        if hasattr(video, "get_stream_source"):
            stream_source = video.get_stream_source()
            if isinstance(stream_source, str) and os.path.isfile(stream_source):
                return {
                    "kind": "path",
                    "path": stream_source,
                    "filename": os.path.basename(stream_source),
                }
            if hasattr(stream_source, "seek"):
                stream_source.seek(0)
            if hasattr(stream_source, "read"):
                return {
                    "kind": "stream",
                    "stream": stream_source,
                    "filename": "video.mp4",
                }

        raise ValueError("无法从 VIDEO 输入中读取本地文件或字节流，请改用 LoadVideo 或直接填写 file_path")

    def _validate_video_filename(self, filename):
        ext = os.path.splitext(filename)[1].lower()
        if ext not in (".mp4", ".mov"):
            raise ValueError(f"当前仅支持上传 .mp4 或 .mov，检测到: {ext or '无扩展名'}")
        return ext

    def _build_object_key(self, object_prefix, filename, content_hash=None):
        prefix = (object_prefix or "").strip().strip("/")
        name, ext = os.path.splitext(os.path.basename(filename))
        safe_name = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in name).strip("_") or "video"
        if content_hash:
            object_name = f"{safe_name}_{content_hash[:16]}{ext.lower()}"
        else:
            object_name = f"{safe_name}_{uuid.uuid4().hex[:12]}{ext.lower()}"
        return f"{prefix}/{object_name}" if prefix else object_name

    def _hash_bytes(self, data):
        return hashlib.sha256(data).hexdigest()

    def _object_exists(self, client, bucket, object_key):
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

    def upload_video(self, bucket, endpoint, region, expires_seconds, reuse_existing, object_prefix, video=None, file_path=""):
        client = self._initialize_tos_client(endpoint, region)
        source = self._resolve_video_source(video=video, file_path=file_path)
        ext = self._validate_video_filename(source["filename"])
        content_type = mimetypes.guess_type(source["filename"])[0] or ("video/mp4" if ext == ".mp4" else "video/quicktime")

        if source["kind"] == "path":
            file_size_bytes = os.path.getsize(source["path"])
            with open(source["path"], "rb") as f:
                data = f.read()
        else:
            stream = source["stream"]
            data = stream.read()
            file_size_bytes = len(data)

        file_size_mb = file_size_bytes / (1024 * 1024)
        if file_size_mb > 50:
            raise ValueError(f"视频大小约 {file_size_mb:.2f} MB，超过参考视频 50 MB 限制")

        content_hash = self._hash_bytes(data)
        if reuse_existing:
            object_key = self._build_object_key(object_prefix, source["filename"], content_hash=content_hash)
            reused_existing = self._object_exists(client, bucket.strip(), object_key)
        else:
            object_key = self._build_object_key(object_prefix, source["filename"])
            reused_existing = False

        if not reused_existing:
            self._put_object_with_fallbacks(client, bucket.strip(), object_key, data, content_type)
        signed_url = self._generate_presigned_url(client, bucket.strip(), object_key, expires_seconds)

        result_info = [
            "📤 TOS 上传成功" if not reused_existing else "♻️ 复用已有 TOS 对象",
            f"🪣 Bucket: {bucket}",
            f"🌍 Region: {region}",
            f"🔗 Endpoint: {endpoint}",
            f"📁 Object Key: {object_key}",
            f"♻️ 复用开关: {'开启' if reuse_existing else '关闭'}",
            f"♻️ 是否复用: {'是' if reused_existing else '否'}",
            f"🧮 SHA256: {content_hash}",
            f"🎞️ 文件名: {source['filename']}",
            f"📦 文件大小: {file_size_mb:.2f} MB",
            f"⏳ 时效: {expires_seconds} 秒",
            f"🔗 URL: {signed_url}",
        ]

        return (signed_url, object_key, reused_existing, "\n".join(result_info))


# Node mappings for ComfyUI
NODE_CLASS_MAPPINGS = {
    "SeedreamImageGenerate": SeedreamImageGenerate,
    "SeedreamImageGenerateV2": SeedreamImageGenerateV2,
    "SeedreamImageGenerateWithWebSearch": SeedreamImageGenerateWithWebSearch,
    "SeedanceVideoGenerate": SeedanceVideoGenerate,
    "TOSUploadVideoURL": TOSUploadVideoURL
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "SeedreamImageGenerate": "Seedream Image Generate",
    "SeedreamImageGenerateV2": "Seedream Image Generate V2",
    "SeedreamImageGenerateWithWebSearch": "Seedream Image Generate With Web Search",
    "SeedanceVideoGenerate": "Seedance Video Generate",
    "TOSUploadVideoURL": "TOS Upload Video URL"
}
