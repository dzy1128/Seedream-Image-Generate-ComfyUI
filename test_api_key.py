#!/usr/bin/env python3
"""
Seedream API Key测试脚本

用于验证API Key是否正确设置和有效
运行方式: python test_api_key.py
"""

import os
import sys

def test_api_key():
    """测试API Key设置和有效性"""
    print("🔍 检查Seedream API Key设置...")
    print("=" * 50)
    
    # 检查环境变量
    api_key = os.environ.get("ARK_API_KEY")
    
    if not api_key:
        print("❌ 错误: ARK_API_KEY 环境变量未设置")
        print("📝 解决方案:")
        print("   export ARK_API_KEY='your_api_key_here'")
        print("   或在 ~/.bashrc 中添加: export ARK_API_KEY='your_api_key_here'")
        return False
    
    print(f"✓ ARK_API_KEY 已设置")
    print(f"✓ API Key长度: {len(api_key)} 字符")
    print(f"✓ API Key前缀: {api_key[:8]}{'*' * (len(api_key) - 8) if len(api_key) > 8 else '***'}")
    
    # 基本格式检查
    if len(api_key.strip()) != len(api_key):
        print("⚠️  警告: API Key包含前后空格，已自动清理")
        api_key = api_key.strip()
    
    if len(api_key) < 20:
        print("⚠️  警告: API Key长度可能太短，请检查是否完整")
    
    # 尝试导入SDK
    try:
        from volcenginesdkarkruntime import Ark
        print("✓ volcengine SDK导入成功")
    except ImportError as e:
        print(f"❌ 错误: volcengine SDK导入失败: {e}")
        print("📝 解决方案: pip install 'volcengine-python-sdk[ark]'")
        return False
    
    # 尝试初始化客户端
    try:
        client = Ark(
            base_url="https://ark.cn-beijing.volces.com/api/v3",
            api_key=api_key
        )
        print("✓ Ark客户端初始化成功")
    except Exception as e:
        print(f"❌ 错误: Ark客户端初始化失败: {e}")
        return False
    
    print("\n🎉 API Key设置检查完成!")
    print("📌 如果仍有问题，请检查:")
    print("   1. API Key是否从火山引擎控制台正确复制")
    print("   2. API Key是否有图像生成权限")
    print("   3. 账户是否有足够的配额")
    print("   4. 网络连接是否正常")
    
    return True

if __name__ == "__main__":
    success = test_api_key()
    sys.exit(0 if success else 1)
