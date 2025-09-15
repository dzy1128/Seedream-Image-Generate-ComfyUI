# Seedream API Key 设置指南

## 🔑 获取API Key

1. 访问 [火山引擎控制台](https://console.volcengine.com/)
2. 开通ARK服务
3. 在ARK控制台创建API Key
4. 复制完整的API Key

## 🛠️ 设置环境变量

### Linux/macOS

#### 方法1: 临时设置 (当前会话有效)
```bash
export ARK_API_KEY="your_api_key_here"
```

#### 方法2: 永久设置 (推荐)
```bash
# 添加到 ~/.bashrc 或 ~/.zshrc
echo 'export ARK_API_KEY="your_api_key_here"' >> ~/.bashrc
source ~/.bashrc
```

#### 方法3: 启动时设置
```bash
ARK_API_KEY="your_api_key_here" python main.py
```

### Windows

#### 方法1: 命令行临时设置
```cmd
set ARK_API_KEY=your_api_key_here
```

#### 方法2: PowerShell临时设置
```powershell
$env:ARK_API_KEY="your_api_key_here"
```

#### 方法3: 系统环境变量 (推荐)
1. 右键"此电脑" → "属性"
2. "高级系统设置" → "环境变量"
3. 新建系统变量:
   - 变量名: `ARK_API_KEY`
   - 变量值: `your_api_key_here`

## ✅ 验证设置

### 检查环境变量
```bash
# Linux/macOS
echo $ARK_API_KEY

# Windows CMD
echo %ARK_API_KEY%

# Windows PowerShell
echo $env:ARK_API_KEY
```

### 运行验证脚本
```bash
cd custom_nodes/Seedream-Image-Generate-ComfyUI
python validate_api_key.py
```

## ⚠️ 常见问题

### 1. API Key包含空格或特殊字符
- **问题**: 复制时包含了额外的空格或换行符
- **解决**: 重新仔细复制API Key，确保没有多余字符

### 2. 环境变量未生效
- **问题**: 设置后立即使用，但环境变量未加载
- **解决**: 重启终端或ComfyUI

### 3. API Key权限不足
- **问题**: API Key没有图像生成权限
- **解决**: 在火山引擎控制台检查API Key权限设置

### 4. 配额不足
- **问题**: 账户配额用完
- **解决**: 在控制台查看使用情况并充值

## 🔒 安全建议

1. **不要在代码中硬编码API Key**
2. **不要提交包含API Key的文件到版本控制**
3. **定期轮换API Key**
4. **仅给API Key必要的权限**

## 📞 获取帮助

如果仍有问题，请检查:
1. 火山引擎服务状态
2. 网络连接
3. ComfyUI控制台日志
4. 运行验证脚本的输出
