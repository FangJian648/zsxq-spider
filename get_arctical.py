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
    THEME_ID = ''                   # 知识星球中的话题的主题ID（可选）不选则下载所有专题
    DOWNLOAD_TYPE = 'pdf'          # 下载类型 column | file
    SLEEP_FLAG = True               # 请求之间是否SLEEP避免请求过于频繁
    SLEEP_SEC = 5                   # SLEEP秒数 SLEEP_FLAG=True时生效

    # ---
    columns = []

    def __init__(self, access_token=None, user_agent=None, group_id=None, column_id=None, theme_id=None, download_type=None):
        self.ZSXQ_ACCESS_TOKEN = access_token or self.ZSXQ_ACCESS_TOKEN
        self.USER_AGENT = user_agent or self.USER_AGENT
        self.GROUP_ID = group_id or self.GROUP_ID
        self.COLUMN_ID = column_id or self.COLUMN_ID
        self.THEME_ID = theme_id or self.THEME_ID
        self.DOWNLOAD_TYPE = download_type or self.DOWNLOAD_TYPE
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

    def generate_merge_pdf(self, dir_name, save_dir='zsxq_column_pdf', base_dir='zsxq_column_html'):
        """
        dir_name: html所在目录 /html/星球导读
        将目录下的所有html使用playwright生成pdf，并合并为一个pdf
        """
        try:
            html_files = os.listdir(os.path.join(base_dir, dir_name))
        except FileNotFoundError:
            print(f"目录不存在: {base_dir}/{dir_name}")
            return
        html_files = [f for f in html_files if f.endswith('.html')]
        html_files.sort(key=lambda x: int(x.split('-')[0]))
        output_dir = save_dir
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
        if not os.path.exists(os.path.join(output_dir, dir_name)):
            os.makedirs(os.path.join(output_dir, dir_name))
        for html_file in html_files:
            file_name = html_file.split('.')[0]
            if os.path.exists(os.path.join(output_dir, dir_name, f'{file_name}.pdf')):
                print(f"已存在PDF: {file_name}.pdf")
                continue
            html_file = os.path.join(base_dir, dir_name, html_file)
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
            html_file_dir = os.path.join(base_dir, dir_name, file_name)
            if os.path.exists(html_file_dir):
                self.generate_merge_pdf(os.path.join(dir_name, file_name), save_dir=save_dir, base_dir=base_dir)
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

    def get_zsxq_article(self, topic_id, index, column=None, download_dir='zsxq_column_html'):
        topic_url = f'https://api.zsxq.com/v2/topics/{topic_id}/info'
        topic_data = self.get_url_data(topic_url).get('topic')
        topic_title = self.sanitize_filename(
            topic_data.get('title') or topic_data.get('text')
        )
        try:
            article_url = topic_data['talk']['article']['article_url']
        except KeyError:
            print('error')
            print(topic_url)
            return 0
        article_html = self.get_url_data(article_url)
        # 修改html需要从本地加载的css和js改成从线上加载
        article_html = self.replace_local_assets_with_online(article_html)
        # html删除qrcode-container标签
        soup = BeautifulSoup(article_html, 'html.parser')

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
        if not os.path.exists(download_dir):
            os.makedirs(download_dir)
        if column is not None:
            column_name = column
        else:
            column_name = str(topic_id)
        if not os.path.exists(os.path.join(download_dir, column_name)):
            os.makedirs(os.path.join(download_dir, column_name))
        file_name = f'{download_dir}/{column_name}/{index}-{topic_title}.html'

        # 如果存在嵌套
        if len(href_urls) > 0:
            # 创建目录
            if not os.path.exists(f'{download_dir}/{column_name}/{index}-{topic_title}'):
                os.makedirs(f'{download_dir}/{column_name}/{index}-{topic_title}')
            # 保存嵌套的HTML
            for i, href in enumerate(href_urls):
                if os.path.exists(
                        f'{download_dir}/{column_name}/{index}-{topic_title}/{i}-{i}.html'):
                    print(
                        f"已存在嵌套文章：{topic_id}/{index}-{topic_title}/{i}-{i}.html")
                    continue
                nested_html = self.get_url_data(href)
                nested_html = self.replace_local_assets_with_online(nested_html)
                soup = BeautifulSoup(nested_html, 'html.parser')
                # 查找并删除 class 为 'qrcode-container' 的 div
                qrcode_div = soup.find('div', class_='qrcode-container')
                if qrcode_div:
                    qrcode_div.decompose()
                # 查找并删除 class 为 'milkdown-preview' 的 div
                milkdown_div = soup.find('div', class_='milkdown-preview')
                if milkdown_div:
                    milkdown_div.decompose()
                nested_html = str(soup)
                nested_file_name = f'{download_dir}/{column_name}/{index}-{topic_title}/{i}-{i}.html'
                with open(nested_file_name, 'w+', encoding='utf-8') as f:
                    f.write(nested_html)
                print(f"已保存嵌套文章：{nested_file_name} - {i}")

        with open(file_name, 'w+', encoding='utf-8') as f:
            f.write(article_html)

        return 1

    def get_zsxq_columns(self):
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
                success=self.get_zsxq_article(topic['topic_id'], topic_index, str(column_index) + '-' + column_name)
                if success==1:
                    topic_index += 1

            # 生成专栏的PDF
            self.generate_merge_pdf(str(column_index) + '-' + column_name)
            column_index += 1

    def get_zsxq_files(self):
        # 检查是否存在目录zsxq——files，不存在则创建
        if not os.path.exists('zsxq-files'):
            os.makedirs('zsxq-files')
        files_api_first = 'https://api.zsxq.com/v2/groups/' + self.GROUP_ID + '/files?count=20&sort=by_download_count'
        files_data = self.get_url_data(files_api_first)
        index = files_data.get('index')
        if index is None:
            print("下载完成")
            return
        while True:
            files = files_data.get('files')
            for file in files:
                file_id = file.get('file').get('file_id')
                file_name = self.sanitize_filename(file.get('file').get('name'))
                file_path = os.path.join('zsxq-files', file_name)
                if os.path.exists(file_path):
                    print(f'文件已存在，跳过下载：{file_name}')
                    continue
                download_url_api = 'https://api.zsxq.com/v2/files/' + str(file_id) + '/download_url'
                download_url = self.get_url_data(download_url_api).get('download_url')
                # 下载文件到zsxq-files目录
                with requests.get(download_url, headers=self.headers, stream=True) as r:
                    r.raise_for_status()
                    with open(file_path, 'wb') as f:
                        for chunk in r.iter_content(chunk_size=8192):
                            f.write(chunk)
            print("已下载文件20个")
            files_api = 'https://api.zsxq.com/v2/groups/'+self.GROUP_ID+'/files?count=20&index='+str(index)+'&sort=by_download_count'
            files_data = self.get_url_data(files_api)
            index = files_data.get('index')
            if index is None:
                print("下载完成")
                return

    def get_zsxq_topics(self):
        tags_api = 'https://api.zsxq.com/v2/groups/'+self.GROUP_ID+'/topics/digests/hashtags?type=default'
        tags_data = self.get_url_data(tags_api).get('hashtags')
        index=0
        tag_index=0
        if self.THEME_ID != '':
            # 如果指定了专题ID，则只处理该专题
            tag_index = next(
                (i for i, tag in enumerate(tags_data) if str(tag['hashtag_id']) == self.THEME_ID),
                None
            )
            tags_data = [tags_data[tag_index]]
        for tag in tags_data:
            tag_name = tag.get('title')
            tag_num = tag.get('topics_count')
            tag_hash = tag.get('hashtag_id')
            topics_api = f'https://api.zsxq.com/v2/groups/{self.GROUP_ID}/topics/digests?sort=by_create_time&direction=desc&index={index}&count=30&hashtag_id={tag_hash}'
            topics_data = self.get_url_data(topics_api)
            index = topics_data.get('index')
            topics = topics_data.get('topics')
            topic_index = 0
            for topic in topics:
                title = topic.get('title')
                topic_id = topic.get('topic_id')
                success = self.get_zsxq_article(topic_id, topic_index, str(tag_index) + '-' + tag_name, download_dir='zsxq_topic_html')
                if success == 1:
                    topic_index += 1
            # 生成专题的PDF
            self.generate_merge_pdf(str(tag_index) + '-' + tag_name, save_dir='zsxq_topic_pdf', base_dir='zsxq_topic_html')
            tag_index += 1


    def run(self):
        if self.DOWNLOAD_TYPE == 'column':
            self.get_zsxq_columns()
        elif self.DOWNLOAD_TYPE == 'file':
            self.get_zsxq_files()
        elif self.DOWNLOAD_TYPE == 'topic':
            self.get_zsxq_topics()
        else:
            print('下载类型错误，请选择 column 或 file')




if __name__ == '__main__':
    # 读取配置文件
    with open('config.yaml', 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    spider_config = config['spider']

    _ = Spider(
        access_token=spider_config['zsxq_access_token'],
        user_agent=spider_config['user_agent'],
        group_id=spider_config['group_id'],
        column_id=spider_config.get('column_id', ''),
        theme_id=spider_config.get('theme_id', ''),
        download_type=spider_config.get('download_type', 'file')
    )
    _.run()
