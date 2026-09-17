"""RPG 提示词的每用户覆盖。读写 User.rpg_prompts，CRUD 走 user_prompts 工厂。

不加 require_admin：小说侧那个 /api/prompts 改的是磁盘上的共享模板文件，
所以只给管理员；这里是每用户各存一份 JSON，互不影响，谁都能改自己的。
"""
from app.api.routes.user_prompts import PromptOut, PromptUpdate, create_user_prompts_router  # noqa: F401
from app.services import rpg_prompts


router, list_prompts, update_prompt, reset_prompt = create_user_prompts_router(
    rpg_prompts, "rpg_prompts", "未知的 RPG 提示词"
)
