#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微信公众号文章链接解析工具
- 解析文章链接获取标题和发布时间
- 自动更新CSV文件，新文章放在开头，序号倒序
"""

import os
import re
import sys
import csv
import time
import random
import requests
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse

# CSV文件路径
SCRIPT_DIR = Path(__file__).parent.absolute()
CSV_FILE = SCRIPT_DIR / "articles_with_publish_date.csv"

# User-Agent列表
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
]


def fetch_article_info(url):
    """
    抓取文章信息（标题、发布时间和公众号名称）
    
    Args:
        url: 文章URL
    
    Returns:
        (title, publish_time, nickname, error)
    """
    try:
        headers = {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Referer": "https://mp.weixin.qq.com/",
        }
        
        # 添加随机延迟
        time.sleep(random.uniform(0.5, 1.5))
        
        response = requests.get(url, headers=headers, timeout=30)
        response.encoding = 'utf-8'
        html = response.text
        
        # 检查是否被限制
        if "访问频繁" in html or "验证码" in html or "Please verify" in html:
            return None, None, None, "检测到访问限制，请稍后再试"
        
        # 检查页面内容
        if 'js_content' not in html:
            return None, None, None, "页面没有文章内容，链接可能已失效"
        
        # 提取标题
        title = "未知标题"
        # 尝试多种标题提取方式
        title_patterns = [
            r'<h1[^>]*class="rich_media_title[^"]*"[^>]*>(.*?)</h1>',
            r'<h2[^>]*class="rich_media_title[^"]*"[^>]*>(.*?)</h2>',
            r'<h1[^>]*id="activity_name"[^>]*>(.*?)</h1>',
            r'<h1[^>]*>(.*?)</h1>',
            r'var msg_title = [\'"]([^\'"]+)[\'"]',
            r'window\.__INITIAL_STATE__.*?"activityTitle":"([^"]+)"',
        ]
        for pattern in title_patterns:
            match = re.search(pattern, html, re.DOTALL | re.IGNORECASE)
            if match:
                title = match.group(1).strip()
                # 清理HTML标签
                title = re.sub(r'<[^>]+>', '', title).strip()
                if title:
                    break
        
        # 提取发布时间
        publish_time = ""
        # 尝试多种时间提取方式
        time_patterns = [
            r'<em[^>]*id="publish_time"[^>]*>(.*?)</em>',
            r'<em[^>]*id="js_publish_time"[^>]*>(.*?)</em>',
            r'var s = "(\d{4}-\d{2}-\d{2})"',
            r'var publish_time = [\'"]([^\'"]+)[\'"]',
            r's="(\d{4}-\d{2}-\d{2})"',
            r'"publishTime":"(\d{4}-\d{2}-\d{2})',
            r'(\d{4})年(\d{1,2})月(\d{1,2})日',
            r'(\d{4})[-/](\d{1,2})[-/](\d{1,2})',
        ]
        for pattern in time_patterns:
            match = re.search(pattern, html)
            if match:
                time_str = match.group(0)
                # 如果是年-月-日格式
                year_match = re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日', time_str)
                if year_match:
                    publish_time = f"{year_match.group(1)}-{int(year_match.group(2)):02d}-{int(year_match.group(3)):02d}"
                    break
                # 如果是 YYYY-MM-DD 格式
                date_match = re.search(r'(\d{4})-(\d{2})-(\d{2})', time_str)
                if date_match:
                    year = int(date_match.group(1))
                    # 年份过滤
                    if 2010 <= year <= 2030:
                        publish_time = date_match.group(0)
                        break
        
        # 如果还是没找到，从URL参数中尝试
        if not publish_time:
            # 某些微信文章URL包含时间戳
            ts_match = re.search(r'ts=(\d{10})', url)
            if ts_match:
                ts = int(ts_match.group(1))
                publish_time = datetime.fromtimestamp(ts).strftime('%Y-%m-%d')
        
        # 提取公众号名称
        nickname = "未知公众号"
        nickname_patterns = [
            r'<a[^>]*id="js_name"[^>]*>(.*?)</a>',
            r'<span[^>]*class="profile_nickname"[^>]*>(.*?)</span>',
            r'<div[^>]*class="profile_nickname"[^>]*>(.*?)</div>',
            r'var nickname = [\'"]([^\'"]+)[\'"]',
            r'"nick_name":"([^"]+)"',
        ]
        for pattern in nickname_patterns:
            match = re.search(pattern, html, re.DOTALL | re.IGNORECASE)
            if match:
                nickname = match.group(1).strip()
                # 清理HTML标签
                nickname = re.sub(r'<[^>]+>', '', nickname).strip()
                if nickname:
                    break
        
        return title, publish_time, nickname, None
        
    except requests.exceptions.Timeout:
        return None, None, None, "请求超时，请检查网络连接"
    except requests.exceptions.ConnectionError:
        return None, None, None, "网络连接错误"
    except Exception as e:
        return None, None, None, f"抓取失败: {str(e)}"


def load_csv():
    """加载CSV文件内容"""
    articles = []
    max_num = 0
    
    if not CSV_FILE.exists():
        return articles, max_num
    
    try:
        with open(CSV_FILE, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                num = int(row.get('序号', 0)) if row.get('序号', '').isdigit() else 0
                if num > max_num:
                    max_num = num
                articles.append({
                    'num': num,
                    'title': row.get('文章名', ''),
                    'publish_time': row.get('发布时间', ''),
                    'nickname': row.get('公众号', ''),  # 兼容旧数据
                    'url': row.get('URL', '')
                })
    except Exception as e:
        print(f"读取CSV文件出错: {e}")
    
    return articles, max_num


def save_csv(articles):
    """保存文章列表到CSV"""
    try:
        with open(CSV_FILE, 'w', encoding='utf-8-sig', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['序号', '文章名', '发布时间', '公众号', 'URL'])
            for article in articles:
                writer.writerow([
                    article['num'],
                    article['title'],
                    article['publish_time'],
                    article.get('nickname', ''),  # 公众号名称
                    article['url']
                ])
        return True
    except Exception as e:
        print(f"保存CSV文件失败: {e}")
        return False


def add_article(url):
    """
    添加新文章到CSV
    
    Args:
        url: 文章链接
    """
    print(f"\n文章链接: {url}")
    print("-" * 50)
    
    # 验证URL格式
    if not url.startswith('https://mp.weixin.qq.com/'):
        print("错误: 请输入有效的微信公众号文章链接")
        print("   链接格式应为: https://mp.weixin.qq.com/s/...")
        return False
    
    # 加载现有数据
    articles, max_num = load_csv()
    print(f"当前共有 {len(articles)} 篇文章，最大序号为 {max_num}")
    
    # 检查是否已存在
    for article in articles:
        if article['url'] == url:
            print(f"该文章已存在于列表中 (序号: {article['num']})")
            print(f"   标题: {article['title']}")
            print(f"   发布时间: {article['publish_time']}")
            return False
    
    # 抓取文章信息
    print("\n正在解析文章信息...")
    title, publish_time, nickname, error = fetch_article_info(url)
    
    if error:
        print(f"错误: {error}")
        return False
    
    # 显示获取到的信息
    print(f"\n解析成功!")
    print(f"   标题: {title}")
    print(f"   发布时间: {publish_time if publish_time else '未识别'}")
    print(f"   公众号: {nickname}")
    
    # 如果没有获取到发布时间，询问用户
    if not publish_time:
        user_time = input("\n未能自动识别发布时间，请手动输入 (格式: YYYY-MM-DD): ").strip()
        if user_time:
            # 验证日期格式
            if re.match(r'\d{4}-\d{2}-\d{2}', user_time):
                publish_time = user_time
            else:
                print("日期格式不正确，使用今天的日期")
                publish_time = datetime.now().strftime('%Y-%m-%d')
        else:
            publish_time = datetime.now().strftime('%Y-%m-%d')
    
    # 创建新文章记录
    new_num = max_num + 1
    new_article = {
        'num': new_num,
        'title': title,
        'publish_time': publish_time,
        'nickname': nickname,  # 公众号名称
        'url': url
    }
    
    # 插入到开头（新文章序号最大，放在最前面，CSV展示为倒序）
    articles.insert(0, new_article)
    
    # 保存到CSV（不重新编号，序号是固定ID）
    if save_csv(articles):
        print(f"\n文章已添加到CSV文件")
        print(f"   新序号: {new_num}")
        print(f"   总文章数: {len(articles)}")
        return True
    else:
        return False


def main():
    """主函数"""
    print("=" * 60)
    print("微信公众号文章链接解析工具")
    print("=" * 60)
    
    # 检查命令行参数
    if len(sys.argv) > 1:
        url = sys.argv[1]
        add_article(url)
    else:
        # 交互模式
        print("\n请输入微信公众号文章链接 (或输入 'q' 退出):")
        while True:
            try:
                user_input = input("\n> ").strip()
                
                if user_input.lower() in ('q', 'quit', 'exit'):
                    print("\n再见!")
                    break
                
                if not user_input:
                    continue
                
                add_article(user_input)
                
            except KeyboardInterrupt:
                print("\n\n再见!")
                break
            except EOFError:
                break


if __name__ == "__main__":
    main()
