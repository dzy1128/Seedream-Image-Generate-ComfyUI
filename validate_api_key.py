#!/usr/bin/env python3
"""
Volcengine Seedream API Key 验证工具

这个脚本帮助您诊断和验证API Key设置
"""

import os
import sys

def validate_api_key():
    """验证API Key设置"""
    print("🔍 Volcengine Seedream API Key 验证")
    print("=" * 60)
    
    # 检查环境变量
    api_key = os.environ.get("ARK_API_KEY")
    
    if not api_key:
        print("❌ 错误: ARK_API_KEY 环境变量未设置")
        print("\n💡 设置方法:")
        print("方法1 - 临时设置:")
        print("   export ARK_API_KEY='your_api_key_here'")
        print("\n方法2 - 永久设置 (推荐):")
        print("   echo 'export ARK_API_KEY=\"your_api_key_here\"' >> ~/.bashrc")
        print("   source ~/.bashrc")
        print("\n方法3 - 在ComfyUI启动脚本中设置:")
        print("   ARK_API_KEY='your_api_key_here' python main.py")
        return False
    
    print("✅ ARK_API_KEY 环境变量已设置")
    
    # 基本信息
    print(f"📏 长度: {len(api_key)} 字符")
    print(f"🔍 预览: {api_key[:8]}{'*' * max(0, len(api_key) - 8)}")
    
    # 格式检查
    issues = []
    
    # 检查空白字符
    stripped_key = api_key.strip()
    if len(stripped_key) != len(api_key):
        issues.append("包含前后空格")
        
    if '\n' in api_key:
        issues.append("包含换行符")
        
    if '\t' in api_key:
        issues.append("包含制表符")
        
    if ' ' in stripped_key:
        issues.append("包含空格")
    
    # 检查长度
    if len(stripped_key) < 10:
        issues.append("长度太短")
    elif len(stripped_key) > 200:
        issues.append("长度异常长")
    
    # 检查字符类型
    if not all(c.isprintable() for c in stripped_key):
        issues.append("包含不可打印字符")
    
    if issues:
        print(f"⚠️  发现 {len(issues)} 个潜在问题:")
        for i, issue in enumerate(issues, 1):
            print(f"   {i}. {issue}")
        print("\n💡 建议: 重新从火山引擎控制台复制API Key")
    else:
        print("✅ API Key格式检查通过")
    
    # 尝试导入SDK
    print("\n📦 检查依赖包...")
    try:
        from volcenginesdkarkruntime import Ark
        print("✅ volcengine-python-sdk 已安装")
    except ImportError as e:
        print(f"❌ volcengine-python-sdk 未安装: {e}")
        print("💡 安装命令: pip install 'volcengine-python-sdk[ark]'")
        return False
    
    # 尝试初始化客户端
    print("\n🔌 测试客户端初始化...")
    try:
        client = Ark(
            base_url="https://ark.cn-beijing.volces.com/api/v3",
            api_key=stripped_key
        )
        print("✅ 客户端初始化成功")
        print("💡 API Key格式正确，可以尝试API调用")
    except Exception as e:
        print(f"❌ 客户端初始化失败: {e}")
        return False
    
    print("\n📋 下一步:")
    print("1. 如果仍有认证错误，请检查API Key权限")
    print("2. 确认账户有足够配额")
    print("3. 验证网络连接到火山引擎服务")
    print("4. 重启ComfyUI确保环境变量生效")
    
    return len(issues) == 0

if __name__ == "__main__":
    success = validate_api_key()
    print(f"\n{'🎉 验证完成' if success else '❌ 发现问题'}")
    sys.exit(0 if success else 1)
