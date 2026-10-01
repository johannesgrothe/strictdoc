import os

from py_draw_io.exporter import DrawIoExporter, ExportFailedError

from strictdoc.backend.rst.rst_to_html_fragment_writer import (
    RstToHtmlFragmentWriter,
)
from strictdoc.core.project_config import ProjectConfig

FIXTURES_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "fixtures")
)
RENDERED_PNG_PATH = os.path.join(
    FIXTURES_PATH, "_assets", "diagram__pagerino.png"
)


def _fake_export_writes_file(_self, *, out_path, **_kwargs):
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "wb") as file_:
        file_.write(b"fake-png-bytes")


def _project_config_with_drawio(tmp_path) -> ProjectConfig:
    project_config = ProjectConfig.default_config()
    project_config.drawio_executable_path = "/usr/local/bin/drawio"
    project_config.get_path_to_cache_dir = lambda: str(tmp_path / "cache")
    return project_config


def test_drawio_image_01_default_page(tmp_path, monkeypatch):
    monkeypatch.setattr(DrawIoExporter, "export", _fake_export_writes_file)

    rst_input = """
.. drawio-image:: _assets/diagram.drawio
""".lstrip()

    project_config = _project_config_with_drawio(tmp_path)
    html_output = RstToHtmlFragmentWriter(
        project_config=project_config,
        context_document=None,
        reference_path_override=FIXTURES_PATH,
    ).write(rst_input, use_cache=False)

    try:
        assert (
            str(html_output)
            == """\
<div class="document">
<img alt="_assets/diagram__pagerino.png" src="_assets/diagram__pagerino.png" />
</div>
"""
        )
        assert os.path.isfile(RENDERED_PNG_PATH)
    finally:
        if os.path.isfile(RENDERED_PNG_PATH):
            os.remove(RENDERED_PNG_PATH)


def test_drawio_image_02_explicit_page(tmp_path, monkeypatch):
    monkeypatch.setattr(DrawIoExporter, "export", _fake_export_writes_file)

    rst_input = """
.. drawio-image:: _assets/diagram.drawio
   :page: pagerino
""".lstrip()

    project_config = _project_config_with_drawio(tmp_path)
    html_output = RstToHtmlFragmentWriter(
        project_config=project_config,
        context_document=None,
        reference_path_override=FIXTURES_PATH,
    ).write(rst_input, use_cache=False)

    try:
        assert "diagram__pagerino.png" in str(html_output)
    finally:
        if os.path.isfile(RENDERED_PNG_PATH):
            os.remove(RENDERED_PNG_PATH)


def test_drawio_image_03_missing_file(tmp_path):
    rst_input = """
.. drawio-image:: _assets/does_not_exist.drawio
""".lstrip()

    project_config = _project_config_with_drawio(tmp_path)
    html_output, error = RstToHtmlFragmentWriter(
        project_config=project_config,
        context_document=None,
        reference_path_override=FIXTURES_PATH,
    ).write_with_validation(rst_input)
    assert html_output is None
    assert "file not found" in error


def test_drawio_image_04_executable_not_configured():
    rst_input = """
.. drawio-image:: _assets/diagram.drawio
""".lstrip()

    project_config = ProjectConfig.default_config()
    assert project_config.drawio_executable_path is None
    html_output, error = RstToHtmlFragmentWriter(
        project_config=project_config,
        context_document=None,
        reference_path_override=FIXTURES_PATH,
    ).write_with_validation(rst_input)
    assert html_output is None
    assert "drawio_executable_path" in error


def test_drawio_image_05_export_failure(tmp_path, monkeypatch):
    def _raise(_self, **_kwargs):
        raise ExportFailedError(1)

    monkeypatch.setattr(DrawIoExporter, "export", _raise)

    rst_input = """
.. drawio-image:: _assets/diagram.drawio
""".lstrip()

    project_config = _project_config_with_drawio(tmp_path)
    html_output, error = RstToHtmlFragmentWriter(
        project_config=project_config,
        context_document=None,
        reference_path_override=FIXTURES_PATH,
    ).write_with_validation(rst_input)
    assert html_output is None
    assert "failed to export" in error
