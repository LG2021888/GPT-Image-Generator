一个 Windows 桌面小工具，用于调用 OpenAI-compatible Images API 进行文生图、图生图和简单并发压力测试。

当前推荐运行版本：

```text
GPT Image Generator CN2.exe
```

> 注意：这是 PyInstaller 文件夹版程序，不能只复制单个 `.exe`。如果要发给别人，请打包整个 `GPT Image Generator CN2` 文件夹。

## 功能

- API 配置：`Base URL`、`API Key`、显示/隐藏 Key、保存配置
- 文生图：只需要提示词，不需要选择图片
- 图生图：选择 1 张或多张图片，总大小限制 `<= 30MB`
- 参数选择：尺寸预设、自定义尺寸、质量、格式、jpeg/webp 压缩比例、模型名
- 压力测试：总请求数、并发线程数、输出目录、开始/停止、进度和日志
- 支持 OpenAI-compatible 接口：
  - 文生图：`POST {Base URL}/images/generations`
  - 图生图：`POST {Base URL}/images/edits`

## 目录说明

```text
app/                 源码目录，需要保留
scripts/             打包脚本目录，建议保留

dist_cn2/            当前推荐的已打包可运行版本
build_cn2/           PyInstaller 临时构建目录，可删除
```

## 使用方法

1. 双击运行：

   ```text
   dist_cn2\GPT Image Generator CN2\GPT Image Generator CN2.exe
   ```

2. 填写接口配置：

   ```text
   Base URL: https://你的接口地址/v1
   API Key: 你的 API Key
   模型: gpt-image-2 或你的服务商支持的模型名
   ```

3. 选择模式：

   - `文生图`：只填写提示词，不需要选择图片
   - `图生图（图+文）`：先选择图片，再填写提示词

4. 设置参数：

   - 尺寸预设：例如 `auto`、`1024x1024`、`1024x1536`
   - 自定义尺寸：格式为 `宽x高`，例如 `1024x1536`
   - 质量：`自动 / 低 / 中 / 高`
   - 格式：`png / jpeg / webp`
   - 输出目录：生成图片保存位置

5. 点击 `开始生成`。

## 从源码运行

需要 Python 3.12+，并且 Python 环境需要可用的 `tkinter`。

```powershell
python app\gpt_image_generator.py
```

如果使用本机 Codex 运行环境：

```powershell
& "C:\Users\###\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" app\gpt_image_generator.py
```

## 打包 EXE

当前项目使用 PyInstaller 打包为 Windows 文件夹版 EXE。

```powershell
scripts\build_exe.bat
```

默认输出：

```text
dist\GPTImageGenerator\GPT Image Generator.exe
```

## 配置文件

程序会在 EXE 所在目录或源码运行目录生成：

```text
config.ini
```

用于保存：

- Base URL
- API Key
- 模型名
- 输出目录
- 尺寸、质量、格式等默认参数

如果配置异常，可以关闭程序后删除 `config.ini`，再重新打开。

## 常见问题

### 1. 双击 EXE 报缺少 tkinter

请确认你运行的是新版目录：

```text
dist_cn2\GPT Image Generator CN2\GPT Image Generator CN2.exe
```

并且不要只复制单个 `.exe`，必须连同 `_internal` 文件夹一起复制。

### 2. 下拉框点了没反应

旧版使用 `ttk.Combobox`，部分打包环境下会失效。新版 `dist_cn2` 已改为更稳定的菜单控件。

### 3. 提示 `model_not_found`

说明你的服务商当前 Base URL 不支持界面里填写的模型名。请把模型改成该服务商支持的图片模型。

### 4. 图生图提示必须选择图片

这是正常逻辑。`图生图（图+文）` 需要至少 1 张输入图片；如果不想选图，请切换到 `文生图`。

### 5. 生成成功但找不到图片

检查界面里的 `输出目录`。程序会把返回的 `b64_json` 或图片 URL 下载结果保存到该目录。

## 备注

本工具面向 OpenAI-compatible Images API。不同中转或服务商的参数兼容度可能不同，如果某些参数不支持，日志区会显示 HTTP 状态码和服务端返回内容。
