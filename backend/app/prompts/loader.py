from pathlib import Path
from jinja2 import Environment, FileSystemLoader

_TEMPLATE_DIR = Path(__file__).parent / "templates"
_env = Environment(loader=FileSystemLoader(str(_TEMPLATE_DIR)))


def render(template_name: str, **kwargs) -> str:
    """渲染 Jinja2 模板"""
    tmpl = _env.get_template(template_name)
    return tmpl.render(**kwargs)
