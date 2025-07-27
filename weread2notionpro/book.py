import pendulum
from weread2notionpro.notion_helper import NotionHelper
from weread2notionpro.weread_api import WeReadApi
from weread2notionpro import utils
from weread2notionpro.config import book_properties_type_dict, tz

TAG_ICON_URL = "https://www.notion.so/icons/tag_gray.svg"
USER_ICON_URL = "https://www.notion.so/icons/user-circle-filled_gray.svg"
BOOK_ICON_URL = "https://www.notion.so/icons/book_gray.svg"
rating = {"poor": "⭐️", "fair": "⭐️⭐️⭐️", "good": "⭐️⭐️⭐️⭐️⭐️"}

def get_cover_url(cover_data):
    """从封面数据中提取URL"""
    # 如果封面数据是字符串，直接返回
    if isinstance(cover_data, str):
        return cover_data.replace("/s_", "/t7_")
    
    # 如果封面数据是字典，尝试提取URL
    if isinstance(cover_data, dict):
        # 尝试不同尺寸的封面
        for size in ["large", "medium", "small"]:
            if size in cover_data:
                url = cover_data[size]
                if isinstance(url, str) and url.startswith("http"):
                    return url.replace("/s_", "/t7_")
    
    # 默认返回书籍图标
    return BOOK_ICON_URL

def insert_book_to_notion(books, index, bookId):
    """插入Book到Notion"""
    book = {}
    if bookId in archive_dict:
        book["书架分类"] = archive_dict.get(bookId)
    if bookId in notion_books:
        book.update(notion_books.get(bookId))
    
    # 获取书籍信息
    bookInfo = weread_api.get_bookinfo(bookId)
    if bookInfo != None:
        book.update(bookInfo)
    
    # 获取阅读信息
    readInfo = weread_api.get_read_info(bookId)
    if readInfo:
        readInfo.update(readInfo.get("readDetail", {}))
        readInfo.update(readInfo.get("bookInfo", {}))
        book.update(readInfo)
        
        # 处理阅读状态
        book["阅读进度"] = (
            100 if (book.get("markedStatus") == 4) else book.get("readingProgress", 0)
        ) / 100
        
        markedStatus = book.get("markedStatus")
        status = "想读"
        if markedStatus == 4:
            status = "已读"
        elif book.get("readingTime", 0) >= 60:
            status = "在读"
        
        book["阅读状态"] = status
        book["阅读时长"] = book.get("readingTime")
        book["阅读天数"] = book.get("totalReadDay")
        book["评分"] = book.get("newRating")
        
        # 处理评分
        if book.get("newRatingDetail") and book.get("newRatingDetail").get("myRating"):
            book["我的评分"] = rating.get(book.get("newRatingDetail").get("myRating"))
        elif status == "已读":
            book["我的评分"] = "未评分"
        
        # 处理时间信息
        book["时间"] = (
            book.get("finishedDate")
            or book.get("lastReadingDate")
            or book.get("readingBookDate")
        )
        book["开始阅读时间"] = book.get("beginReadingDate")
        book["最后阅读时间"] = book.get("lastReadingDate")
    
    # 处理封面图片
    cover_data = book.get("cover")
    cover = get_cover_url(cover_data)
    
    # 如果是新书，添加基本信息
    if bookId not in notion_books:
        book["书名"] = book.get("title")
        book["BookId"] = book.get("bookId")
        book["ISBN"] = book.get("isbn")
        book["链接"] = weread_api.get_url(bookId)
        book["简介"] = book.get("intro")
        
        # 处理作者信息
        author = book.get("author", "")
        if author:
            book["作者"] = [
                notion_helper.get_relation_id(
                    x, notion_helper.author_database_id, USER_ICON_URL
                )
                for x in author.split(" ")
            ]
        
        # 处理分类信息
        if book.get("categories"):
            book["分类"] = [
                notion_helper.get_relation_id(
                    x.get("title"), notion_helper.category_database_id, TAG_ICON_URL
                )
                for x in book.get("categories")
            ]
    
    # 创建属性
    properties = utils.get_properties(book, book_properties_type_dict)
    
    # 添加日期关系
    if book.get("时间"):
        notion_helper.get_date_relation(
            properties,
            pendulum.from_timestamp(book.get("时间"), tz="Asia/Shanghai"),
        )

    print(
        f"正在插入《{book.get('title')}》,一共{len(books)}本，当前是第{index+1}本。"
    )
    
    # 插入或更新Notion页面
    parent = {"database_id": notion_helper.book_database_id, "type": "database_id"}
    result = None
    
    if bookId in notion_books:
        result = notion_helper.update_page(
            page_id=notion_books.get(bookId).get("pageId"),
            properties=properties,
            cover=utils.get_icon(cover),
        )
    else:
        result = notion_helper.create_book_page(
            parent=parent,
            properties=properties,
            icon=utils.get_icon(cover),
        )
    
    # 处理阅读数据
    if result:
        page_id = result.get("id")
        if book.get("readDetail") and book.get("readDetail").get("data"):
            data = book.get("readDetail").get("data")
            data = {item.get("readDate"): item.get("readTime") for item in data}
            insert_read_data(page_id, data)


def insert_read_data(page_id, readTimes):
    readTimes = dict(sorted(readTimes.items()))
    filter = {"property": "书架", "relation": {"contains": page_id}}
    results = notion_helper.query_all_by_book(notion_helper.read_database_id, filter)
    for result in results:
        timestamp = result.get("properties").get("时间戳").get("number")
        duration = result.get("properties").get("时长").get("number")
        id = result.get("id")
        if timestamp in readTimes:
            value = readTimes.pop(timestamp)
            if value != duration:
                insert_to_notion(
                    page_id=id,
                    timestamp=timestamp,
                    duration=value,
                    book_database_id=page_id,
                )
    for key, value in readTimes.items():
        insert_to_notion(None, int(key), value, page_id)


def insert_to_notion(page_id, timestamp, duration, book_database_id):
    parent = {"database_id": notion_helper.read_database_id, "type": "database_id"}
    properties = {
        "标题": utils.get_title(
            pendulum.from_timestamp(timestamp, tz=tz).to_date_string()
        ),
        "日期": utils.get_date(
            start=pendulum.from_timestamp(timestamp, tz=tz).format(
                "YYYY-MM-DD HH:mm:ss"
            )
        ),
        "时长": utils.get_number(duration),
        "时间戳": utils.get_number(timestamp),
        "书架": utils.get_relation([book_database_id]),
    }
    if page_id != None:
        notion_helper.client.pages.update(page_id=page_id, properties=properties)
    else:
        notion_helper.client.pages.create(
            parent=parent,
            icon=utils.get_icon("https://www.notion.so/icons/target_red.svg"),
            properties=properties,
        )


weread_api = WeReadApi()
notion_helper = NotionHelper()
archive_dict = {}
notion_books = {}


def main():
    global notion_books
    global archive_dict
    
    # 获取书架数据
    bookshelf_books = weread_api.get_bookshelf()
    if not bookshelf_books:
        print("无法获取书架数据，请检查网络连接或Cookie是否有效")
        return
    
    # 获取Notion中已有的书籍
    notion_books = notion_helper.get_all_book()
    
    # 处理阅读进度
    bookProgress = bookshelf_books.get("bookProgress", [])
    bookProgress_dict = {book.get("bookId"): book for book in bookProgress}
    
    # 处理归档信息
    archive_list = bookshelf_books.get("archive", [])
    for archive in archive_list:
        name = archive.get("name")
        bookIds = archive.get("bookIds", [])
        archive_dict.update({bookId: name for bookId in bookIds})
    
    # 确定不需要同步的书籍
    not_need_sync = []
    for key, value in notion_books.items():
        book_progress = bookProgress_dict.get(key, {})
        if (
            (
                key not in bookProgress_dict
                or value.get("readingTime") == book_progress.get("readingTime")
            )
            and (archive_dict.get(key) == value.get("category"))
            and (value.get("cover") is not None)
            and (
                value.get("status") != "已读"
                or (value.get("status") == "已读" and value.get("myRating"))
            )
        ):
            not_need_sync.append(key)
    
    # 获取笔记本中的书籍
    notebooks = weread_api.get_notebooklist()
    if notebooks:
        notebooks = [d["bookId"] for d in notebooks if "bookId" in d]
    else:
        notebooks = []
    
    # 获取书架中的书籍
    books = bookshelf_books.get("books", [])
    if books:
        books = [d["bookId"] for d in books if "bookId" in d]
    else:
        books = []
    
    # 确定需要同步的书籍列表
    books = list((set(notebooks) | set(books)) - set(not_need_sync))
    
    # 同步每本书籍
    for index, bookId in enumerate(books):
        insert_book_to_notion(books, index, bookId)


if __name__ == "__main__":
    main()
