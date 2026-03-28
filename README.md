# 微信公众号文章批量抓取脚本

支持断点续传、日志记录、防封机制的微信公众号文章批量抓取工具。主要是作为太阳照常升起公众号的备份，顺便开源文章链接和抓取脚本。

## 功能特性

- 从 CSV 文件读取文章列表
- 自动下载文章中的图片并替换为本地链接
- 支持断点续传（通过 progress.json）
- 防封机制：随机延时、User-Agent 轮换
- 可配置的环境变量支持

## 安装依赖

```bash
pip install -r requirements.txt
```

## 配置环境变量

**⚠️ 必须配置环境变量才能运行脚本！**

脚本通过 `.env` 文件读取环境变量配置：

### 第一步：创建配置文件

复制示例配置文件：
```bash
cp .env.example .env
```

或在 Windows PowerShell 中：
```powershell
Copy-Item .env.example .env
```

### 第二步：编辑配置文件

用文本编辑器打开 `.env` 文件，设置 **必需的** `OUTPUT_DIR`：

```ini
# ========== 必需配置 ==========
# 设置文章保存目录（必须！）
OUTPUT_DIR=C:/Users/你的用户名/Desktop/文章下载

# ========== 可选配置 ==========
# 文章列表 CSV 文件路径（默认使用当前目录的 articles_with_publish_date.csv）
# ARTICLES_CSV_FILE=./articles_with_publish_date.csv

# 请求间隔（秒）- 防止被封，数值越大越安全
# MIN_DELAY=1
# MAX_DELAY=2

# 图片下载间隔（秒）
# IMG_MIN_DELAY=0.5
# IMG_MAX_DELAY=1.5

# 网络请求重试次数
# MAX_RETRIES=3
```

### 配置示例

**Windows 用户示例：**
```ini
OUTPUT_DIR=C:/Users/Alice/Desktop/微信公众号文章
ARTICLES_CSV_FILE=C:/Users/Alice/Desktop/articles.csv
MIN_DELAY=2
MAX_DELAY=4
```

**Linux/Mac 用户示例：**
```ini
OUTPUT_DIR=/home/alice/Documents/wechat_articles
ARTICLES_CSV_FILE=/home/alice/Documents/articles.csv
MIN_DELAY=2
MAX_DELAY=4
```

### 可配置项说明

| 配置项 | 是否必需 | 说明 | 默认值 |
|--------|----------|------|--------|
| `OUTPUT_DIR` | ✅ **必需** | 文章保存目录 | 无（必须设置） |
| `ARTICLES_CSV_FILE` | 可选 | 文章列表 CSV 文件路径 | `./articles_with_publish_date.csv` |
| `MIN_DELAY` | 可选 | 请求最小间隔（秒） | `1` |
| `MAX_DELAY` | 可选 | 请求最大间隔（秒） | `2` |
| `IMG_MIN_DELAY` | 可选 | 图片下载最小间隔（秒） | `0.5` |
| `IMG_MAX_DELAY` | 可选 | 图片下载最大间隔（秒） | `1.5` |
| `MAX_RETRIES` | 可选 | 网络请求最大重试次数 | `3` |

## CSV 文件格式

CSV 文件需要包含以下列：

| 列名 | 说明 |
|------|------|
| 序号 | 文章编号（必须） |
| 文章名 | 文章标题 |
| 发布时间 | 文章发布时间（格式：YYYY-MM-DD） |
| URL | 文章链接 |

示例：
```csv
序号,文章名,发布时间,URL
439,微信公众号在失去活人感,2026-03-28,https://mp.weixin.qq.com/s/xxxxx
438,伊朗已占据谈判优势地位,2026-03-27,https://mp.weixin.qq.com/s/yyyyy
```

## 使用方法

配置好 `.env` 文件后，直接运行：

```bash
python fetch_weixin_articles.py
```

如果未配置 `OUTPUT_DIR`，脚本会报错并提示你创建配置文件。

## 输出目录结构

运行后会在 `OUTPUT_DIR` 目录下生成以下结构：

```
OUTPUT_DIR/
├── html_source/          # HTML 缓存文件（用于断点续传）
├── html/                 # 提取后的 HTML 文件（用于阅读）
│   ├── 2026-03-28_微信公众号在失去活人感.html
│   └── ...
├── md/                   # Markdown 文件
│   ├── 2026-03-28_微信公众号在失去活人感.md
│   └── ...
└── images/               # 下载的图片
    ├── 2026-03-28_微信公众号在失去活人感/
    │   ├── img_000.jpg
    │   └── ...
    └── ...
```

## 断点续传

脚本会自动保存进度到 `progress.json`，中断后重新运行会从上次中断处继续。

如需重新抓取所有文章，请删除 `progress.json`：

```bash
del progress.json
```
