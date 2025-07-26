from datetime import datetime
from datetime import timedelta
import os
import logging

import pendulum

from weread2notionpro.weread_api import WeReadApi
from weread2notionpro.notion_helper import NotionHelper
from weread2notionpro.utils import (
    format_date,
    get_date,
    get_icon,
    get_number,
    get_relation,
    get_title,
)

# 设置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

HEATMAP_GUIDE = "https://mp.weixin.qq.com/s?__biz=MzI1OTcxOTI4NA==&mid=2247484145&idx=1&sn=81752852420b9153fc292b7873217651&chksm=ea75ebeadd0262fc65df100370d3f983ba2e52e2fcde2deb1ed49343fbb10645a77570656728&token=157143379&lang=zh_CN#rd"


def insert_to_notion(page_id, timestamp, duration):
    """插入或更新阅读时间到Notion"""
    parent = {"database_id": notion_helper.day_database_id, "type": "database_id"}
    properties = {
        "标题": get_title(
            format_date(
                datetime.utcfromtimestamp(timestamp) + timedelta(hours=8),
                "%Y年%m月%d日",
            )
        ),
        "日期": get_date(
            start=format_date(datetime.utcfromtimestamp(timestamp) + timedelta(hours=8))
        ),
        "时长": get_number(duration),
        "时间戳": get_number(timestamp),
        "年": get_relation(
            [
                notion_helper.get_year_relation_id(
                    datetime.utcfromtimestamp(timestamp) + timedelta(hours=8)
                ),
            ]
        ),
        "月": get_relation(
            [
                notion_helper.get_month_relation_id(
                    datetime.utcfromtimestamp(timestamp) + timedelta(hours=8)
                ),
            ]
        ),
        "周": get_relation(
            [
                notion_helper.get_week_relation_id(
                    datetime.utcfromtimestamp(timestamp) + timedelta(hours=8)
                ),
            ]
        ),
    }
    
    try:
        if page_id is not None:
            notion_helper.client.pages.update(page_id=page_id, properties=properties)
            logging.info(f"更新Notion页面 {page_id} 成功")
        else:
            notion_helper.client.pages.create(
                parent=parent,
                icon=get_icon("https://www.notion.so/icons/target_red.svg"),
                properties=properties,
            )
            logging.info(f"创建新的Notion页面成功")
    except Exception as e:
        logging.error(f"更新Notion失败: {e}")


def get_file():
    """获取热力图文件"""
    # 设置文件夹路径
    folder_path = "./OUT_FOLDER"

    # 检查文件夹是否存在
    if os.path.exists(folder_path) and os.path.isdir(folder_path):
        entries = os.listdir(folder_path)
        file_name = entries[0] if entries else None
        return file_name
    else:
        logging.warning("OUT_FOLDER does not exist.")
        return None


def main():
    notion_helper = NotionHelper()
    weread_api = WeReadApi()
    
    # 先处理热力图更新
    image_file = get_file()
    if image_file:
        image_url = f"https://raw.githubusercontent.com/{os.getenv('REPOSITORY')}/{os.getenv('REF').split('/')[-1]}/OUT_FOLDER/{image_file}"
        heatmap_url = f"https://heatmap.malinkang.com/?image={image_url}"
        if notion_helper.heatmap_block_id:
            try:
                response = notion_helper.update_heatmap(
                    block_id=notion_helper.heatmap_block_id, url=heatmap_url
                )
                logging.info(f"热力图更新成功: {heatmap_url}")
            except Exception as e:
                logging.error(f"更新热力图失败: {e}")
        else:
            logging.warning(f"更新热力图失败，没有添加热力图占位。具体参考：{HEATMAP_GUIDE}")
    else:
        logging.warning(f"更新热力图失败，没有生成热力图。具体参考：{HEATMAP_GUIDE}")
    
    # 获取阅读数据
    try:
        api_data = weread_api.get_api_data()
        readTimes = {int(key): value for key, value in api_data.get("readTimes", {}).items()}
        
        # 确保今天的数据存在（即使为0）
        now = pendulum.now("Asia/Shanghai").start_of("day")
        today_timestamp = now.int_timestamp
        if today_timestamp not in readTimes:
            readTimes[today_timestamp] = 0
        
        # 按时间戳排序
        readTimes = dict(sorted(readTimes.items()))
        
        # 同步到Notion
        results = notion_helper.query_all(database_id=notion_helper.day_database_id)
        
        # 更新已存在的记录
        for result in results:
            timestamp = result.get("properties", {}).get("时间戳", {}).get("number")
            duration = result.get("properties", {}).get("时长", {}).get("number")
            id = result.get("id")
            
            if timestamp in readTimes:
                value = readTimes.pop(timestamp)  # 移除已处理的时间戳
                if value != duration:
                    insert_to_notion(page_id=id, timestamp=timestamp, duration=value)
        
        # 添加新记录
        for key, value in readTimes.items():
            insert_to_notion(None, int(key), value)
            
        logging.info(f"阅读时间同步完成，共处理 {len(results) + len(readTimes)} 条记录")
            
    except Exception as e:
        logging.error(f"获取阅读数据失败: {e}")
        if "Cookie过期" in str(e):
            logging.error("请更新微信读书Cookie！")


if __name__ == "__main__":
    main()
