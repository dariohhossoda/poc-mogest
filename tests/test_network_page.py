import tempfile
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).parent.parent
PAGE = str(ROOT / "app" / "pages" / "2_Rede_Hidrologica.py")
SKIP = {".venv", ".git", "__pycache__", ".pytest_cache", ".ruff_cache"}


def _files(root: Path) -> set:
    return {
        p.relative_to(root)
        for p in root.rglob("*")
        if not SKIP.intersection(p.relative_to(root).parts)
    }


def _button(at: AppTest, label: str):
    return next(b for b in at.button if b.label == label)


def test_example_network_runs():
    at = AppTest.from_file(PAGE).run(timeout=60)
    assert not at.exception
    _button(at, "▶ Executar roteamento").click().run(timeout=60)
    assert not at.exception
    assert "network_result" in at.session_state


def test_delineation_mode_waits_for_points():
    at = AppTest.from_file(PAGE).run(timeout=60)
    at.checkbox(key="use_network_example").uncheck().run(timeout=60)
    at.radio(key="network_source").set_value("Delimitar a partir de um ponto")
    at.run(timeout=60)
    assert not at.exception
    assert any("Delimitar sub-bacias" in i.value for i in at.info)


@pytest.mark.slow
def test_delineation_from_glo30_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    before = _files(ROOT)

    at = AppTest.from_file(PAGE).run(timeout=60)
    at.checkbox(key="use_network_example").uncheck().run(timeout=60)
    at.radio(key="network_source").set_value("Delimitar a partir de um ponto")
    at.run(timeout=60)
    _button(at, "🗺️ Delimitar sub-bacias").click().run(timeout=300)

    assert not at.exception
    assert not at.error
    result = at.session_state["delineation"]
    assert len(result.params) == 6  # Cachoeira, as in mogest-network
    assert at.metric[0].value == "6"
    assert _files(ROOT) == before
    assert list(tmp_path.iterdir()) == []
