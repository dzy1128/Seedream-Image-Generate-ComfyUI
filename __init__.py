"""
Seedream Image Generate ComfyUI Node

A custom node for ComfyUI that enables image generation using Volcengine's Seedream API.
This node allows users to generate high-quality images with various configuration options
including model selection, aspect ratios, and sequential image generation.

Features:
- Multiple model support (doubao-seedream series)
- Input up to 5 images (1 required, 4 optional)
- Configurable aspect ratios instead of fixed sizes
- Sequential image generation with customizable max images
- Support for watermark and streaming options
- Multiple response formats (URL and base64)

Requirements:
- volcengine-python-sdk[ark]
- ARK API Key (from environment variable or node input)

Author: Custom Node for ComfyUI
Version: 1.0.0
"""

from .seedream_node import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS

__all__ = ['NODE_CLASS_MAPPINGS', 'NODE_DISPLAY_NAME_MAPPINGS']

# ComfyUI will automatically load these mappings
WEB_DIRECTORY = "./web"
