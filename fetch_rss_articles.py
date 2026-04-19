#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RSS订阅文章自动拉取脚本
- 从RSS API获取最新文章列表
- 解析并与CSV对比，找出新文章
- 自动更新CSV
- 调用fetch脚本抓取
- 调用git提交push
- 调用ima脚本上传
"""

import os
import re
import sys
import csv
import json
import time
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse

import requests

# ========== 加载环境变量配置 ==========

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


# ========== 配置区域 ==========
SCRIPT_DIR = Path(__file__).parent.absolute()
CSV_FILE = SCRIPT_DIR / "articles_with_publish_date.csv"
PROGRESS_FILE = SCRIPT_DIR / "progress.json"
FETCH_SCRIPT = SCRIPT_DIR / "fetch_weixin_articles.py"
UPLOAD_SCRIPT = SCRIPT_DIR / "ima_upload.py"

# RSS API地址（基础URL从环境变量读取，路径固定）
RSS_BASE_URL = os.environ.get('RSS_BASE_URL', 'http://192.168.3.100:12005')
RSS_URL = f"{RSS_BASE_URL}/feed/MP_WXS_3248194593.rss"

# 请求配置
TIMEOUT = 30
RETRY_COUNT = 3


def fetch_rss_content():
    """获取RSS内容"""
    print(f"正在获取RSS内容: {RSS_URL}")
    
    for attempt in range(RETRY_COUNT):
        try:
            response = requests.get(RSS_URL, timeout=TIMEOUT)
            response.raise_for_status()
            response.encoding = 'utf-8'
            return response.text
        except requests.exceptions.Timeout:
            print(f"请求超时，重试 {attempt + 1}/{RETRY_COUNT}")
            time.sleep(1)
        except Exception as e:
            print(f"请求失败: {e}")
            time.sleep(1)
    
    return None


def parse_rss(xml_content):
    """
    解析RSS XML内容
    
    返回:
        list: [{title, link, guid, pub_date, nickname}, ...]
    """
    if not xml_content:
        return []
    
    articles = []
    
    try:
        root = ET.fromstring(xml_content)
        
        # 获取channel信息
        channel = root.find('.//channel')
        if channel is None:
            print("错误: 未找到channel元素")
            return []
        
        # 获取公众号名称
        nickname = "未知公众号"
        title_elem = channel.find('title')
        if title_elem is not None and title_elem.text:
            nickname = title_elem.text.strip()
        
        # 解析每个item
        for item in channel.findall('.//item'):
            article = {
                'title': '',
                'link': '',
                'guid': '',
                'pub_date': '',
                'nickname': nickname
            }
            
            # 文章标题
            title_elem = item.find('title')
            if title_elem is not None and title_elem.text:
                article['title'] = title_elem.text.strip()
            
            # 微信公众号链接
            link_elem = item.find('link')
            if link_elem is not None and link_elem.text:
                article['link'] = link_elem.text.strip()
            
            # GUID（用作唯一标识，也是文章链接）
            guid_elem = item.find('guid')
            if guid_elem is not None and guid_elem.text:
                article['guid'] = guid_elem.text.strip()
            
            # 发布日期
            pub_date_elem = item.find('pubDate')
            if pub_date_elem is not None and pub_date_elem.text:
                # 解析RSS日期格式，如 "Fri, 18 Apr 2026 12:30:00 GMT"
                pub_date_str = pub_date_elem.text.strip()
                try:
                    # 尝试解析标准RSS日期格式
                    parsed_date = datetime.strptime(pub_date_str, '%a, %d %b %Y %H:%M:%S %Z')
                    article['pub_date'] = parsed_date.strftime('%Y-%m-%d')
                except ValueError:
                    # 尝试其他格式
                    try:
                        parsed_date = datetime.strptime(pub_date_str, '%a, %d %b %Y %H:%M:%S %z')
                        article['pub_date'] = parsed_date.strftime('%Y-%m-%d')
                    except ValueError:
                        # 使用原始字符串
                        article['pub_date'] = pub_date_str
            
            # 如果title或link为空，使用guid作为备选
            if not article['link'] and article['guid']:
                article['link'] = article['guid']
            
            # 只添加有效的文章
            if article['title'] and article['link']:
                articles.append(article)
        
    except ET.ParseError as e:
        print(f"解析XML失败: {e}")
        return []
    except Exception as e:
        print(f"解析RSS时出错: {e}")
        return []
    
    return articles


def load_csv_articles():
    """加载CSV中的文章列表"""
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
                    'nickname': row.get('公众号', ''),
                    'url': row.get('URL', '')
                })
    except Exception as e:
        print(f"读取CSV文件出错: {e}")
    
    return articles, max_num


def find_new_articles(rss_articles, csv_articles):
    """
    找出RSS中有但CSV中没有的新文章
    
    返回:
        list: 新文章列表
    """
    # 获取CSV中所有文章的URL集合
    csv_urls = {article['url'] for article in csv_articles}
    
    new_articles = []
    for rss_article in rss_articles:
        if rss_article['link'] not in csv_urls:
            new_articles.append(rss_article)
    
    return new_articles


def save_to_csv(csv_articles, new_articles, max_num):
    """
    将新文章添加到CSV
    
    Args:
        csv_articles: 现有CSV文章列表
        new_articles: 新文章列表（RSS格式）
        max_num: 当前最大序号
    
    Returns:
        list: 新文章的序号列表
    """
    new_nums = []
    
    # 将新文章转换为CSV格式并添加序号
    for i, article in enumerate(new_articles, 1):
        max_num += 1
        new_nums.append(max_num)
        csv_articles.insert(0, {
            'num': max_num,
            'title': article['title'],
            'publish_time': article['pub_date'],
            'nickname': article['nickname'],
            'url': article['link']
        })
    
    try:
        with open(CSV_FILE, 'w', encoding='utf-8-sig', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['序号', '文章名', '发布时间', '公众号', 'URL'])
            for article in csv_articles:
                writer.writerow([
                    article['num'],
                    article['title'],
                    article['publish_time'],
                    article.get('nickname', ''),
                    article['url']
                ])
        return new_nums
    except Exception as e:
        print(f"保存CSV文件失败: {e}")
        return []


def check_progress_before_fetch(new_article_nums):
    """
    在抓取前检查进度文件，判断是否需要执行抓取
    
    Args:
        new_article_nums: 新文章序号列表
    
    Returns:
        dict: {
            'all_completed': bool,  # 是否全部已完成
            'pending_nums': [待抓取的序号列表]
        }
    """
    if not PROGRESS_FILE.exists():
        # 进度文件不存在，全部都需要抓取
        return {'all_completed': False, 'pending_nums': new_article_nums}
    
    try:
        with open(PROGRESS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        completed = set(data.get('completed', []))
        
        # 检查哪些新文章还未完成
        pending_nums = []
        for num in new_article_nums:
            if str(num) not in completed:
                pending_nums.append(num)
        
        all_completed = len(pending_nums) == 0
        
        if all_completed:
            print(f"\n所有新文章（{new_article_nums}）已在进度文件中标记为完成，无需抓取")
        else:
            print(f"\n待抓取文章: {pending_nums}，已完成: {set(new_article_nums) - set(pending_nums)}")
        
        return {'all_completed': all_completed, 'pending_nums': pending_nums}
        
    except Exception as e:
        print(f"检查进度文件失败: {e}，将继续执行抓取")
        return {'all_completed': False, 'pending_nums': new_article_nums}


def run_fetch_script(new_article_nums):
    """
    运行fetch脚本抓取文章，并分析执行结果
    
    Args:
        new_article_nums: 新文章序号列表
    
    Returns:
        dict: {
            'success': [成功抓取的序号列表],
            'skipped': [跳过的序号列表],
            'failed': [失败的序号列表],
            'should_continue': bool  # 是否继续执行后续步骤
        }
    """
    print("\n开始抓取文章...")
    
    result_data = {
        'success': [],
        'skipped': [],
        'failed': [],
        'should_continue': False
    }
    
    try:
        # 切换到脚本目录执行
        result = subprocess.run(
            [sys.executable, str(FETCH_SCRIPT)],
            cwd=str(SCRIPT_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,  # 合并stderr到stdout
            text=True,
            encoding='utf-8'
        )
        
        output = result.stdout
        print(output)
        
        # 解析fetch脚本的输出
        # 格式示例:
        # [474] (1/472) 为什么相信川普就会被打脸...
        # [474] 从本地HTML加载
        #   Markdown已保存  <- 注意：前面没有序号
        #   可见HTML已保存  <- 注意：前面没有序号
        # [473] 跳过: 已完成
        # [472] 抓取失败: 页面没有文章内容
        
        # 按行分析，追踪当前处理的序号
        current_num = None
        lines = output.splitlines()  # 自动处理 \n 和 \r\n
        
        for line in lines:
            # 检查是否是新的文章开始行（形如 [数字]）
            num_match = re.search(r'\[(\d+)\]', line)
            if num_match:
                num = int(num_match.group(1))
                if num in new_article_nums:
                    current_num = num
                    
                    # 检查当前行是否包含跳过或失败信息
                    if '跳过:' in line:
                        result_data['skipped'].append(num)
                        current_num = None
                    elif '抓取失败' in line:
                        result_data['failed'].append(num)
                        current_num = None
            
            # 检查是否成功（Markdown已保存 / 可见HTML已保存）
            if current_num and ('Markdown已保存' in line or '可见HTML已保存' in line):
                if current_num not in result_data['success']:
                    result_data['success'].append(current_num)
            
            # 如果当前行包含失败信息（可能没有序号前缀）
            if current_num and '抓取失败' in line and 'INFO' not in line:
                if current_num not in result_data['failed']:
                    result_data['failed'].append(current_num)
        
        # 判断是否应该继续
        # 1. 如果所有新文章都被跳过，说明已经抓取过了，不需要执行后续步骤
        # 2. 如果有任何失败，停止执行
        # 3. 只要有成功的，就继续执行后续步骤
        
        if result_data['failed']:
            print(f"\n错误: 以下文章抓取失败: {result_data['failed']}")
            result_data['should_continue'] = False
        elif len(result_data['skipped']) == len(new_article_nums):
            print(f"\n所有新文章都已存在，无需执行后续步骤")
            result_data['should_continue'] = False
        elif result_data['success']:
            print(f"\n成功抓取 {len(result_data['success'])} 篇文章")
            result_data['should_continue'] = True
        else:
            # 无法确定状态，默认不继续
            print(f"\n警告: 无法确定文章抓取状态")
            result_data['should_continue'] = False
        
        return result_data
        
    except Exception as e:
        print(f"运行fetch脚本失败: {e}")
        result_data['should_continue'] = False
        return result_data


def git_commit_and_push(new_articles):
    """提交并推送git更改"""
    print("\n开始Git提交...")
    
    try:
        # 添加所有变更（包括CSV和新抓取的文章）
        subprocess.run(
            ['git', 'add', '.'],
            cwd=str(SCRIPT_DIR),
            capture_output=True
        )
        
        # 构建提交信息：feat: 添加微信文章 2026-04-16 本公号强力完成初步转型
        if new_articles:
            # 取最新的一篇文章信息
            latest = new_articles[0]
            commit_msg = f"feat: 添加微信文章 {latest['pub_date']} {latest['title']}"
        else:
            commit_msg = f"feat: 添加微信文章 {datetime.now().strftime('%Y-%m-%d')}"
        
        result = subprocess.run(
            ['git', 'commit', '-m', commit_msg],
            cwd=str(SCRIPT_DIR),
            capture_output=True,
            text=True
        )
        
        if result.returncode != 0 and 'nothing to commit' not in result.stdout.lower():
            print(f"Git提交警告: {result.stderr}")
        else:
            print("Git提交成功")
        
        # 推送
        result = subprocess.run(
            ['git', 'push'],
            cwd=str(SCRIPT_DIR),
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0:
            print("Git推送成功")
            return True
        else:
            print(f"Git推送失败: {result.stderr}")
            return False
            
    except Exception as e:
        print(f"Git操作失败: {e}")
        return False


def upload_to_ima(article_title):
    """上传文章到IMA"""
    print(f"\n开始上传文章到IMA: {article_title}")
    
    try:
        # 设置环境变量
        env = os.environ.copy()
        env['ARTICLE_KEYWORD'] = article_title
        
        result = subprocess.run(
            [sys.executable, str(UPLOAD_SCRIPT)],
            cwd=str(SCRIPT_DIR),
            capture_output=True,
            text=True,
            encoding='utf-8',
            env=env
        )
        
        print(result.stdout)
        if result.stderr:
            print(result.stderr)
        
        return result.returncode == 0
    except Exception as e:
        print(f"上传文章失败: {e}")
        return False


def main():
    """主函数"""
    print("=" * 60)
    print("RSS文章自动拉取工具")
    print("=" * 60)
    
    # 1. 获取RSS内容
    rss_content = fetch_rss_content()
    if not rss_content:
        print("错误: 无法获取RSS内容")
        return 1
    
    print("RSS内容获取成功")
    
    # 2. 解析RSS
    rss_articles = parse_rss(rss_content)
    if not rss_articles:
        print("错误: 未解析到任何文章")
        return 1
    
    print(f"RSS中共有 {len(rss_articles)} 篇文章")
    
    # 3. 加载CSV
    csv_articles, max_num = load_csv_articles()
    print(f"CSV中已有 {len(csv_articles)} 篇文章")
    
    # 4. 找出新文章
    new_articles = find_new_articles(rss_articles, csv_articles)
    
    if not new_articles:
        print("\n没有发现新文章，无需更新")
        return 0
    
    print(f"\n发现 {len(new_articles)} 篇新文章:")
    for article in new_articles:
        print(f"  - [{article['pub_date']}] {article['title']}")
    
    # 5. 更新CSV
    new_article_nums = save_to_csv(csv_articles, new_articles, max_num)
    if new_article_nums:
        print(f"\nCSV文件已更新，新增 {len(new_article_nums)} 篇文章")
    else:
        print("\n错误: CSV更新失败")
        return 1
    
    # 6. 抓取前检查进度文件
    progress_check = check_progress_before_fetch(new_article_nums)
    
    if progress_check['all_completed']:
        # 所有新文章都已完成，直接跳过所有后续步骤
        print("\n所有文章已抓取完成，无需执行后续步骤")
        return 0
    
    # 运行fetch脚本抓取文章（只抓未完成的）
    fetch_result = run_fetch_script(new_article_nums)
    
    # 根据抓取结果决定是否继续
    if not fetch_result['should_continue']:
        if fetch_result['failed']:
            print("\n抓取失败，停止执行后续步骤")
            return 1
        else:
            print("\n所有文章已存在，无需执行后续步骤")
            return 0
    
    # 7. Git提交推送
    git_commit_and_push(new_articles)
    
    # 8. 上传到IMA（只上传成功抓取的文章）
    print("\n开始上传到IMA知识库...")
    # 获取成功抓取的文章序号
    success_nums = set(fetch_result['success'])
    
    # 从后往前遍历（new_articles和new_article_nums顺序对应）
    for i, article in enumerate(new_articles):
        article_num = new_article_nums[i]
        # 只上传成功抓取的文章
        if article_num in success_nums:
            upload_to_ima(article['title'])
            time.sleep(1)  # 避免请求过快
    
    print("\n" + "=" * 60)
    print("处理完成!")
    print(f"新增文章数: {len(new_articles)}")
    print("=" * 60)
    
    return 0


if __name__ == "__main__":
    exit(main())
