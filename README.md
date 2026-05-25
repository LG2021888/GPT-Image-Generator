# GPT 图像生成器

Windows Tkinter 桌面工具，用于调用 OpenAI-compatible Images API 进行文生图、图生图和简单并发测试。支持 OpenAI 兼容平台与 Grok/xAI 平台配置。

当前可运行版本：

```text
E:\GptChat\001\dist\GPTImageGenerator\GPT Image Generator.exe
```

> 注意：这是 PyInstaller 文件夹版程序，不能只复制单个 `.exe`。如果要发给别人，请压缩并发送整个 `dist\GPTImageGenerator` 文件夹。

## 功能

- 多 API 配置：可保存/切换/删除多组 `Base URL + API Key + 模型名`
- 文生图：只填写提示词，不需要选择图片
- 图生图：选择 1 张或多张图片，总大小限制 `<= 30MB`
- 提示词历史：自动保存最近 30 条提示词，可从提示词区域的 `历史` 下拉中快速恢复
- 参数选择：尺寸预设、自定义尺寸、生成张数 `1/2/3`、质量、风格、格式、jpeg/webp 压缩比例
- 平台选择：`OpenAI兼容` / `Grok/xAI`
- 输出目录：可选择目录，也可一键打开输出目录
- 进度显示：请求未完成前显示 0-100 循环动画；完成后显示真实进度
- 压力测试：总请求数、并发线程数、开始/停止、成功/失败统计和日志
- 尺寸校正：选择固定尺寸时，如果服务商实际返回尺寸不一致，会在本地保存后自动校正到目标宽高

## 接口

- 文生图：`POST {Base URL}/images/generations`
- 图生图：`POST {Base URL}/images/edits`
- Grok/xAI：默认 Base URL 为 `https://api.x.ai/v1`，默认模型为 `grok-imagine-image-quality`；程序会按 Grok/xAI 图片接口传 `aspect_ratio`、`resolution` 等兼容参数。

示例配置：

```text
Base URL: https://你的接口地址/v1
API Key: 你的 API Key
模型: gpt-image-2 或你的服务商支持的图片模型
```

Grok/xAI 示例：

```text
平台: Grok/xAI
Base URL: https://api.x.ai/v1
模型: grok-imagine-image-quality
```

说明：Grok/xAI 官方图片接口当前以 `1k/2k` 分辨率为主；如果界面选择 `3840x2160` 等 4K 尺寸，程序会请求可用高分辨率并在本地保存后校正为目标尺寸。

## 目录说明

```text
app/                 源码目录
scripts/             打包脚本目录
README.md            项目说明文档

dist/                当前最终打包输出目录
.pydeps/             本机 PyInstaller 依赖目录，源码上传通常不需要
.pip-cache/          pip 缓存，不需要上传
.npm-cache/          npm 缓存，不需要上传
```

如果只上传源码，推荐保留：

```text
app/
scripts/
README.md
```

如果只发可运行程序，推荐压缩整个目录：

```text
dist/GPTImageGenerator/
```

## 使用方法

1. 双击运行：

   ```text
   dist\GPTImageGenerator\GPT Image Generator.exe
   ```

2. 在 `API 配置` 中填写接口地址、API Key 和模型名。
3. 如果需要多套接口，填写 `名称` 后点击 `保存/更新`；之后可从 `配置` 菜单切换。
4. 选择 `文生图` 或 `图生图（图+文）`。
5. 设置尺寸、质量、风格、生成张数、格式、输出目录等参数。
6. 如果一次想返回多张图，把 `张数` 选择为 `1`、`2` 或 `3`。
7. 点击 `开始生成`。

## 从源码运行

需要 Python 3.12+，且 Python 环境需要可用的 `tkinter`。

```powershell
python app\gpt_image_generator.py
```

## 打包 EXE

```powershell
scripts\build_exe.bat
```

输出目录：

```text
dist\GPTImageGenerator\GPT Image Generator.exe
```

## 配置文件

程序会在 EXE 所在目录或源码运行目录生成：

```text
config.ini
```

其中保存多套 API 配置、界面参数和最近 30 条提示词历史。如果配置异常，可以关闭程序后删除 `config.ini`，再重新打开。

## 常见问题

### 1. 双击 EXE 报缺少 tkinter

不要只复制单个 `.exe`，必须连同 `_internal` 文件夹一起复制整个 `dist\GPTImageGenerator` 目录。

### 2. 提示 `model_not_found`

说明你的服务商不支持当前模型名。请在界面里把模型改成该服务商支持的图片模型。

### 3. 图生图提示必须选择图片

这是正常逻辑。`图生图（图+文）` 需要至少 1 张输入图片；如果不想选图，请切换到 `文生图`。

### 4. 生成成功但找不到图片

检查界面里的 `输出目录`，也可以点击 `打开输出目录`。

### 5. 选择 4K 但服务商返回 2K

不同服务商对图片尺寸支持不一致。新版程序会把实际请求参数写入日志，并在保存后对固定尺寸图片做本地尺寸校正，例如 `3840x2160`。

## 免责声明

本工具仅用于个人学习、接口测试与合法授权场景，使用者应自行确保 API 来源、输入内容和生成结果的合规性，因使用本工具产生的任何风险与责任由使用者自行承担。

## 打包注意

`scripts\build_exe.bat` 重新打包时会自动保留以下用户数据：

```text
dist\GPTImageGenerator\config.ini
dist\GPTImageGenerator\output\
```

因此后续重新打包不会再删除已保存的 API 配置和默认输出目录内容。
