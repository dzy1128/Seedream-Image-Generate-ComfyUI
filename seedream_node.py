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
                    "default": 3,
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
                })
            },
            "optional": {
                "image2": ("IMAGE",),
                "image3": ("IMAGE",),
                "image4": ("IMAGE",),
                "image5": ("IMAGE",)
            }
        }
    
    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("images",)
    OUTPUT_IS_LIST = (True,)
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
    
    def upload_image_to_temp_url(self, pil_image):
        """
        Convert PIL image to a temporary URL that can be used by the API
        This is a simplified approach - in production you might want to use a proper image hosting service
        """
        # For this example, we'll convert to base64 data URL
        buffered = io.BytesIO()
        pil_image.save(buffered, format="PNG")
        img_str = buffered.getvalue()
        
        # In a real implementation, you would upload this to a temporary hosting service
        # For now, we'll save it locally and return a file path
        # This is just a placeholder - you'll need to implement proper image hosting
        temp_path = os.path.join(folder_paths.get_temp_directory(), f"temp_image_{id(pil_image)}.png")
        pil_image.save(temp_path)
        return f"file://{temp_path}"
    
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
            print(f"Error downloading image from {url}: {e}")
            # Return a black placeholder image
            placeholder = Image.new('RGB', (512, 512), color='black')
            return self.pil_to_tensor(placeholder)
    
    def initialize_client(self, base_url):
        """Initialize the Ark client"""
        # Get API key from environment variable
        api_key = os.environ.get("ARK_API_KEY")
        
        if not api_key:
            raise ValueError("API Key is required. Please set ARK_API_KEY environment variable.")
        
        self.client = Ark(
            base_url=base_url,
            api_key=api_key
        )
    
    def generate_images(self, prompt, image1, model, aspect_ratio, sequential_image_generation, 
                       max_images, response_format, watermark, stream, base_url,
                       image2=None, image3=None, image4=None, image5=None):
        
        try:
            # Initialize client
            self.initialize_client(base_url)
            
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
            
            # Convert input images to URLs (this is a simplified approach)
            image_urls = []
            for img_tensor in input_images:
                # Convert tensor to PIL
                pil_img = self.tensor_to_pil(img_tensor.squeeze(0))
                # In a real implementation, you would upload to a proper image hosting service
                # For now, we'll use a placeholder URL
                url = self.upload_image_to_temp_url(pil_img)
                image_urls.append(url)
            
            # Convert aspect ratio to size
            size = self.aspect_ratio_to_size(aspect_ratio)
            
            # Prepare generation options
            generation_options = SequentialImageGenerationOptions(max_images=max_images)
            
            # Generate images
            print(f"Generating images with prompt: {prompt}")
            print(f"Model: {model}, Size: {size}, Max images: {max_images}")
            
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
            
            # Process generated images
            output_tensors = []
            
            for i, image_data in enumerate(images_response.data):
                print(f"Processing image {i+1}: URL: {image_data.url}, Size: {image_data.size}")
                
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
            
            if not output_tensors:
                # Return a placeholder if no images generated
                placeholder = Image.new('RGB', (512, 512), color='black')
                output_tensors = [self.pil_to_tensor(placeholder)]
            
            return (output_tensors,)
            
        except Exception as e:
            print(f"Error generating images: {e}")
            # Return a placeholder error image
            error_img = Image.new('RGB', (512, 512), color='red')
            return ([self.pil_to_tensor(error_img)],)

# Node mappings for ComfyUI
NODE_CLASS_MAPPINGS = {
    "SeedreamImageGenerate": SeedreamImageGenerate
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "SeedreamImageGenerate": "Seedream Image Generate"
}
