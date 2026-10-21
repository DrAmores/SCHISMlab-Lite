import os
os.environ["SCHISMLAB_NO_UPDATE_CHECK"] = "1"   # sin consultas a GitHub en los tests
pytest_plugins = ["nicegui.testing.user_plugin"]

