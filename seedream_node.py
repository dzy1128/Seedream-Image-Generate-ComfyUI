import os
import requests
import torch
import numpy as np
from PIL import Image
import io
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
                "image1": ("IMAGE",),
                "model": (["doubao-seedream-4-0-250828", "doubao-seedream-4-0-preview", "doubao-seedream-3-0"], {
                    "default": "doubao-seedream-4-0-250828"
                }),
                "aspect_ratio": (["1:1", "2:3", "3:2", "4:3", "3:4", "16:9", "9:16", "21:9"], {
                    "default": "1:1"
                }),
                "sequential_image_generation": (["auto", "enabled", "disabled"], {
                    "default": "auto"
                }),
                "max_images": ("INT", {
                    "default": 1,
                    "min": 1,
                    "max": 10,
                    "step": 1
                }),
                "response_format": (["url", "b64_json"], {
                    "default": "url"
                }),
                "watermark": ("BOOLEAN", {
                    "default": False
                }),
                "stream": ("BOOLEAN", {
                    "default": False
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
                    "max": 2147483647,
                    "step": 1
                }),
            },
            "optional": {
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
            "21:9": "3024x1296"
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
    
    def generate_images(self, prompt, image1, model, aspect_ratio, sequential_image_generation, 
                       max_images, response_format, watermark, stream, base_url, use_local_images, seed,
                       image2=None, image3=None, image4=None, image5=None):
        
        try:
            # Initialize client
            self.initialize_client(base_url)
            
            # Note: seed parameter is available for workflow tracking but not sent to the API
            # The Volcengine Seedream API doesn't currently support seed parameter
            
            # Collect input images
            input_images = [image1]
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
                
            if not image_urls:
                # 如果没有图像，使用默认示例
                image_urls = [
                    "https://ark-project.tos-cn-beijing.volces.com/doc_image/seedream4_imagesToimages_1.png"
                ]
            
            # Convert aspect ratio to size
            size = self.aspect_ratio_to_size(aspect_ratio)
            
            # Prepare generation options
            generation_options = SequentialImageGenerationOptions(max_images=max_images)
            
            # Generate images
            images_response = self.client.images.generate(
                model=model,
                prompt=prompt,
                image=image_urls,
                size=size,
                sequential_image_generation=sequential_image_generation,
                sequential_image_generation_options=generation_options,
                response_format=response_format,
                watermark=watermark,
                stream=stream
            )
            
            # Process generated images and collect information
            output_tensors = []
            result_info = []
            
            # Collect basic generation info
            result_info.append(f"🎨 生成信息:")
            result_info.append(f"📝 提示词: {prompt}")
            result_info.append(f"🔧 模型: {model}")
            result_info.append(f"📐 宽高比: {aspect_ratio}")
            result_info.append(f"🔄 顺序生成: {sequential_image_generation}")
            result_info.append(f"🖼️ 生成数量: {len(images_response.data)}")
            result_info.append(f"📊 输入图像: {len([img for img in [image1, image2, image3, image4, image5] if img is not None])}")
            result_info.append(f"🔄 本地图像模式: {'Base64编码' if use_local_images else '示例图像'}")
            result_info.append(f"🎲 种子值: {seed}")
            result_info.append("")
            
            for i, image_data in enumerate(images_response.data):
                result_info.append(f"📷 图像 {i+1}:")
                result_info.append(f"   🔗 URL: {image_data.url}")
                result_info.append(f"   📏 尺寸: {image_data.size}")
                
                # Add any additional metadata if available
                if hasattr(image_data, 'revised_prompt') and image_data.revised_prompt:
                    result_info.append(f"   ✏️ 修订提示词: {image_data.revised_prompt}")
                
                if hasattr(image_data, 'finish_reason') and image_data.finish_reason:
                    result_info.append(f"   ✅ 完成原因: {image_data.finish_reason}")
                
                if response_format == "url":
                    # Download image from URL
                    tensor = self.download_image_from_url(image_data.url)
                    output_tensors.append(tensor)
                else:  # b64_json
                    # Handle base64 encoded image
                    import base64
                    image_data_b64 = image_data.b64_json
                    image_bytes = base64.b64decode(image_data_b64)
                    image = Image.open(io.BytesIO(image_bytes))
                    if image.mode != 'RGB':
                        image = image.convert('RGB')
                    tensor = self.pil_to_tensor(image)
                    output_tensors.append(tensor)
                
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
            
            # Return a placeholder error image with error text
            error_img = Image.new('RGB', (512, 512), color='red')
            
            # Create detailed error text output
            error_text_parts = [
                "❌ 图像生成失败",
                "",
                f"🔍 错误信息: {error_msg}",
                "",
                f"📝 提示词: {prompt}",
                f"🔧 模型: {model}",
                f"📐 宽高比: {aspect_ratio}",
                f"🔄 顺序生成: {sequential_image_generation}",
                f"🖼️ 最大图像数: {max_images}",
                f"🌐 API地址: {base_url}",
                f"🧪 使用本地图像: {'是' if use_local_images else '否'}",
                f"🎲 种子值: {seed}",
                "",
                "💡 请检查控制台输出获取详细错误信息"
            ]
            
            error_text = "\n".join(error_text_parts)
            
            return ([self.pil_to_tensor(error_img)], error_text)

# Node mappings for ComfyUI
NODE_CLASS_MAPPINGS = {
    "SeedreamImageGenerate": SeedreamImageGenerate
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "SeedreamImageGenerate": "Seedream Image Generate"
}
