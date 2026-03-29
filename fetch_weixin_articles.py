#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微信公众号文章批量抓取脚本
支持断点续传、日志记录、防封机制
支持 .env 配置文件
"""

import os
import re
import json
import time
import random
import logging
from datetime import datetime
from urllib.parse import unquote, urlparse, parse_qs
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry



# ==================== 加载环境变量配置 ====================

def load_env_config():
    """加载 .env 配置文件"""
    SCRIPT_DIR = Path(__file__).parent.absolute()
    env_file = SCRIPT_DIR / ".env"
    
    if env_file.exists():
        try:
            # 尝试使用 python-dotenv
            from dotenv import load_dotenv
            load_dotenv(env_file)
            return True
        except ImportError:
            # 如果没有安装 python-dotenv，手动解析
            with open(env_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, value = line.split('=', 1)
                        os.environ[key] = value
            return True
    return False


# 加载 .env 文件
load_env_config()


# ==================== 配置区域 ====================

# 脚本所在目录
SCRIPT_DIR = Path(__file__).parent.absolute()

# 检查必需的环境变量
def check_required_env():
    """检查必需的环境变量是否已设置"""
    output_dir = os.getenv("OUTPUT_DIR")
    if not output_dir:
        print("错误：未设置 OUTPUT_DIR 环境变量")
        print("")
        print("请创建 .env 文件并设置输出目录：")
        print("  1. 复制 .env.example 为 .env")
        print("  2. 编辑 .env 文件，设置 OUTPUT_DIR")
        print("")
        print("示例：")
        print("  OUTPUT_DIR=C:/Users/username/Desktop/wechat_articles")
        print("")
        raise SystemExit(1)
    return Path(output_dir)

# 保存目录（必需的环境变量）
OUTPUT_DIR = check_required_env()

# 当前使用的目录（会根据公众号名称动态更新）
HTML_SOURCE_DIR = OUTPUT_DIR / "cache"  # HTML缓存文件
HTML_DIR = OUTPUT_DIR / "html"  # 可见HTML文件（用于阅读）
MD_DIR = OUTPUT_DIR / "md"
IMAGES_DIR = OUTPUT_DIR / "images"  # 图片保存目录

# 全局变量存储当前公众号名称
current_nickname = ""

# 文章列表文件路径（可从环境变量配置，默认：articles_with_publish_date.csv）
ARTICLES_CSV_FILE = Path(os.getenv("ARTICLES_CSV_FILE", SCRIPT_DIR / "articles_with_publish_date.csv"))

# 日志和进度文件路径（放在脚本目录）
LOG_FILE = SCRIPT_DIR / "fetch.log"
PROGRESS_FILE = SCRIPT_DIR / "progress.json"

# 请求间隔（秒）
MIN_DELAY = float(os.getenv("MIN_DELAY", "1"))
MAX_DELAY = float(os.getenv("MAX_DELAY", "2"))

# 图片下载间隔（秒）
IMG_MIN_DELAY = float(os.getenv("IMG_MIN_DELAY", "0.5"))
IMG_MAX_DELAY = float(os.getenv("IMG_MAX_DELAY", "1.5"))

# 重试配置
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))

# User-Agent列表
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
]


def load_articles():
    """从CSV文件加载文章列表，并转换为内部JSON格式"""
    import csv
    
    articles = []
    if ARTICLES_CSV_FILE.exists():
        # 使用 utf-8-sig 编码，自动处理 BOM（字节顺序标记）
        with open(ARTICLES_CSV_FILE, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                article = {
                    'num': row.get('序号', ''),
                    'title': row.get('文章名', ''),
                    'publish_time': row.get('发布时间', ''),
                    'nickname': row.get('公众号', ''),  # 公众号名称
                    'url': row.get('URL', '')
                }
                articles.append(article)
    return articles


def setup_logging():
    """设置日志（日志文件放在脚本目录）"""
    SCRIPT_DIR.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        handlers=[
            logging.FileHandler(LOG_FILE, encoding='utf-8'),
            logging.StreamHandler()
        ]
    )
    return logging.getLogger(__name__)


# ==================== HTML转Markdown ====================

def has_bold_style(element):
    """检查元素是否有加粗样式"""
    style = element.get('style', '')
    if not style:
        return False
    if 'font-weight' in style:
        if 'bold' in style or '700' in style:
            return True
    return False


def html_to_markdown(element, parent_is_bold=False):
    """将HTML元素转换为Markdown格式"""
    if element is None:
        return ""
    
    if hasattr(element, 'name'):
        if element.name in ['script', 'style']:
            return ""
        
        is_bold_tag = element.name in ['strong', 'b']
        has_bold_style_attr = has_bold_style(element)
        is_bold = is_bold_tag or has_bold_style_attr
        should_add_bold = is_bold and not parent_is_bold
        
        if element.name in ['p', 'section']:
            text = process_element_children(element, is_bold or parent_is_bold)
            text = text.strip()
            if should_add_bold and text:
                text = '**' + text + '**'
            return text + '\n\n' if text else ""
        
        if element.name == 'div':
            text = process_element_children(element, is_bold or parent_is_bold).strip()
            if should_add_bold and text:
                text = '**' + text + '**'
            return text + '\n\n' if text else ""
        
        if element.name in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
            level = int(element.name[1])
            text = process_element_children(element, parent_is_bold).strip()
            return '#' * level + ' ' + text + '\n\n' if text else ""
        
        if element.name == 'ul':
            items = []
            for li in element.find_all('li', recursive=False):
                item_text = process_element_children(li, parent_is_bold).strip()
                if item_text:
                    items.append('- ' + item_text)
            return '\n'.join(items) + '\n\n' if items else ""
        
        if element.name == 'ol':
            items = []
            for idx, li in enumerate(element.find_all('li', recursive=False), 1):
                item_text = process_element_children(li, parent_is_bold).strip()
                if item_text:
                    items.append(f'{idx}. ' + item_text)
            return '\n'.join(items) + '\n\n' if items else ""
        
        if element.name == 'li':
            return process_element_children(element, parent_is_bold)
        
        if element.name == 'br':
            return '\n'
        
        if element.name in ['strong', 'b']:
            text = process_element_children(element, True)
            text = ' '.join(text.split())
            if parent_is_bold:
                return text if text else ""
            return '**' + text + '**' if text else ""
        
        if element.name in ['em', 'i']:
            text = process_element_children(element, parent_is_bold)
            text = ' '.join(text.split())
            if has_bold_style_attr and not parent_is_bold:
                return '***' + text + '***' if text else ""
            return '*' + text + '*' if text else ""
        
        if element.name in ['span', 'label', 'cite', 'small', 'big', 'font']:
            text = process_element_children(element, is_bold or parent_is_bold)
            if has_bold_style_attr and not parent_is_bold:
                text = ' '.join(text.split())
                return '**' + text + '**' if text else ""
            return text
        
        if element.name == 'a':
            href = element.get('href', '')
            text = process_element_children(element, False)
            text = ' '.join(text.split())
            if href and text and not href.startswith('javascript:'):
                return '[' + text + '](' + href + ')'
            return text
        
        if element.name == 'img':
            src = element.get('data-src') or element.get('src', '')
            alt = element.get('alt', '图片')
            if src:
                return '\n![' + alt + '](' + src + ')\n'
            return ""
        
        if element.name == 'blockquote':
            text = process_element_children(element, parent_is_bold).strip()
            if text:
                lines = text.split('\n')
                quoted = '\n'.join(['> ' + line for line in lines if line.strip()])
                return quoted + '\n\n'
            return ""
        
        return process_element_children(element, parent_is_bold)
    
    if isinstance(element, str):
        return element
    
    return str(element)


def process_element_children(element, parent_is_bold=False):
    """处理元素的子元素"""
    if element is None:
        return ""
    
    parts = []
    for child in element.children:
        if isinstance(child, str):
            parts.append(child)
        else:
            md = html_to_markdown(child, parent_is_bold)
            parts.append(md)
    
    return ''.join(parts)


def clean_markdown_content(content):
    """清理Markdown内容"""
    # 规范化空行
    content = re.sub(r'\n{3,}', '\n\n', content)
    
    # ========== 第1步: 处理引号/括号包围的链接加粗（最复杂的嵌套情况）==========
    # 模式: **"[文字**](url)"** -> "[文字](url)"
    # 外层有**，引号内链接文字末尾也有**
    def clean_quoted_link(match):
        """清理引号包围的链接加粗"""
        quote_open = match.group(1)
        link_text = match.group(2)
        url = match.group(3)
        quote_close = match.group(4)
        # 去掉链接文字内部的 **
        link_text = re.sub(r'\*\*([^*]+?)\*\*', r'\1', link_text)
        return f'{quote_open}[{link_text}]({url}){quote_close}'
    
    # 匹配: **"[文字**](url)"**（链接文字末尾有**）
    content = re.sub(
        r'\*\*([""""「『【（])\[([^\*\]]+?)\*\*\]\(([^)]+)\)([""""」』】）])\*\*',
        clean_quoted_link,
        content
    )
    # 匹配: **"[文字](url)"**（链接文字无内部加粗）
    content = re.sub(
        r'\*\*([""""「『【（])\[([^\]]+)\]\(([^)]+)\)([""""」』】）])\*\*',
        clean_quoted_link,
        content
    )
    
    # ========== 第2步: 修复链接周围的加粗标记 ==========
    content = re.sub(r'\*\*([《\[「【（])\*\*', r'**\1', content)
    content = re.sub(r'\*\*([》\]」】）])\*\*', r'\1**', content)
    
    # ========== 第3步: 处理书名号包围的链接 ==========
    def clean_link_text(match):
        """清理链接文字内部的加粗标记"""
        link_text = match.group(1)
        url = match.group(2)
        link_text = re.sub(r'\*\*([^*]+?)\*\*', r'\1', link_text)
        return f'《[{link_text}]({url})》'
    
    content = re.sub(r'\*\*《\*\*\[([^\]]+)\]\(([^)]+)\)\*\*》\*\*', clean_link_text, content)
    content = re.sub(r'\*\*《\[([^\]]+)\]\(([^)]+)\)》\*\*', clean_link_text, content)
    
    # ========== 第4步: 处理普通链接周围的加粗 ==========
    def clean_plain_link(match):
        """清理普通链接文字内部的加粗标记"""
        link_text = match.group(1)
        url = match.group(2)
        link_text = re.sub(r'\*\*([^*]+?)\*\*', r'\1', link_text)
        return f'[{link_text}]({url})'
    
    content = re.sub(r'\*\*\[([^\]]+)\]\(([^)]+)\)\*\*', clean_plain_link, content)
    
    # 修复连续加粗
    prev_content = None
    while prev_content != content:
        prev_content = content
        content = re.sub(r'\*\*([^*\n]+?)\*\*\*\*([^*\n]+?)\*\*', r'**\1\2**', content)
    
    content = re.sub(r'\*{4,}', '**', content)
    
    # 修复加粗包含标点符号的问题
    # 核心逻辑：找到成对的 **...**，只处理后一个 ** 在句子结束标点后的情况
    # **文本。** -> **文本**。(正确)
    # **文本，** -> **文本，**(逗号保留在加粗内，不处理)
    
    def process_bold_pair(match):
        """处理成对加粗，只将句子结束标点移出"""
        text = match.group(1)
        
        # 检查文本末尾是否有句子结束标点（句号、问号、感叹号）
        # 注意：逗号、顿号等非句末标点应该保留在加粗内
        if re.search(r'[。．.！?？]+$', text):
            # 找到末尾的所有句子结束标点
            punct_match = re.search(r'([。．.！?？]+)$', text)
            if punct_match:
                punct = punct_match.group(1)
                text_without_punct = text[:-len(punct)]
                # 如果移除标点后还有内容，则将标点移到加粗外
                if text_without_punct:
                    return f'**{text_without_punct}**{punct}'
        
        # 保持原样
        return f'**{text}**'
    
    # 使用正则匹配成对的加粗：**文本**
    # 注意：这个匹配是贪婪的，确保找到完整的加粗对
    content = re.sub(r'\*\*([^*]+?)\*\*', process_bold_pair, content)
    
    # 将开头标点移出加粗 (书名号、引号等)
    content = re.sub(r'\*\*([《「【（\'"]+)([^*]+?)\*\*', r'\1**\2**', content)
    
    # 修复断开的加粗: **文本1**。**文本2** -> **文本1**。**文本2**
    # 这个修复处理因原HTML结构导致的错误断开的加粗
    prev_content = None
    while prev_content != content:
        prev_content = content
        # 处理被句号、问号、感叹号断开的加粗（保留标点在外面）
        content = re.sub(r'\*\*([^*]+?)\*\*([。．.！?？])\*\*([^*]+?)\*\*', r'**\1**\2**\3**', content)
    
    # 去除行尾空格
    content = '\n'.join(line.rstrip() for line in content.split('\n'))
    return content.strip()


# ==================== 图片下载处理 ====================

def download_image(img_url, save_path, session=None):
    """
    下载单张图片（如果文件已存在则跳过）

    Args:
        img_url: 图片URL
        save_path: 保存路径
        session: requests session对象

    Returns:
        (success: bool, local_path: str, is_existing: bool)
        - success: 是否成功
        - local_path: 本地路径
        - is_existing: 是否已存在（True表示文件已存在，跳过下载）
    """
    if session is None:
        session = requests.Session()

    try:
        # 确保保存目录存在
        save_path.parent.mkdir(parents=True, exist_ok=True)

        # 检查文件是否已存在
        if save_path.exists():
            logging.info(f"图片已存在，跳过下载: {save_path.name}")
            return True, str(save_path), True

        # 设置请求头
        headers = {
            "User-Agent": random.choice(USER_AGENTS),
            "Referer": "https://mp.weixin.qq.com/"
        }

        # 随机延时，防止被封
        time.sleep(random.uniform(IMG_MIN_DELAY, IMG_MAX_DELAY))

        # 下载图片
        response = session.get(img_url, headers=headers, timeout=30)
        response.raise_for_status()

        # 保存图片
        with open(save_path, 'wb') as f:
            f.write(response.content)

        return True, str(save_path), False
    except Exception as e:
        logging.warning(f"下载图片失败 {img_url}: {e}")
        return False, img_url, False


def extract_images_from_html(html_content, publish_time, article_title, images_dir=None):
    """
    从HTML正文中提取图片URL（只提取js_content内的图片）
    
    Args:
        html_content: HTML内容
        publish_time: 发布时间（用于目录命名）
        article_title: 文章标题（用于目录命名）
        images_dir: 图片保存目录（默认为全局IMAGES_DIR）
        
    Returns:
        list: [(原始URL, 本地保存路径), ...]
    """
    from bs4 import BeautifulSoup
    
    # 使用传入的目录或全局目录
    img_base_dir = images_dir if images_dir else IMAGES_DIR
    
    soup = BeautifulSoup(html_content, 'html.parser')
    images = []
    
    # 只查找正文内容区域
    content_elem = soup.find(id="js_content")
    if not content_elem:
        logging.warning(f"未找到正文内容，无法提取图片")
        return images
    
    # 创建文章专属图片目录（使用发布时间_文章名格式）
    safe_title = sanitize_filename(article_title) if article_title else ""
    # 确保有发布时间，如果没有则使用占位符，并清理非法字符
    if not publish_time:
        publish_time = "未知时间"
    safe_publish_time = sanitize_filename(publish_time)
    article_img_dir = img_base_dir / f"{safe_publish_time}_{safe_title}"
    
    # 只在正文区域内查找图片
    for img in content_elem.find_all('img'):
        # 获取图片URL（微信图片通常在data-src中）
        img_url = img.get('data-src') or img.get('src', '')
        
        if not img_url or img_url.startswith('data:'):
            continue
            
        # 跳过非微信域名的图片
        if not ('mmbiz.qpic.cn' in img_url or 'mmbizurl.cn' in img_url):
            continue
        
        # 生成本地文件名
        parsed_url = urlparse(img_url)
        # 从URL中提取文件名，如果没有则使用哈希
        url_path = parsed_url.path
        if '.' in url_path:
            ext = url_path.split('.')[-1].lower()
            if ext not in ['jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp']:
                ext = 'jpg'
        else:
            ext = 'jpg'
        
        # 使用URL的部分路径作为文件名
        filename = f"img_{len(images):03d}.{ext}"
        local_path = article_img_dir / filename
        
        images.append((img_url, local_path))
    
    return images


def process_images_for_article(html_content, md_content, session=None, publish_time="", article_title="", images_dir=None):
    """
    处理文章中的所有图片：下载并替换链接（已存在的图片会跳过下载）

    Args:
        html_content: HTML内容
        md_content: Markdown内容
        session: requests session对象
        publish_time: 发布时间（用于目录命名）
        article_title: 文章标题（用于目录命名）
        images_dir: 图片保存目录（默认为全局IMAGES_DIR）

    Returns:
        (new_html, new_md, downloaded_count)
    """
    if session is None:
        session = requests.Session()

    # 使用传入的目录或全局目录
    img_base_dir = images_dir if images_dir else IMAGES_DIR

    # 提取图片列表
    images = extract_images_from_html(html_content, publish_time, article_title, img_base_dir)

    if not images:
        return html_content, md_content, 0

    downloaded_count = 0
    skipped_count = 0
    url_mapping = {}  # 原始URL -> 本地相对路径

    # 下载所有图片
    for img_url, local_path in images:
        success, result_path, is_existing = download_image(img_url, local_path, session)
        if success:
            # 计算相对路径（相对于HTML/MD文件的位置）
            safe_title = sanitize_filename(article_title) if article_title else ""
            pt = publish_time if publish_time else "未知时间"
            safe_pt = sanitize_filename(pt)  # 清理发布时间中的非法字符
            # 使用当前图片目录的相对路径
            rel_path = f"../images/{safe_pt}_{safe_title}/{local_path.name}"
            url_mapping[img_url] = rel_path
            
            if is_existing:
                skipped_count += 1
                logging.info(f"图片已存在，跳过: {local_path.name}")
            else:
                downloaded_count += 1
                logging.info(f"下载图片: {local_path.name}")
        else:
            url_mapping[img_url] = img_url  # 失败则保留原链接

    # 如果有跳过的图片，记录一下
    if skipped_count > 0:
        logging.info(f"共跳过 {skipped_count} 张已存在的图片")

    # 替换HTML中的图片链接
    new_html = html_content
    for original_url, local_path in url_mapping.items():
        # 替换 data-src 和 src
        new_html = new_html.replace(f'data-src="{original_url}"', f'src="{local_path}"')
        new_html = new_html.replace(f'src="{original_url}"', f'src="{local_path}"')

    # 替换Markdown中的图片链接
    new_md = md_content
    for original_url, local_path in url_mapping.items():
        new_md = new_md.replace(original_url, local_path)

    return new_html, new_md, downloaded_count


# ==================== 文章抓取器 ====================

class ArticleFetcher:
    """文章抓取器"""
    
    def __init__(self):
        self.session = requests.Session()
        
        # 设置重试策略
        retry_strategy = Retry(
            total=MAX_RETRIES,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        
        # 默认headers - 模拟浏览器
        self.session.headers.update({
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Cache-Control": "max-age=0",
        })
        
        # 目录会在获取到公众号名称后动态创建
    
    def _load_local_html(self, article_num):
        """从本地加载HTML缓存文件"""
        # 优先读取缓存文件（用于断点续传）
        cache_path = HTML_SOURCE_DIR / f"{article_num}.cache.html"
        if cache_path.exists():
            try:
                with open(cache_path, 'r', encoding='utf-8') as f:
                    html = f.read()
                
                # 简单检查是否有内容
                if len(html) > 1000 and 'js_content' in html:
                    return html
                else:
                    logging.warning(f"[{article_num}] 本地缓存可能无效，将重新抓取")
                    return None
                    
            except Exception as e:
                logging.warning(f"读取本地缓存失败 {article_num}: {e}")
        return None
    
    def _save_html(self, article_num, html):
        """保存HTML到本地（用于断点续传的缓存）"""
        # 使用简化文件名，仅用于缓存
        html_path = HTML_SOURCE_DIR / f"{article_num}.cache.html"
        try:
            with open(html_path, 'w', encoding='utf-8') as f:
                f.write(html)
            return True
        except Exception as e:
            logging.warning(f"保存HTML缓存失败 {article_num}: {e}")
            return False
    
    def fetch_article(self, url, article_num=None, csv_publish_time=""):
        """
        抓取文章
        
        Args:
            url: 文章URL
            article_num: 文章编号
            csv_publish_time: CSV中记录的发布时间（作为备用）
        
        Returns:
            (article_data, error_message)
        """
        from bs4 import BeautifulSoup
        
        # 1. 检查本地缓存
        if article_num:
            html = self._load_local_html(article_num)
            if html:
                logging.info(f"[{article_num}] 从本地HTML加载")
                result, error = self._parse_html(html, url, csv_publish_time)
                if result:
                    result['raw_html'] = html
                return result, error
        
        # 2. 网络请求
        logging.info(f"[{article_num}] 正在抓取: {url[:60]}...")
        
        try:
            # 随机延迟
            delay = random.uniform(MIN_DELAY, MAX_DELAY)
            time.sleep(delay)
            
            # 更新User-Agent
            self.session.headers["User-Agent"] = random.choice(USER_AGENTS)
            
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            response.encoding = 'utf-8'
            
            html = response.text
            
            # 检查是否被封
            if "访问频繁" in html or "验证码" in html or "Please verify" in html:
                return None, "检测到访问限制"
            
            # 检查是否有内容
            if 'js_content' not in html:
                return None, "页面没有文章内容"
            
            # 保存HTML
            if article_num:
                self._save_html(article_num, html)
                logging.info(f"[{article_num}] HTML已保存")
            
            result, error = self._parse_html(html, url, csv_publish_time)
            if result:
                result['raw_html'] = html  # 保存原始HTML
            return result, error
            
        except Exception as e:
            return None, f"抓取失败: {e}"
    
    def _parse_html(self, html, url, csv_publish_time=""):
        """解析HTML内容"""
        from bs4 import BeautifulSoup
        
        soup = BeautifulSoup(html, 'html.parser')
        
        # 提取标题
        title_elem = soup.find(id="activity_name") or soup.find(class_="rich_media_title")
        title = title_elem.get_text(strip=True) if title_elem else "未知标题"
        
        # 优先使用CSV中的发布时间
        publish_time = ""
        if csv_publish_time:
            publish_time = csv_publish_time
            logging.info(f"  使用CSV中的发布时间: {publish_time}")
        
        # 如果CSV没有，才从HTML中提取
        if not publish_time:
            time_selectors = [
                '#publish_time',
                'em#publish_time',
                '#js_publish_time',
                '.rich_media_meta_list em',
                '#js_content > div:first-child em',
                '.rich_media_content + div em'
            ]
            for selector in time_selectors:
                time_elem = soup.select_one(selector)
                if time_elem:
                    publish_time = time_elem.get_text(strip=True)
                    if publish_time:
                        logging.info(f"  从HTML提取发布时间: {publish_time}")
                        break
            
            # 如果还是没有找到，尝试从文本中匹配日期格式
            if not publish_time:
                import re
                date_patterns = [
                    r'(\d{4})[-/](\d{1,2})[-/](\d{1,2})',
                    r'(\d{4})年(\d{1,2})月(\d{1,2})日'
                ]
                for pattern in date_patterns:
                    for match in re.finditer(pattern, html):
                        year = int(match.group(1))
                        month = int(match.group(2))
                        day = int(match.group(3))
                        # 年份过滤：只接受 2010-2030 年的日期
                        if 2010 <= year <= 2030 and 1 <= month <= 12 and 1 <= day <= 31:
                            publish_time = f"{year}-{month:02d}-{day:02d}"
                            logging.info(f"  从HTML文本匹配发布时间: {publish_time}")
                            break
                    if publish_time:
                        break
        
        # 提取正文内容
        content_elem = soup.find(id="js_content")
        if not content_elem:
            return None, "未找到文章内容"

        # 清理
        for elem in content_elem.find_all(['script', 'style']):
            elem.decompose()

        # 转换为Markdown
        content_text = html_to_markdown(content_elem)
        content_text = clean_markdown_content(content_text)

        return {
            "title": title,
            "publish_time": publish_time,
            "nickname": current_nickname,  # 使用从CSV获取的公众号名称
            "content_text": content_text,
            "url": url
        }, None


# ==================== Markdown生成 ====================

def sanitize_filename(filename):
    """清理文件名"""
    filename = re.sub(r'[<>"/\\|?*]', '-', filename)
    filename = filename.strip('. ')
    if len(filename) > 100:
        filename = filename[:100]
    return filename


def update_output_dirs(nickname):
    """
    根据公众号名称更新输出目录
    缓存文件跟随公众号目录存放
    
    Args:
        nickname: 公众号名称
    """
    global HTML_SOURCE_DIR, HTML_DIR, MD_DIR, IMAGES_DIR, current_nickname
    
    if not nickname or nickname == current_nickname:
        return
    
    # 清理公众号名称，作为目录名
    safe_nickname = sanitize_filename(nickname)
    if not safe_nickname:
        safe_nickname = "未知公众号"
    
    current_nickname = nickname
    
    # 更新目录路径：OUTPUT_DIR/公众号名称/子目录
    base_dir = OUTPUT_DIR / safe_nickname
    HTML_SOURCE_DIR = base_dir / "cache"  # 缓存放在各自公众号目录下
    HTML_DIR = base_dir / "html"
    MD_DIR = base_dir / "md"
    IMAGES_DIR = base_dir / "images"
    
    # 确保目录存在
    HTML_SOURCE_DIR.mkdir(parents=True, exist_ok=True)
    HTML_DIR.mkdir(parents=True, exist_ok=True)
    MD_DIR.mkdir(parents=True, exist_ok=True)
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    
    logging.info(f"  已切换到公众号目录: {safe_nickname}")


def save_as_markdown(article_title, article_data, publish_time):
    """保存文章为Markdown格式"""
    safe_title = sanitize_filename(article_title)
    # 使用发布时间_文章名格式，必须保证有发布时间
    if not publish_time:
        publish_time = "未知时间"
        logging.warning(f"文章 '{article_title[:30]}...' 没有发布时间，使用 '未知时间'")
    # 清理发布时间中的非法字符（如 / 会被当作路径分隔符）
    safe_publish_time = sanitize_filename(publish_time)
    filename = f"{safe_publish_time}_{safe_title}.md"
    filepath = MD_DIR / filename
    
    content = article_data['content_text']
    
    md_content = f"""# {article_data['title']}

> 来源: {article_data['nickname']}

> 发布时间: {article_data['publish_time']}

> 原文链接: {article_data.get('url', '')}

---

{content}

---

*本文抓取时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*
"""
    
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(md_content)
        return True
    except Exception as e:
        logging.error(f"保存Markdown失败: {e}")
        return False


def save_extracted_html(article_title, html_content, url, publish_time, nickname=None):
    """提取并保存可见的HTML内容（js_content显示版本）"""
    from bs4 import BeautifulSoup

    safe_title = sanitize_filename(article_title)
    # 使用发布时间_文章名格式，必须保证有发布时间
    if not publish_time:
        publish_time = "未知时间"
        logging.warning(f"文章 '{article_title[:30]}...' 没有发布时间，使用 '未知时间'")
    # 清理发布时间中的非法字符（如 / 会被当作路径分隔符）
    safe_publish_time = sanitize_filename(publish_time)
    filename = f"{safe_publish_time}_{safe_title}.html"
    filepath = HTML_DIR / filename
    
    # 使用传入的公众号名称或全局变量
    article_nickname = nickname if nickname else current_nickname
    
    try:
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # 提取标题
        title_elem = soup.find(id="activity_name") or soup.find(class_="rich_media_title")
        title = title_elem.get_text(strip=True) if title_elem else article_title
        
        # 提取发布时间（尝试多种选择器）
        publish_time = ""
        time_selectors = [
            '#publish_time',
            'em#publish_time',
            '#js_publish_time',
            '.rich_media_meta_list em',
            '#js_content > div:first-child em',
            '.rich_media_content + div em'
        ]
        for selector in time_selectors:
            time_elem = soup.select_one(selector)
            if time_elem:
                publish_time = time_elem.get_text(strip=True)
                if publish_time:
                    break
        
        # 如果还是没有找到，尝试从文本中匹配日期格式
        if not publish_time:
            date_patterns = [
                r'(\d{4}[-/]\d{1,2}[-/]\d{1,2})',
                r'(\d{4}年\d{1,2}月\d{1,2}日)'
            ]
            for pattern in date_patterns:
                match = re.search(pattern, html_content)
                if match:
                    publish_time = match.group(1)
                    break

        # 提取正文内容
        content_elem = soup.find(id="js_content")
        if not content_elem:
            logging.warning(f"未找到文章内容")
            return None
        
        # 清理内容中的script和style
        for elem in content_elem.find_all(['script', 'style']):
            elem.decompose()
        
        # 获取HTML字符串并进行全局清理
        content_html = str(content_elem)
        
        # 移除所有隐藏样式（全局正则替换）
        content_html = re.sub(r'visibility\s*:\s*[^;"]+;?', '', content_html, flags=re.IGNORECASE)
        content_html = re.sub(r'opacity\s*:\s*[^;"]+;?', '', content_html, flags=re.IGNORECASE)
        content_html = re.sub(r'display\s*:\s*none;?', '', content_html, flags=re.IGNORECASE)
        
        # 移除内部重复的 id="js_content"
        # 保留最外层的id，移除内部的
        content_html = re.sub(r'(<div[^>]*id="js_content"[^>]*>.*?)id="js_content"', r'\1', content_html, flags=re.DOTALL)
        
        # 移除特定的class
        content_html = re.sub(r'class="[^"]*rich_media_content[^"]*"', '', content_html)
        content_html = re.sub(r'class="[^"]*js_underline_content[^"]*"', '', content_html)
        content_html = re.sub(r'class="[^"]*autoTypeSetting24psection[^"]*"', '', content_html)
        
        # 清理多余的空格
        content_html = re.sub(r'\s+', ' ', content_html)
        content_html = re.sub(r'>\s<', '><', content_html)
        
        # 构建可见的HTML文档
        visible_html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, "Noto Sans", sans-serif;
            line-height: 1.8;
            max-width: 800px;
            margin: 0 auto;
            padding: 40px 20px;
            color: #333;
            background: #fff;
        }}
        .article-header {{
            margin-bottom: 30px;
            padding-bottom: 20px;
            border-bottom: 1px solid #eee;
        }}
        .article-title {{
            font-size: 24px;
            font-weight: bold;
            margin-bottom: 15px;
            line-height: 1.4;
            color: #000;
        }}
        .article-meta {{
            color: #666;
            font-size: 14px;
        }}
        .article-meta p {{
            margin: 5px 0;
        }}
        #js_content {{
            font-size: 16px;
            visibility: visible !important;
            display: block !important;
        }}
        #js_content p {{
            margin: 1em 0;
            text-align: justify;
        }}
        #js_content img {{
            max-width: 100%;
            height: auto;
            display: block;
            margin: 20px auto;
        }}
        #js_content strong, #js_content b {{
            font-weight: bold;
        }}
        #js_content em, #js_content i {{
            font-style: italic;
        }}
        #js_content a {{
            color: #576b95;
            text-decoration: none;
        }}
        #js_content blockquote {{
            border-left: 4px solid #ccc;
            margin: 1em 0;
            padding-left: 16px;
            color: #666;
        }}
        #js_content span {{
            display: inline;
        }}
        .article-footer {{
            margin-top: 40px;
            padding-top: 20px;
            border-top: 1px solid #eee;
            color: #999;
            font-size: 12px;
            text-align: center;
        }}
        section {{
            margin-top: 0;
            margin-bottom: 24px;
        }}
    </style>
</head>
<body>
    <div class="article-header">
        <h1 class="article-title">{title}</h1>
        <div class="article-meta">
            <p><strong>来源:</strong> {article_nickname}</p>
            <p><strong>发布时间:</strong> {publish_time}</p>
            <p><strong>原文链接:</strong> <a href="{url}" target="_blank">{url}</a></p>
        </div>
    </div>
    <div>
        {content_html}
    </div>
    <div class="article-footer">
        <p>本文抓取时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
    </div>
</body>
</html>"""
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(visible_html)
        
        return filepath, visible_html
        
    except Exception as e:
        logging.error(f"保存提取HTML失败: {e}")
        return None, None





# ==================== 进度管理 ====================

class ProgressManager:
    """进度管理器"""
    
    def __init__(self, progress_file):
        self.progress_file = progress_file
        self.completed = set()
        self.failed = {}
        self.skipped = set()
        self._load()
    
    def _load(self):
        """加载进度"""
        if self.progress_file.exists():
            try:
                with open(self.progress_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.completed = set(data.get('completed', []))
                    self.failed = data.get('failed', {})
                    self.skipped = set(data.get('skipped', []))
            except:
                pass
    
    def save(self):
        """保存进度"""
        try:
            with open(self.progress_file, 'w', encoding='utf-8') as f:
                json.dump({
                    'completed': list(self.completed),
                    'failed': self.failed,
                    'skipped': list(self.skipped)
                }, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logging.error(f"保存进度失败: {e}")
    
    def is_completed(self, num):
        return str(num) in self.completed
    
    def mark_completed(self, num):
        self.completed.add(str(num))
        if str(num) in self.failed:
            del self.failed[str(num)]
        self.save()
    
    def mark_failed(self, num, error):
        self.failed[str(num)] = error
        self.save()
    
    def get_stats(self):
        return {
            'completed': len(self.completed),
            'failed': len(self.failed),
            'skipped': len(self.skipped)
        }


# ==================== 主函数 ====================

def main():
    """主函数"""
    global HTML_SOURCE_DIR, HTML_DIR, MD_DIR, IMAGES_DIR
    
    logger = setup_logging()
    logger.info("=" * 60)
    logger.info("微信公众号文章批量抓取脚本启动")
    logger.info("=" * 60)
    
    # 加载文章列表
    articles = load_articles()
    if not articles:
        logger.error("没有找到文章列表，请先生成 articles_full.json")
        return 1
    
    logger.info(f"共加载 {len(articles)} 篇文章")
    
    # 初始化
    progress = ProgressManager(PROGRESS_FILE)
    fetcher = ArticleFetcher()
    
    stats = progress.get_stats()
    logger.info(f"当前进度: 已完成 {stats['completed']}, 失败 {stats['failed']}")
    
    try:
        for i, article in enumerate(articles, 1):
            num = article.get('num', '')
            title = article.get('title', '未知标题')
            url = article.get('url', '')
            
            # 如果 CSV 中没有序号，抛出错误停止运行
            if not num:
                logger.error(f"第 {i} 行文章 '{title[:50]}...' 没有序号，请检查CSV文件")
                raise ValueError(f"第 {i} 行缺少序号")
            
            if not url:
                logger.warning(f"[{num}] 跳过: 没有URL")
                continue
            
            # 检查是否已完成
            if progress.is_completed(num):
                logger.info(f"[{num}] 跳过: 已完成")
                continue
            
            logger.info(f"\n[{num}] ({i}/{len(articles)}) {title[:50]}...")
            
            # 根据CSV中的公众号名称提前设置保存目录
            csv_nickname = article.get('nickname', '')
            if csv_nickname:
                update_output_dirs(csv_nickname)
            
            # 抓取文章（传入CSV中的发布时间作为备用）
            csv_publish_time = article.get('publish_time', '')
            article_data, error = fetcher.fetch_article(url, article_num=num, csv_publish_time=csv_publish_time)
            
            if error:
                logger.error(f"  抓取失败: {error}")
                progress.mark_failed(num, error)
                continue
            
            # 处理图片（下载并替换链接）
            img_count = 0
            if article_data.get('raw_html'):
                processed_html, processed_md, img_count = process_images_for_article(
                    article_data['raw_html'],
                    article_data['content_text'],
                    fetcher.session,
                    article_data.get('publish_time', ''),
                    article_data.get('title', ''),
                    IMAGES_DIR  # 传递当前公众号的图片目录
                )
                article_data['content_text'] = processed_md
                article_data['processed_html'] = processed_html
                if img_count > 0:
                    logger.info(f"  下载了 {img_count} 张图片")

            # 保存Markdown
            md_success = save_as_markdown(article_data['title'], article_data, article_data.get('publish_time', ''))
            if md_success:
                logger.info(f"  Markdown已保存")

            # 保存提取的可见HTML（js_content显示版本，用于阅读）
            if article_data.get('raw_html'):
                html_to_save = article_data.get('processed_html', article_data['raw_html'])
                visible_path, _ = save_extracted_html(article_data['title'], html_to_save, url, article_data.get('publish_time', ''), article_data.get('nickname', ''))
                if visible_path:
                    logger.info(f"  可见HTML已保存")
            
            # 标记完成
            if md_success:
                progress.mark_completed(num)
            else:
                logger.error(f"  保存失败")
                progress.mark_failed(num, "保存失败")
        
        # 最终统计
        final_stats = progress.get_stats()
        logger.info("\n" + "=" * 60)
        logger.info("抓取完成!")
        logger.info(f"总计: {len(articles)} 篇")
        logger.info(f"成功: {final_stats['completed']} 篇")
        logger.info(f"失败: {final_stats['failed']} 篇")
        logger.info("=" * 60)
        
    except KeyboardInterrupt:
        logger.info("\n用户中断，进度已保存")
    except Exception as e:
        logger.exception(f"发生错误: {e}")
    
    return 0


if __name__ == "__main__":
    exit(main())
