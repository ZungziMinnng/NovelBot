"""酒馆提示词的每用户覆盖。读写 User.tavern_prompts，CRUD 走 user_prompts 工厂。"""
from app.api.routes.user_prompts import PromptOut, PromptUpdate, create_user_prompts_router  # noqa: F401
from app.services import tavern_prompts


router, list_prompts, update_prompt, reset_prompt = create_user_prompts_router(
    tavern_prompts, "tavern_prompts", "未知的酒馆提示词"
)
