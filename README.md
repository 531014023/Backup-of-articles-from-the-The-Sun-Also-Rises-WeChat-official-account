# 微信公众号文章批量抓取脚本

**主要是作为太阳照常升起公众号的备份，顺便开源文章链接和抓取脚本，脚本只能抓取也有链接，无法实时爬新发文章**。

**只需要文章的直接全部clone下来再删掉其他文件只保留《太阳照常升起文件夹》即可**。

支持断点续传、日志记录、防封机制的微信公众号文章批量抓取工具。

## 功能特性

- 从 CSV 文件读取文章列表
- 自动下载文章中的图片并替换为本地链接
- 支持断点续传（通过 progress.json）
- 防封机制：随机延时、User-Agent 轮换
- 可配置的环境变量支持
- RSS 自动拉取脚本（支持环境变量配置）
- 支持 COS 对象存储上传

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

# ========== RSS 服务配置 ==========
# RSS 服务端地址
# RSS_BASE_URL=http://192.168.3.100:12005

# ========== IMA 配置 ==========
# IMA 密钥存放目录
# IMA_DIR=./ima
```

### 配置示例

**Windows 用户示例：**
```ini
OUTPUT_DIR=C:/Users/Alice/Desktop/微信公众号文章
ARTICLES_CSV_FILE=C:/Users/Alice/Desktop/articles.csv
MIN_DELAY=2
MAX_DELAY=4
RSS_BASE_URL=http://192.168.3.100:12005
IMA_DIR=./ima
```

**Linux/Mac 用户示例：**
```ini
OUTPUT_DIR=/home/alice/Documents/wechat_articles
ARTICLES_CSV_FILE=/home/alice/Documents/articles.csv
MIN_DELAY=2
MAX_DELAY=4
RSS_BASE_URL=http://192.168.3.100:12005
IMA_DIR=./ima
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
| `RSS_BASE_URL` | 可选 | RSS 服务端地址 | 无 |
| `IMA_DIR` | 可选 | IMA 密钥存放目录 | `./ima` |

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

### RSS 自动拉取

使用环境变量配置启动 RSS 自动拉取：

```bash
RSS_BASE_URL=http://192.168.3.100:12005 python fetch_rss_articles.py
```

### COS 对象存储上传

使用 `cos-upload.cjs` 将文件上传到腾讯云 COS：

```bash
node cos-upload.cjs \
  --file <本地文件路径> \
  --secret-id <你的 SecretId> \
  --secret-key <你的 SecretKey> \
  --token <安全令牌> \
  --bucket <存储桶名称> \
  --region <地域区域> \
  --cos-key <COS 上的文件路径>
```

可选参数：
- `--content-type <mime>`: 指定文件 MIME 类型
- `--start-time <ts>`: 签名起始时间戳
- `--expired-time <ts>`: 签名过期时间戳

## 脚本工具一览

| 脚本 | 说明 |
|------|------|
| `fetch_weixin_articles.py` | 微信公众号文章批量抓取 |
| `add_article.py` | 添加新文章到 CSV 列表 |
| `fetch_rss_articles.py` | RSS 自动拉取脚本 |
| `ima_upload.py` | IMA 知识库上传脚本 |
| `cos-upload.cjs` | 腾讯云 COS 对象存储上传 |

## 项目目录结构

```
wechat_articles_downloads/
├── fetch_weixin_articles.py  # 文章抓取主脚本
├── add_article.py            # 添加文章到 CSV
├── fetch_rss_articles.py     # RSS 自动拉取
├── ima_upload.py             # IMA 知识库上传
├── cos-upload.cjs           # COS 对象存储上传
├── articles_with_publish_date.csv  # 文章列表数据
├── requirements.txt          # Python 依赖
├── .env.example              # 环境变量示例
├── README.md                 # 本文档
└── backup/                   # 文章备份目录
    └── 太阳照常升起/
        ├── html/             # HTML 文件
        ├── md/               # Markdown 文件
        └── images/           # 文章图片
```

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

## 添加新文章到列表

使用 `add_article.py` 脚本可以方便地将新文章添加到 CSV 列表：

### 功能特性

- 自动解析文章标题和发布时间
- 自动分配新序号（当前最大序号 + 1）
- 新文章自动插入到 CSV 开头
- 检测重复链接，避免重复添加

### 使用方式

**方式1：命令行直接传链接**

```bash
python add_article.py "https://mp.weixin.qq.com/s/xxxxx"
```

**方式2：交互模式**

```bash
python add_article.py
```

然后按提示输入文章链接。

### 工作流程

1. 打开微信文章复制链接然后运行脚本粘贴链接
2. 脚本自动抓取文章信息（标题、发布时间）
3. 如果无法自动识别发布时间，会提示手动输入
4. 新文章以新的序号插入到 CSV 开头
5. 序号是固定ID，不会重新编排已有文章

## 断点续传

脚本会自动保存进度到 `progress.json`，中断后重新运行会从上次中断处继续。

如需重新抓取所有文章，请删除 `progress.json`：

```bash
del progress.json
```
