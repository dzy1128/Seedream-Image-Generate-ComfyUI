# README 图片使用指南

## 文件夹结构

我们已经为您创建了以下文件夹结构：

```
Seedream-Image-Generate-ComfyUI/
├── images/                    # 主要图片文件夹
│   ├── screenshots/          # 节点界面截图
│   ├── examples/             # 生成示例图片
│   ├── workflow/             # 工作流程图
│   ├── icons/                # 图标文件
│   └── README.md             # 图片文件夹说明
├── docs/                     # 文档文件夹
│   └── images/               # 文档专用图片
└── assets/                   # 其他资源文件
```

## 在 README.md 中引用图片的方法

### 1. 基本图片引用
```markdown
![描述文字](images/文件名.png)
```

**示例：**
```markdown
![节点界面](images/screenshots/node-interface.png)
```

### 2. 带链接的图片
```markdown
[![描述文字](images/文件名.png)](链接地址)
```

**示例：**
```markdown
[![点击查看大图](images/examples/result.png)](images/examples/result.png)
```

### 3. 控制图片大小
```markdown
<img src="images/文件名.png" alt="描述文字" width="500">
```

**示例：**
```markdown
<img src="images/screenshots/node-ui.png" alt="节点界面" width="600">
```

### 4. 图片居中显示
```markdown
<div align="center">
  <img src="images/文件名.png" alt="描述文字" width="400">
</div>
```

### 5. 多图片并排显示
```markdown
<div align="center">
  <img src="images/examples/input.png" alt="输入图像" width="300">
  <img src="images/examples/output.png" alt="输出图像" width="300">
  <p><em>左：输入图像 | 右：生成结果</em></p>
</div>
```

### 6. 响应式图片（适应不同屏幕）
```markdown
<img src="images/文件名.png" alt="描述文字" style="max-width: 100%; height: auto;">
```

## 建议的图片类型和用途

### screenshots/ 文件夹
- `node-interface.png` - 节点界面截图
- `node-parameters.png` - 参数设置截图
- `comfyui-workflow.png` - 在ComfyUI中的工作流截图

### examples/ 文件夹
- `input-example.png` - 输入图像示例
- `output-example.png` - 生成结果示例
- `before-after.png` - 对比图

### workflow/ 文件夹
- `basic-workflow.png` - 基础工作流程图
- `advanced-workflow.png` - 高级工作流程图
- `node-connections.png` - 节点连接示意图

### icons/ 文件夹
- `logo.png` - 项目图标
- `feature-icons.png` - 功能图标

## 图片文件命名规范

1. **使用英文和数字**
2. **使用连字符连接单词**: `node-interface.png`
3. **描述性命名**: `workflow-basic.png` 而不是 `img1.png`
4. **保持一致性**: 统一使用小写字母

## 图片优化建议

1. **文件大小**: 尽量控制在 1MB 以内
2. **分辨率**: 截图建议 1920x1080 或更小
3. **格式选择**:
   - PNG: 截图、界面图片
   - JPG: 照片、生成结果
   - GIF: 动画演示

## 当前README中的图片占位符

我们已经在README.md中添加了注释形式的图片引用示例：

1. 顶部logo/banner图片
2. 工作流程示例
3. 节点参数截图
4. 生成结果对比

您只需要：
1. 将图片文件放入对应文件夹
2. 取消注释对应的图片引用行
3. 确保文件名匹配

## 示例模板

以下是一些常用的图片引用模板：

### 功能展示
```markdown
## 功能特性

<div align="center">
  <img src="images/screenshots/main-features.png" alt="主要功能" width="800">
</div>
```

### 安装步骤
```markdown
## 安装步骤

1. 下载节点文件
   ![下载文件](images/screenshots/download.png)

2. 复制到ComfyUI目录
   ![复制文件](images/screenshots/install.png)
```

### 使用教程
```markdown
## 使用教程

### 步骤1: 添加节点
![添加节点](images/workflow/step1-add-node.png)

### 步骤2: 设置参数
![设置参数](images/workflow/step2-parameters.png)

### 步骤3: 连接工作流
![连接工作流](images/workflow/step3-connect.png)
```

现在您可以开始添加图片了！
