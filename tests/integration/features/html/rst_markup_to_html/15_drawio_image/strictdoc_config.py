from strictdoc.core.project_config import ProjectConfig

# This test requires a real draw.io desktop install at this path, and will
# only pass on a machine that has one (macOS default install location).
DRAWIO_EXECUTABLE_PATH = (
    "/Applications/draw.io.app/Contents/MacOS/draw.io"
)


def create_config() -> ProjectConfig:
    config = ProjectConfig(
        drawio_executable_path=DRAWIO_EXECUTABLE_PATH,
    )
    return config
