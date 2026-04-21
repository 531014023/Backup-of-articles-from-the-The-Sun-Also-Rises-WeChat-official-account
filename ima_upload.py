#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import sys
import argparse
import csv
import shutil
import requests
from pathlib import Path

# ========== 配置（从环境变量读取） ==========
SCRIPT_DIR = Path(__file__).parent.absolute()
PROJECT_DIR = os.environ.get('PROJECT_DIR', str(SCRIPT_DIR))
ARTICLE_CSV_FILE = os.environ.get('ARTICLES_CSV_FILE', str(SCRIPT_DIR / 'articles_with_publish_date.csv'))
OUTPUT_DIR = os.environ.get('OUTPUT_DIR', str(SCRIPT_DIR / 'backup'))

# IMA 凭证（从 ~/.config/ima/ 读取）
ima_config_path = os.path.expanduser('~/.config/ima/')
with open(os.path.join(ima_config_path, 'client_id')) as f:
    IMA_CLIENT_ID = f.read().strip()
with open(os.path.join(ima_config_path, 'api_key')) as f:
    IMA_API_KEY = f.read().strip()

headers = {
    'ima-openapi-clientid': IMA_CLIENT_ID,
    'ima-openapi-apikey': IMA_API_KEY,
    'Content-Type': 'application/json; charset=utf-8'
}

# ========== 解析命令行参数 ==========
parser = argparse.ArgumentParser(description='上传微信文章到 IMA 知识库')
parser.add_argument('keyword', nargs='?', help='文章标题关键字（可选，默认使用环境变量 ARTICLE_KEYWORD）')
args = parser.parse_args()

# ========== 步骤1：从 CSV 读取最新公众号名 ==========
# 优先使用命令行参数，其次环境变量
article_keyword = args.keyword or os.environ.get('ARTICLE_KEYWORD', '')
account_name = None
article_title = None

with open(ARTICLE_CSV_FILE, 'r', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    for row in reader:
        # 跳过没有公众号名的旧数据
        if not row.get('公众号'):
            continue
        # 第一行就是最新的文章
        account_name = row['公众号']
        article_title = row['文章名']
        print(f'检测到公众号: {account_name}')
        print(f'文章标题: {article_title}')
        break

if not account_name:
    print('错误: CSV 中未找到公众号信息')
    exit(1)

# ========== 步骤2：从 IMA API 获取 KB_ID ==========
print('获取知识库列表...')
resp = requests.post('https://ima.qq.com/openapi/wiki/v1/search_knowledge_base',
                     headers=headers, json={"query": "", "cursor": "", "limit": 20})
data = resp.json()
if data.get('code') != 0:
    print('获取知识库失败:', data)
    exit(1)

kb_list = data.get('data', {}).get('info_list', [])
KB_ID = None
for kb in kb_list:
    # 匹配公众号名（知识库名可能包含"文章备份"等后缀）
    kb_name = kb.get('kb_name', '')
    if account_name in kb_name or kb_name in account_name:
        KB_ID = kb.get('kb_id')
        print(f'匹配到知识库: {kb_name} (ID: {KB_ID})')
        break

if not KB_ID:
    print(f'错误: 未找到与公众号 "{account_name}" 匹配的知识库')
    print('可用的知识库:', [kb.get('kb_name') for kb in kb_list])
    exit(1)

# ========== 步骤3：从 IMA API 获取 MD 文件夹的 folder_id ==========
print('获取文件夹列表...')
resp = requests.post('https://ima.qq.com/openapi/wiki/v1/get_knowledge_list',
                     headers=headers, json={"knowledge_base_id": KB_ID, "cursor": "", "limit": 50})
data = resp.json()
if data.get('code') != 0:
    print('获取文件夹失败:', data)
    exit(1)

knowledge_list = data.get('data', {}).get('knowledge_list', [])
FOLDER_ID = None
for item in knowledge_list:
    # 文件夹的 media_type 是 99
    if item.get('media_type') == 99 and item.get('title', '').lower() == 'md':
        FOLDER_ID = item.get('media_id')
        print(f'找到 md 文件夹: ID = {FOLDER_ID}')
        break

if not FOLDER_ID:
    print('错误: 未找到 md 文件夹，请先在知识库中创建 md 文件夹')
    exit(1)

# ========== 步骤4：找到并复制源文件 ==========
SRC_DIR = os.path.join(OUTPUT_DIR, account_name, 'md')
files = [f for f in os.listdir(SRC_DIR) if article_keyword in f]
if not files:
    print(f'未找到包含关键字 "{article_keyword}" 的文件')
    exit(1)

src_file = os.path.join(SRC_DIR, files[0])
correct_filename = files[0]
temp_file = os.path.join(SRC_DIR, 'temp_upload.md')
shutil.copy(src_file, temp_file)
print(f'准备上传: {correct_filename}')

# ========== 步骤5：create_media ==========
body = {
    'file_name': correct_filename,
    'file_size': os.path.getsize(temp_file),
    'content_type': 'text/markdown',
    'knowledge_base_id': KB_ID,
    'file_ext': 'md'
}
resp = requests.post('https://ima.qq.com/openapi/wiki/v1/create_media',
                    headers=headers, json=body)
data = resp.json()
if data.get('code') != 0:
    print('create_media 失败:', data)
    os.remove(temp_file)
    exit(1)

cos_credential = data['data']['cos_credential']
media_id = data['data']['media_id']

# ========== 步骤6：cos-upload ==========
cos_script = os.path.expanduser('~/.claude/skills/ima-skill/knowledge-base/scripts/cos-upload.cjs')
cos_cmd = (
    f'node "{cos_script}" --file "{temp_file}" '
    f'--secret-id "{cos_credential["secret_id"]}" '
    f'--secret-key "{cos_credential["secret_key"]}" '
    f'--token "{cos_credential["token"]}" '
    f'--bucket "{cos_credential["bucket_name"]}" '
    f'--region "{cos_credential["region"]}" '
    f'--cos-key "{cos_credential["cos_key"]}" '
    f'--content-type "text/markdown" '
    f'--start-time "{cos_credential["start_time"]}" '
    f'--expired-time "{cos_credential["expired_time"]}"'
)
os.system(cos_cmd)

# ========== 步骤7：add_knowledge ==========
body = {
    'media_type': 7,
    'media_id': media_id,
    'title': correct_filename,
    'knowledge_base_id': KB_ID,
    'folder_id': FOLDER_ID,
    'file_info': {
        'cos_key': cos_credential['cos_key'],
        'file_size': os.path.getsize(temp_file),
        'file_name': correct_filename
    }
}
resp = requests.post('https://ima.qq.com/openapi/wiki/v1/add_knowledge',
                    headers=headers, json=body)
print('add_knowledge 结果:', resp.json())

# ========== 步骤8：清理 ==========
os.remove(temp_file)
print('上传完成！')
print(f'\n使用示例:')
print(f'  python ima_upload.py "文章标题关键字"')
print(f'  python ima_upload.py  # 使用环境变量 ARTICLE_KEYWORD')