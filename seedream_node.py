import os
import requests
import torch
import numpy as np
from PIL import Image
import io
import time
import folder_paths
from volcenginesdkarkruntime import Ark
from volcenginesdkarkruntime.types.images.images import SequentialImageGenerationOptions

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
                "model": (["doubao-seedream-4-0-250828", "doubao-seedream-4-5-251128"], {
                    "default": "doubao-seedream-4-0-250828"
                }),
                "aspect_ratio": (["1:1", "2:3", "3:2", "4:3", "3:4", "16:9", "9:16", "21:9", "2K", "3K", "3.5K", "4K"], {
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
    
    def aspect_ratio_to_size(self, aspect_ratio):
        """Convert aspect ratio to size parameter"""
        ratio_map = {
            "1:1": "2048x2048",
            "4:3": "2304x1728", 
            "3:4": "1728x2304",
            "16:9": "2560x1440",
            "9:16": "1440x2560",
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
                
            # Convert aspect ratio to size
            size = self.aspect_ratio_to_size(aspect_ratio)
            
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
            
            images_response = self.client.images.generate(**generate_params)
            
            # 处理流式响应
            all_image_data = []
            if stream:
                print(f"🌊 流式响应模式，正在收集所有图片...")
                try:
                    # 流式响应返回的是迭代器，需要遍历收集所有图片
                    chunk_count = 0
                    for chunk in images_response:
                        chunk_count += 1
                        print(f"   📦 收到第 {chunk_count} 个chunk, 类型: {type(chunk)}")
                        
                        if hasattr(chunk, 'data'):
                            print(f"   ✓ Chunk有data属性，数据项数: {len(chunk.data)}")
                            for img_data in chunk.data:
                                # 验证图片数据有效性
                                has_url = hasattr(img_data, 'url') and img_data.url is not None
                                has_b64 = hasattr(img_data, 'b64_json') and img_data.b64_json is not None
                                
                                if has_url or has_b64:
                                    all_image_data.append(img_data)
                                    size_info = img_data.size if hasattr(img_data, 'size') else 'unknown'
                                    url_preview = img_data.url[:50] + '...' if has_url and len(img_data.url) > 50 else (img_data.url if has_url else 'b64_json')
                                    print(f"   ✅ 收到第 {len(all_image_data)} 张有效图片: {size_info}, URL: {url_preview}")
                                else:
                                    print(f"   ⚠️ 跳过无效图片数据: url={getattr(img_data, 'url', None)}, b64_json={'存在' if has_b64 else '不存在'}")
                        else:
                            print(f"   ⚠️ Chunk没有data属性")
                            # 可能chunk本身就是image data
                            has_url = hasattr(chunk, 'url') and chunk.url is not None
                            has_b64 = hasattr(chunk, 'b64_json') and chunk.b64_json is not None
                            
                            if has_url or has_b64:
                                all_image_data.append(chunk)
                                print(f"   ✅ 直接收集chunk为图片: {len(all_image_data)}")
                    
                    print(f"📊 流式响应完成，共收到 {chunk_count} 个chunk，收集 {len(all_image_data)} 张有效图片")
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
                    error_detail += f"  - 收到chunk数: {chunk_count}\n"
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
            result_info.append(f"📐 宽高比: {aspect_ratio}")
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
                f"📐 宽高比: {aspect_ratio}",
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
            
            return ([self.pil_to_tensor(error_img)], error_text)

# Node mappings for ComfyUI
NODE_CLASS_MAPPINGS = {
    "SeedreamImageGenerate": SeedreamImageGenerate
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "SeedreamImageGenerate": "Seedream Image Generate"
}
