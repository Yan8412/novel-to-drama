import pytest

from app.config import reset_settings_for_tests
from app.models import Character, NovelSettings, Project
from app.storage import ProjectStore, set_store


@pytest.fixture
def settings(tmp_path):
    s = reset_settings_for_tests(data_dir=str(tmp_path / "data"))
    return s


@pytest.fixture
def store(settings):
    st = ProjectStore(settings.projects_path)
    set_store(st)
    return st


@pytest.fixture
def project(store):
    p = Project(
        name="测试项目",
        settings=NovelSettings(
            genre="悬疑推理",
            premise="一把旧钥匙把两个陌生人卷进二十年前的失踪案。",
            chapter_count=2,
            target_word_count=1600,
            shots_per_chapter=3,
            characters=[
                Character(name="林晚", role="主角", traits="冷静", appearance="二十八岁女性，齐肩黑发，米白色针织衫"),
                Character(name="顾言", role="知情人", traits="油滑", appearance="三十二岁男性，寸头，眉骨有疤"),
            ],
        ),
    )
    store.create(p)
    return p
