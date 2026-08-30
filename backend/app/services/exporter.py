"""稿件导出：把库里的章节导成可直接投稿的纯文本。

番茄/起点的作者后台都是粘贴或上传纯文本，所以只做 txt（整本单文件 / 分章 zip），
不引入 docx 依赖。正文统一走 strip_plot_suggestions，避免把模型自行附加的
"接下来剧情可以这样发展：A/B/C" 尾巴一起投出去。
"""
import io
import re
import zipfile

from app.models.chapter import Chapter
from app.models.novel import Novel
from app.services.summarizer import strip_plot_suggestions

_ILLEGAL_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|\r\n\t]')


def safe_filename(name: str, fallback: str = "未命名") -> str:
    """清掉 Windows/Linux 都不接受的字符，并掐掉过长的名字。"""
    cleaned = _ILLEGAL_FILENAME_CHARS.sub("_", name or "").strip().strip(".")
    return (cleaned or fallback)[:80]


def chapter_heading(chapter: Chapter) -> str:
    title = (chapter.title or "").strip()
    return f"第{chapter.number}章 {title}".rstrip() if title else f"第{chapter.number}章"


def clean_body(chapter: Chapter) -> str:
    return strip_plot_suggestions(chapter.content or "").strip()


def build_single_txt(novel: Novel, chapters: list[Chapter]) -> str:
    """整本一个 txt：书名 + 简介在前，章节依次拼接。"""
    parts: list[str] = [novel.title or "未命名"]
    if (novel.blurb or "").strip():
        parts.append(f"\n【简介】\n{novel.blurb.strip()}")
    if novel.submission_tags:
        parts.append(f"\n【标签】{' '.join(novel.submission_tags)}")
    parts.append("")

    for ch in chapters:
        parts.append(f"\n\n{chapter_heading(ch)}\n\n{clean_body(ch)}")
    return "\n".join(parts).strip() + "\n"


def build_chapter_zip(novel: Novel, chapters: list[Chapter]) -> bytes:
    """分章 zip：一章一个 txt，文件名带序号保证解压后顺序正确。"""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for ch in chapters:
            name = safe_filename(f"{ch.number:04d}_{(ch.title or '').strip()}".rstrip("_"))
            zf.writestr(f"{name}.txt", f"{chapter_heading(ch)}\n\n{clean_body(ch)}\n")
    return buffer.getvalue()
