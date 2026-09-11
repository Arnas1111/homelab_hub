"""Exercise stats and connector isolation without a Docker daemon or appdata writes."""
import ast
from pathlib import Path
import unittest
from unittest.mock import Mock


def load_functions(*names, **dependencies):
    tree = ast.parse((Path(__file__).parents[1] / "app/main.py").read_text(encoding="utf-8"))
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    for node in functions:
        node.decorator_list = []
    namespace = {"Request": object, **dependencies}
    exec(compile(ast.Module(body=functions, type_ignores=[]), "main.py", "exec"), namespace)
    return namespace


class BackendTests(unittest.TestCase):
    def test_cpu_uses_interval_and_can_exceed_one_core(self):
        cpu = load_functions("cpu_percent")["cpu_percent"]
        stats = {
            "cpu_stats": {"cpu_usage": {"total_usage": 300}, "system_cpu_usage": 1800, "online_cpus": 8},
            "precpu_stats": {"cpu_usage": {"total_usage": 100}, "system_cpu_usage": 1000},
        }
        self.assertEqual(cpu(stats), 200.0)
        self.assertEqual(cpu({}), 0.0)

    def test_running_container_requests_two_samples(self):
        container = Mock()
        container.attrs = {"State": {"Running": True}}
        container.stats.return_value = {}
        funcs = load_functions("collect_container", "cpu_percent", "mem_values")
        funcs["collect_container"](container)
        container.stats.assert_called_once_with(stream=False, one_shot=False)

    def test_docker_discovery_failure_does_not_block_home_assistant(self):
        ha = Mock(return_value={"entities": [{"entity_id": "light.test"}]})
        funcs = load_functions(
            "integrations", require_auth=Mock(),
            integration_config=lambda: {"jellyfin_url": "", "jellyfin_api_key": "", "home_assistant_url": ""},
            docker_client=Mock(side_effect=RuntimeError("offline")), home_assistant_state=ha,
        )
        result = funcs["integrations"](object())
        self.assertIn("error", result["jellyfin"])
        self.assertEqual(result["home_assistant"]["entities"][0]["entity_id"], "light.test")
        ha.assert_called_once()

    def test_explicit_jellyfin_url_needs_no_docker_client(self):
        docker = Mock(side_effect=AssertionError("Docker should not be needed"))
        funcs = load_functions(
            "integrations", require_auth=Mock(), docker_client=docker,
            integration_config=lambda: {"jellyfin_url": "http://example.invalid", "home_assistant_url": ""},
            jellyfin_sessions=Mock(return_value={"active": []}),
            home_assistant_state=Mock(side_effect=ValueError("invalid response")),
        )
        result = funcs["integrations"](object())
        self.assertEqual(result["jellyfin"], {"active": []})
        self.assertIn("error", result["home_assistant"])
        docker.assert_not_called()


if __name__ == "__main__":
    unittest.main()
