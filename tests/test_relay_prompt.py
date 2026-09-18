import unittest

from fleetbroker import relay


class TestRelayPrompt(unittest.TestCase):
    def test_hu_prompt_contains_allow_and_deny_list(self):
        cfg = {
            "target_tmux_session": "claude",
            "forbidden_tmux_sessions": ["deepseek", "glm"],
            "forbidden_peer_names": ["OtherSiteFleetNode"],
            "prompt_locale": "hu",
        }
        prompt = relay.build_prompt(cfg, "BODY TEXT")
        self.assertIn("BODY TEXT", prompt)
        self.assertIn("ListAgents", prompt)
        self.assertIn("SendMessage", prompt)
        self.assertIn("tmux 'claude'", prompt)
        self.assertIn("'deepseek'", prompt)
        self.assertIn("'glm'", prompt)
        self.assertIn("'OtherSiteFleetNode'", prompt)
        self.assertIn("ne improvizalj mas celt", prompt)

    def test_en_prompt_contains_allow_and_deny_list(self):
        cfg = {
            "target_tmux_session": "claude",
            "forbidden_tmux_sessions": ["deepseek"],
            "forbidden_peer_names": [],
            "prompt_locale": "en",
        }
        prompt = relay.build_prompt(cfg, "BODY TEXT")
        self.assertIn("BODY TEXT", prompt)
        self.assertIn("tmux session 'claude'", prompt)
        self.assertIn("'deepseek'", prompt)
        self.assertIn("do not improvise a different target", prompt)

    def test_no_forbidden_lists_omits_the_clause_cleanly(self):
        cfg = {"target_tmux_session": "claude", "prompt_locale": "en"}
        prompt = relay.build_prompt(cfg, "BODY")
        self.assertIn("tmux session 'claude'.", prompt)  # no dangling "( )"
        self.assertNotIn("()", prompt)

    def test_defaults_to_hungarian_when_locale_unset(self):
        cfg = {"target_tmux_session": "claude"}
        prompt = relay.build_prompt(cfg, "x")
        self.assertIn("Hasznald a ListAgents toolt", prompt)


if __name__ == "__main__":
    unittest.main()
