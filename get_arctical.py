import re

import requests
import json
import os
import time
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
from PyPDF2 import PdfMerger
import yaml

class Spider:
    ZSXQ_ACCESS_TOKEN = ''          # 登录后Cookie中的Token（必须修改）
    USER_AGENT = ''                 # 登录时使用的User-Agent（必须修改）
    GROUP_ID = ''                   # 知识星球中的小组ID
    COLUMN_ID = ''                 # 知识星球中的专栏ID（可选）不选则下载所有专栏
    SLEEP_FLAG = True               # 请求之间是否SLEEP避免请求过于频繁
    SLEEP_SEC = 5                   # SLEEP秒数 SLEEP_FLAG=True时生效

    # ---
    columns = []

    def __init__(self, access_token=None, user_agent=None, group_id=None, column_id=None):
        self.ZSXQ_ACCESS_TOKEN = access_token or self.ZSXQ_ACCESS_TOKEN
        self.USER_AGENT = user_agent or self.USER_AGENT
        self.GROUP_ID = group_id or self.GROUP_ID
        self.COLUMN_ID = column_id or self.COLUMN_ID
        self.headers = {
            'Cookie': 'abtest_env=product;zsxq_access_token=' + self.ZSXQ_ACCESS_TOKEN,
            'User-Agent': self.USER_AGENT,
            'accept': 'application/json, text/plain, */*',
            'sec-ch-ua-platform': '"Windows"',
            'origin': 'https://wx.zsxq.com',
            'sec-fetch-site': 'same-site',
            'sec-fetch-mode': 'cors',
            'sec-fetch-dest': 'empty',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua': '" Not A;Brand";v="99", "Chromium";v="98", "Google Chrome";v="98"',
            'referer': 'https://wx.zsxq.com/',
            'dnt': '1',
        }

    def sanitize_filename(self, filename):
        # 将常见非法字符替换为全角或安全字符
        filename = filename.replace('?', '？')  # 半角 → 全角
        filename = filename.replace(':', '：')
        filename = filename.replace('/', '_')
        filename = filename.replace('>', '》')
        filename = filename.replace('<', '《')
        return filename.strip()

    def get_url_data(self, url):
        rsp = requests.get(url, headers=self.headers)
        # 检查HTTP状态码
        if rsp.status_code != 200:
            raise Exception(f'HTTP请求失败，状态码: {rsp.status_code}')

        # 检查Content-Type
        content_type = rsp.headers.get('content-type', '').lower()
        if 'application/json' not in content_type:
            return rsp.text

        rsp_data = rsp.json()

        if not rsp_data.get('succeeded'):
            if rsp_data.get('code') == 1059:
                if self.SLEEP_FLAG:
                    time.sleep(self.SLEEP_SEC)
                return self.get_url_data(url)
            raise Exception('访问错误：\n' + json.dumps(rsp_data, indent=2, ensure_ascii=False))
        else:
            return rsp_data.get('resp_data')

    def generate_merge_pdf(self, dir_name):
        """
        dir_name: html所在目录 /html/星球导读
        将目录下的所有html使用playwright生成pdf，并合并为一个pdf
        """
        html_files = os.listdir(os.path.join('html', dir_name))
        html_files = [f for f in html_files if f.endswith('.html')]
        html_files.sort(key=lambda x: int(x.split('-')[0]))
        output_dir = 'pdf'
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
        if not os.path.exists(os.path.join(output_dir, dir_name)):
            os.makedirs(os.path.join(output_dir, dir_name))
        for html_file in html_files:
            file_name = html_file.split('.')[0]
            if os.path.exists(os.path.join(output_dir, dir_name, f'{file_name}.pdf')):
                print(f"已存在PDF: {file_name}.pdf")
                continue
            html_file = os.path.join('html', dir_name, html_file)
            with open(html_file, 'r', encoding='utf-8') as file:
                html_content = file.read()
            with sync_playwright() as p:
                browser = p.chromium.launch()
                page = browser.new_page()
                page.set_content(html_content)
                page.pdf(
                    path=os.path.join(output_dir, dir_name, f'{file_name}.pdf'),
                    format="A4",
                    print_background=True  # 添加这个选项以包含背景样式
                )
                browser.close()
            print(f"已生成PDF: {file_name}.pdf")
            # 如果存在嵌套
            html_file_dir = os.path.join('html', dir_name, file_name)
            if os.path.exists(html_file_dir):
                self.generate_merge_pdf(os.path.join(dir_name, file_name))
                merger = PdfMerger()
                merger.append(os.path.join(output_dir, dir_name, f'{file_name}.pdf'), outline_item=file_name)
                merger.append(os.path.join(output_dir, dir_name, file_name, f'{file_name}.pdf'))
                merger.write(os.path.join(output_dir, dir_name, f'{file_name}.pdf'))
                merger.close()
                print(f"嵌套成功")

        if os.path.exists(os.path.join(output_dir, dir_name, os.path.basename(dir_name)+'.pdf')):
            print(f"电子书 {dir_name}.pdf 已存在，跳过合并")
            return
        # 合并pdf
        merger = PdfMerger()
        pdf_files = os.listdir(os.path.join(output_dir, dir_name))
        pdf_files = [f for f in pdf_files if f.endswith('.pdf')]
        # 过滤掉结果文件
        pdf_files = [f for f in pdf_files if f != os.path.basename(dir_name) + '.pdf']
        # 按文件名-前缀数字排序
        pdf_files.sort(key=lambda x: int(x.split('-')[0]))

        # 记录每个文件的标题（可从文件名或HTML内容提取）
        for pdf_file in pdf_files:
            file_path = os.path.join(output_dir, dir_name, pdf_file)
            # 提取标题：比如把 01-第一章.html -> “第一章”
            title = "-".join(pdf_file.split('-')[1:]).replace('.pdf', '')
            title = title.strip()
            # 添加PDF，并创建书签
            merger.append(file_path, outline_item=title)

        # 输出最终PDF
        output_pdf_path = os.path.join(output_dir, dir_name, os.path.basename(dir_name)+'.pdf')
        merger.write(output_pdf_path)
        merger.close()
        print(f"电子书 {dir_name}.pdf 生成成功，包含书签目录！")

    def replace_local_assets_with_online(self, html_content):
        # 替换 CSS 文件：将 ./css/xxx.css → https://articles.zsxq.com/css/xxx.css
        html_content = re.sub(
            r'href=["\'](\.\./|\.?/)css/([^"\']+)["\']',
            r'href="https://articles.zsxq.com/css/\2"',
            html_content
        )

        # 替换 JS 文件：将 ./js/xxx.js → https://articles.zsxq.com/js/xxx.js
        html_content = re.sub(
            r'src=["\'](\.\./|\.?/)js/([^"\']+)["\']',
            r'src="https://articles.zsxq.com/js/\2"',
            html_content
        )

        # 替换图片：将 ./assets_dweb/xxx.png → https://articles.zsxq.com/assets_dweb/xxx.png
        html_content = re.sub(
            r'src=["\'](\.\./|\.?/)assets_dweb/([^"\']+)["\']',
            r'src="https://articles.zsxq.com/assets_dweb/\2"',
            html_content
        )

        # 替换图片：将 /favicon.ico → https://articles.zsxq.com/favicon.ico
        html_content = re.sub(
            r'href=["\']/favicon\.ico["\']',
            r'src="https://articles.zsxq.com/favicon.ico"',
            html_content
        )

        return html_content

    def run(self):
        columns_url = 'https://api.zsxq.com/v2/groups/' + self.GROUP_ID + '/columns'
        self.columns = self.get_url_data(columns_url).get('columns')
        # 遍历所有专栏
        column_index = 0
        if self.COLUMN_ID != '':
            # 如果指定了专栏ID，则只处理该专栏
            column_index = next(
                (i for i, col in enumerate(self.columns) if str(col['column_id']) == self.COLUMN_ID),
                None
            )
            self.columns = [self.columns[column_index]]
        for column in self.columns:
            column_id = column['column_id']
            column_name = column['name']
            topics_num = column['statistics']['topics_count']
            topics_url = f'https://api.zsxq.com/v2/groups/{self.GROUP_ID}/columns/{column_id}/topics?count={topics_num}'
            topics = self.get_url_data(topics_url).get('topics')
            # 遍历专栏下的所有文章
            topic_index = 0
            for topic in topics:
                topic_id = topic['topic_id']
                topic_title = self.sanitize_filename(
                    topic.get('title') or topic.get('text')
                )
                if os.path.exists('html/' + str(column_index) + '-' + column_name + '/' + str(topic_index) + '-' + topic_title + '.html'):
                    print(f'已存在文章：{topic_index}-{topic_title}.html')
                    topic_index += 1
                    continue

                topic_url = f'https://api.zsxq.com/v2/topics/{topic_id}/info'
                topic_data = self.get_url_data(topic_url).get('topic')
                article_url = topic_data['talk']['article']['article_url']
                article_html = self.get_url_data(article_url)
                # 修改html需要从本地加载的css和js改成从线上加载
                article_html = self.replace_local_assets_with_online(article_html)
                # html删除qrcode-container标签
                soup = BeautifulSoup(article_html , 'html.parser')

                # 查找并删除 class 为 'qrcode-container' 的 div
                qrcode_div = soup.find('div', class_='qrcode-container')
                if qrcode_div:
                    qrcode_div.decompose()  # 删除整个元素及其子元素

                # 查找并删除 type 为 'hidden' 的 input
                hidden_inputs = soup.find_all('input', type='hidden')
                for input_tag in hidden_inputs:
                    input_tag.decompose()

                # 查找并删除 class 为 'milkdown-preview' 的 div
                milkdown_div = soup.find('div', class_='milkdown-preview')
                if milkdown_div:
                    milkdown_div.decompose()

                # 找出<div class="ql-snow">中或子元素中的所有<a href="https://articles.zsxq.com/xxx.html" url链接
                ql_snow_div = soup.find('div', class_='ql-snow')
                href_urls = []
                if ql_snow_div:
                    for a_tag in ql_snow_div.find_all('a', href=True):
                        href = a_tag['href']
                        # 如果链接是本地的，替换为线上链接
                        if href.startswith('https://articles.zsxq.com/'):
                            href_urls.append(href)

                # 输出清理后的 HTML
                article_html = str(soup)

                # 保存文章HTML
                if not os.path.exists('html'):
                    os.makedirs('html')
                if not os.path.exists('html/' + str(column_index) + '-' + column_name):
                    os.makedirs('html/' + str(column_index) + '-' + column_name)
                file_name = f'html/{column_index}-{column_name}/{topic_index}-{topic_title}.html'

                # 如果存在嵌套
                if len(href_urls) > 0:
                    # 创建目录
                    if not os.path.exists(f'html/{column_index}-{column_name}/{topic_index}-{topic_title}'):
                        os.makedirs(f'html/{column_index}-{column_name}/{topic_index}-{topic_title}')
                    # 保存嵌套的HTML
                    for i, href in enumerate(href_urls):
                        if os.path.exists(f'html/{column_index}-{column_name}/{topic_index}-{topic_title}/{i}-{i}.html'):
                            print(f"已存在嵌套文章：{column_index}-{column_name}/{topic_index}-{topic_title}/{i}-{i}.html")
                            continue
                        nested_html = self.get_url_data(href)
                        nested_html = self.replace_local_assets_with_online(nested_html)
                        soup = BeautifulSoup(nested_html , 'html.parser')
                        # 查找并删除 class 为 'qrcode-container' 的 div
                        qrcode_div = soup.find('div', class_='qrcode-container')
                        if qrcode_div:
                            qrcode_div.decompose()
                        # 查找并删除 class 为 'milkdown-preview' 的 div
                        milkdown_div = soup.find('div', class_='milkdown-preview')
                        if milkdown_div:
                            milkdown_div.decompose()
                        nested_html = str(soup)
                        nested_file_name = f'html/{column_index}-{column_name}/{topic_index}-{topic_title}/{i}-{i}.html'
                        with open(nested_file_name, 'w+', encoding='utf-8') as f:
                            f.write(nested_html)
                        print(f"已保存嵌套文章：{nested_file_name} - {i}")

                topic_index += 1
                with open(file_name, 'w+', encoding='utf-8') as f:
                    f.write(article_html)
            # 生成专栏的PDF
            self.generate_merge_pdf(str(column_index)+'-'+column_name)
            column_index += 1



if __name__ == '__main__':
    # 读取配置文件
    with open('config.yaml', 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    spider_config = config['spider']

    _ = Spider(
        access_token=spider_config['zsxq_access_token'],
        user_agent=spider_config['user_agent'],
        group_id=spider_config['group_id'],
        column_id=spider_config.get('column_id', '')
    )
    _.run()
