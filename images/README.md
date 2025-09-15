# 图片文件夹说明

这个文件夹用于存放README.md中使用的图片资源。

## 文件夹结构

```
images/
├── README.md           # 本说明文件
├── screenshots/        # 界面截图
├── examples/          # 示例图片
├── workflow/          # 工作流程图
└── icons/             # 图标文件
```

## 在README中引用图片

### 相对路径引用
```markdown
![描述文字](images/screenshot.png)
```

### 带链接的图片
```markdown
[![描述文字](images/screenshot.png)](链接地址)
```

### 指定图片大小
```markdown
<img src="images/screenshot.png" alt="描述文字" width="500">
```

## 图片文件命名建议

- 使用英文和数字
- 使用连字符分隔单词
- 例如：`node-interface.png`, `workflow-example.jpg`

## 支持的图片格式

- PNG（推荐用于截图和界面图片）
- JPG/JPEG（推荐用于照片）
- GIF（用于动图演示）
- SVG（用于矢量图标）
